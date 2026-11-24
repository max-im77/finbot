"""Превращает расчёты в готовые сообщения (HTML для Telegram). Без обращения к Telegram API."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from . import calc, charts, parsing
from .parsing import Query, UserError

NBSP = "\u00a0"


@dataclass
class Reply:
    text: str
    photo: bytes | None = None
    document: tuple[str, bytes] | None = None


def money(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}".replace(",", NBSP)


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return forms[1]
    return forms[2]


def term_str(months: int) -> str:
    y, m = divmod(months, 12)
    parts = []
    if y:
        parts.append(f"{y} {plural(y, ('год', 'года', 'лет'))}")
    if m:
        parts.append(f"{m} {plural(m, ('месяц', 'месяца', 'месяцев'))}")
    return " ".join(parts)


def _check(amount, rate, months):
    if amount is not None and not 0 < amount < 1e12:
        raise UserError("Сумма должна быть положительной.")
    if rate is not None and not 0 <= rate <= 200:
        raise UserError("Ставка должна быть от 0 до 200% годовых.")
    if months is not None and not 1 <= months <= 600:
        raise UserError("Срок — от 1 до 600 месяцев.")


# ───────────────────────────── ВКЛАД ─────────────────────────────

def deposit(q: Query) -> Reply:
    if q.rate is None:
        raise UserError("Не нашёл ставку. Пример:\n<code>/deposit 500к 10% на год, капитализация каждый месяц</code>")
    notes = []
    amount, months, cap = q.amount, q.months, q.cap
    if amount is None:
        amount = 100_000
        notes.append("сумма не указана — взял 100 000")
    if months is None:
        months = 12
        notes.append("срок не указан — взял 12 месяцев")
    if cap is None:
        cap = "monthly"
        notes.append("капитализация не указана — взял ежемесячную")
    _check(amount, q.rate, months)

    res = calc.calc_deposit(amount, q.rate, months, cap)
    simple = calc.deposit_balance(amount, q.rate, months, "end")

    lines = [
        f"💰 <b>Вклад {money(amount)}</b> на {term_str(months)} под {q.rate:g}% годовых",
        f"Капитализация: {calc.CAP_LABELS[cap]}",
        "",
        f"Итого к получению: <b>{money(res.final)}</b>",
        f"Доход: <b>+{money(res.profit)}</b>",
        f"Эффективная ставка: <b>{res.effective_rate:.2f}%</b> (в рекламе — {q.rate:g}%)",
    ]
    if cap != "end":
        extra = res.final - simple
        lines.append(f"Капитализация дала +{money(extra)} к простым процентам.")

    # как влияет капитализация
    table = ["Капитализация    Эфф.%    Итого"]
    for key in ("end", "yearly", "quarterly", "monthly", "daily"):
        label = {"end": "в конце срока", "yearly": "ежегодная", "quarterly": "ежеквартальная",
                 "monthly": "ежемесячная", "daily": "ежедневная"}[key]
        final = calc.deposit_balance(amount, q.rate, months, key)
        mark = "◀" if key == cap else " "
        table.append(f"{label:<15} {calc.effective_rate(q.rate, key):6.2f}  {money(final):>11} {mark}")
    lines += ["", "<pre>" + "\n".join(table) + "</pre>"]

    # подводный камень
    if q.withdraw_month is not None:
        if q.withdraw_month >= months:
            lines.append("⚠️ Срок снятия не меньше срока вклада — это уже не досрочно.")
        else:
            pen = q.penalty_rate if q.penalty_rate is not None else 0.01
            ew = calc.early_withdrawal(amount, q.rate, months, cap, q.withdraw_month, pen)
            lost_share = ew.lost / res.profit * 100 if res.profit else 0
            lines += [
                "⚠️ <b>Подводный камень: досрочное снятие</b>",
                f"Снимаете через {term_str(ew.month)} → банк пересчитает по ставке {pen:g}%.",
                f"Получите: <b>{money(ew.received)}</b> вместо {money(ew.full)}",
                f"Потеряете: <b>−{money(ew.lost)}</b> ({lost_share:.0f}% всех процентов)",
            ]
    else:
        lines.append("💡 Добавьте «снять через 3 мес», чтобы увидеть цену досрочного снятия.")
    if notes:
        lines += ["", "<i>" + "; ".join(notes) + "</i>"]

    chart = charts.deposit_chart(res.schedule, amount, f"Рост вклада: {q.rate:g}%, {calc.CAP_LABELS[cap]} капитализация")
    return Reply("\n".join(lines), photo=chart)


# ───────────────────────── СРАВНЕНИЕ ВКЛАДОВ ─────────────────────────

def compare(text: str) -> Reply:
    """/compare 500к на год: 10% ежемесячно; 10.3% в конце срока; 9.8% ежедневно"""
    if ":" in text:
        common, rest = text.split(":", 1)
        base = parsing.parse(common)
    else:
        rest = text
        base = parsing.parse(re.split(r"[;\n]", text)[0])
    segments = [s for s in re.split(r"[;\n]", rest) if s.strip()]
    if len(segments) < 2:
        raise UserError("Нужно минимум два вклада через «;». Пример:\n"
                        "<code>/compare 500к на год: 10% ежемесячно; 10.3% в конце срока</code>")
    amount = base.amount or 100_000
    months = base.months or 12
    rows = []
    for seg in segments:
        q = parsing.parse(seg)
        if q.rate is None:
            raise UserError(f"В «{seg.strip()}» не нашёл ставку.")
        a, mo, cap = q.amount or amount, q.months or months, q.cap or "monthly"
        _check(a, q.rate, mo)
        final = calc.deposit_balance(a, q.rate, mo, cap)
        rows.append((q.rate, cap, calc.effective_rate(q.rate, cap), final, a, mo))
    rows.sort(key=lambda r: r[3], reverse=True)

    out = [f"⚖️ <b>Сравнение вкладов</b> ({money(amount)}, {term_str(months)})", ""]
    table = ["   Ставка Капитал.      Эфф.%     Итого"]
    for i, (rate, cap, eff, final, *_rest) in enumerate(rows):
        mark = "✅" if i == 0 else "  "
        label = {"end": "в конце", "yearly": "ежегодно", "quarterly": "ежекварт.",
                 "monthly": "ежемес.", "daily": "ежедневно"}[cap]
        table.append(f"{mark} {rate:5g}% {label:<10} {eff:6.2f} {money(final):>11}")
    out.append("<pre>" + "\n".join(table) + "</pre>")
    best, worst = rows[0], rows[-1]
    out.append(f"Лучший вариант даёт на <b>{money(best[3] - worst[3])}</b> больше худшего.")
    out.append("<i>Сравнивайте по эффективной ставке, а не по цифре в рекламе.</i>")
    return Reply("\n".join(out))


# ───────────────────────────── КРЕДИТ ─────────────────────────────

def loan(q: Query) -> Reply:
    if q.amount is None or q.rate is None or q.months is None:
        raise UserError("Нужны сумма, ставка и срок. Пример:\n"
                        "<code>/loan 500000 на 3 года под 14%</code>\n"
                        "Для дифференцированных платежей добавьте слово «дифф».")
    _check(q.amount, q.rate, q.months)
    res = calc.loan_schedule(q.amount, q.rate, q.months, q.kind)
    kind_label = "аннуитет" if q.kind == "annuity" else "дифференцированные платежи"
    n3 = min(3, q.months)
    int3, paid3 = res.interest_in_first(n3), res.paid_in_first(n3)
    year_n = min(12, q.months)
    int_year = res.interest_in_first(year_n)
    total_interest = sum(r.interest for r in res.rows)

    lines = [f"🏦 <b>Кредит {money(q.amount)}</b> на {term_str(q.months)} под {q.rate:g}% ({kind_label})", ""]
    if q.kind == "annuity":
        lines.append(f"Платёж: <b>{money(res.rows[0].payment)}</b> в месяц")
    else:
        lines.append(f"Первый платёж: <b>{money(res.rows[0].payment)}</b>, последний: {money(res.rows[-1].payment)}")
    lines += [
        f"Всего выплатите: <b>{money(res.total_paid)}</b>",
        f"Переплата: <b>{money(res.overpayment)}</b> (+{res.overpayment / q.amount * 100:.0f}% к сумме кредита)",
        "",
        f"😳 <b>Первые {n3} {plural(n3, ('месяц', 'месяца', 'месяцев'))}</b>: из {money(paid3)} выплат "
        f"на проценты уходит <b>{money(int3)}</b> ({int3 / paid3 * 100:.0f}%), на долг — только {money(paid3 - int3)}.",
    ]
    if total_interest > 0 and q.months > 12:
        lines.append(f"За первый год банк забирает {money(int_year)} — это {int_year / total_interest * 100:.0f}% "
                     f"всех процентов по кредиту.")

    table = ["  №    Платёж  Проценты      Долг"]
    for r in res.rows[:6]:
        table.append(f"{r.n:>3} {money(r.payment):>9} {money(r.interest):>9} {money(r.principal):>9}")
    if q.months > 6:
        table.append("  …")
    lines += ["", "<pre>" + "\n".join(table) + "</pre>", "Полный график — в файле ниже 👇"]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["month", "payment", "interest", "principal", "balance"])
    for r in res.rows:
        w.writerow([r.n, round(r.payment, 2), round(r.interest, 2), round(r.principal, 2), round(r.balance, 2)])
    chart = charts.loan_chart(res.rows, "Из чего состоит каждый платёж")
    return Reply("\n".join(lines), photo=chart, document=("schedule.csv", buf.getvalue().encode("utf-8-sig")))


# ───────────────────────────── ВАЛЮТЫ ─────────────────────────────

POPULAR = ["USD", "EUR", "PLN", "GBP", "RUB", "UAH", "CNY", "TRY"]


def convert(amount: float, codes: list[str], rates: dict[str, float], updated: str = "") -> str:
    unknown = [c for c in codes if c not in rates]
    codes = [c for c in codes if c in rates]
    if not codes:
        raise UserError("Не узнал валюту. Пример: <code>/convert 100 USD EUR</code>")
    src = codes[0]
    targets = codes[1:] or [c for c in POPULAR if c != src][:6]
    lines = [f"💱 <b>{money(amount, 2)} {src}</b>"]
    for dst in targets:
        value = amount / rates[src] * rates[dst]
        lines.append(f"≈ <b>{money(value, 2)}</b> {dst}  <i>(1 {src} = {rates[dst] / rates[src]:.4f} {dst})</i>")
    if unknown:
        lines.append(f"<i>Не знаю валюты: {', '.join(unknown)}</i>")
    if updated:
        lines.append(f"<i>Курсы обновлены: {updated}</i>")
    return "\n".join(lines)
