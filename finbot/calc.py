"""Чистая финансовая математика. Никаких зависимостей от Telegram — легко тестировать."""
from __future__ import annotations

import math
from dataclasses import dataclass

# Сколько раз в год капитализируются проценты. 0 = простые проценты, выплата в конце срока.
CAP_PERIODS = {"daily": 365, "monthly": 12, "quarterly": 4, "yearly": 1, "end": 0}
CAP_LABELS = {
    "daily": "ежедневная",
    "monthly": "ежемесячная",
    "quarterly": "ежеквартальная",
    "yearly": "ежегодная",
    "end": "нет (проценты в конце срока)",
}


# ───────────────────────────── ВКЛАДЫ ─────────────────────────────

def deposit_balance(principal: float, rate_pct: float, months: float, cap: str = "monthly") -> float:
    """Сумма на вкладе через `months` месяцев.

    Целые периоды капитализации считаются по сложному проценту,
    неполный «хвост» периода — по простому (так делает большинство банков).
    """
    r = rate_pct / 100
    t = months / 12
    n = CAP_PERIODS[cap]
    if n == 0:
        return principal * (1 + r * t)
    periods = n * t
    k = math.floor(periods + 1e-9)
    rem = max(periods - k, 0.0)
    return principal * (1 + r / n) ** k * (1 + r / n * rem)


def effective_rate(rate_pct: float, cap: str) -> float:
    """Эффективная годовая ставка (EAR), %."""
    n = CAP_PERIODS[cap]
    if n == 0:
        return rate_pct
    return ((1 + rate_pct / 100 / n) ** n - 1) * 100


@dataclass
class DepositResult:
    principal: float
    rate: float
    months: int
    cap: str
    final: float
    profit: float
    effective_rate: float
    schedule: list[tuple[int, float]]  # (месяц, баланс)


def calc_deposit(principal: float, rate_pct: float, months: int, cap: str = "monthly") -> DepositResult:
    final = deposit_balance(principal, rate_pct, months, cap)
    schedule = [(m, deposit_balance(principal, rate_pct, m, cap)) for m in range(months + 1)]
    return DepositResult(principal, rate_pct, months, cap, final, final - principal,
                         effective_rate(rate_pct, cap), schedule)


@dataclass
class EarlyWithdrawal:
    month: int
    penalty_rate: float
    received: float
    full: float

    @property
    def lost(self) -> float:
        return self.full - self.received


def early_withdrawal(principal: float, rate_pct: float, months: int, cap: str,
                     withdraw_month: int, penalty_rate_pct: float = 0.01) -> EarlyWithdrawal:
    """«Подводный камень»: при досрочном снятии банк пересчитывает ВЕСЬ срок по штрафной ставке."""
    full = deposit_balance(principal, rate_pct, months, cap)
    received = deposit_balance(principal, penalty_rate_pct, withdraw_month, cap)
    return EarlyWithdrawal(withdraw_month, penalty_rate_pct, received, full)


# ───────────────────────────── КРЕДИТЫ ─────────────────────────────

@dataclass
class Payment:
    n: int
    payment: float
    interest: float
    principal: float
    balance: float


@dataclass
class LoanResult:
    principal: float
    rate: float
    months: int
    kind: str  # "annuity" | "diff"
    rows: list[Payment]

    @property
    def total_paid(self) -> float:
        return sum(r.payment for r in self.rows)

    @property
    def overpayment(self) -> float:
        return self.total_paid - self.principal

    def interest_in_first(self, n: int) -> float:
        return sum(r.interest for r in self.rows[:n])

    def paid_in_first(self, n: int) -> float:
        return sum(r.payment for r in self.rows[:n])


def loan_schedule(principal: float, rate_pct: float, months: int, kind: str = "annuity") -> LoanResult:
    i = rate_pct / 100 / 12
    bal = principal
    rows: list[Payment] = []
    if kind == "annuity":
        pay = principal / months if i == 0 else principal * i / (1 - (1 + i) ** -months)
    for n in range(1, months + 1):
        interest = bal * i
        body = (pay - interest) if kind == "annuity" else principal / months
        if n == months:  # убираем накопленную ошибку округления
            body = bal
        bal -= body
        rows.append(Payment(n, body + interest, interest, body, max(bal, 0.0)))
    return LoanResult(principal, rate_pct, months, kind, rows)
