"""Разбор свободного текста: «Вклад 500к 10% на год, капитализация каждый месяц»."""
from __future__ import annotations

import re
from dataclasses import dataclass


class UserError(Exception):
    """Ошибка, текст которой можно показать пользователю как есть."""


@dataclass
class Query:
    amount: float | None = None
    rate: float | None = None
    months: int | None = None
    cap: str | None = None
    kind: str = "annuity"
    withdraw_month: int | None = None
    penalty_rate: float | None = None


_NUM = r"\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_AMOUNT_RE = re.compile(rf"({_NUM})\s*(млн\w*|тыс\w*|к\b|k\b)?")
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|проц\w*)")
_TERM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(лет|год(?:а|ов)?|г|мес\w*|м)\b")
_WITHDRAW_RE = re.compile(r"через\s+(\d+(?:[.,]\d+)?)\s*(лет|год(?:а|ов)?|г|мес\w*|м)\b")

# порядок важен: «без капитализации» содержит слово «капитализац…»
_CAP_RULES = [
    ("end", r"в конце|без капитализ|простые проценты"),
    ("daily", r"ежедневн|каждый день|раз в день"),
    ("quarterly", r"ежеквартальн|раз в квартал|каждый квартал|квартальн"),
    ("yearly", r"ежегодн|раз в год|каждый год"),
    ("monthly", r"ежемесячн|каждый месяц|раз в месяц|месячн"),
]


def _num(s: str) -> float:
    return float(s.replace("\u00a0", "").replace(" ", "").replace(",", "."))


def _to_months(value: str, unit: str) -> int:
    v = _num(value)
    return max(1, round(v if unit.startswith("м") else v * 12))


def parse(text: str) -> Query:
    t = text.lower().replace("ё", "е")
    q = Query()
    if "дифф" in t:
        q.kind = "diff"

    # 1. «снять через N мес»
    m = _WITHDRAW_RE.search(t)
    if m:
        q.withdraw_month = _to_months(m.group(1), m.group(2))
        t = t[:m.start()] + " " + t[m.end():]

    # 2. проценты: первая — ставка, вторая — штрафная ставка при досрочном снятии
    pcts = _PCT_RE.findall(t)
    if pcts:
        q.rate = _num(pcts[0])
        if len(pcts) > 1:
            q.penalty_rate = _num(pcts[1])
        t = _PCT_RE.sub(" ", t)

    # 3. срок
    m = _TERM_RE.search(t)
    if m:
        q.months = _to_months(m.group(1), m.group(2))
        t = t[:m.start()] + " " + t[m.end():]
    elif re.search(r"полтора\s+года", t):
        q.months = 18
    elif "полгода" in t:
        q.months = 6
    elif re.search(r"\bгод\b", t):
        q.months = 12

    # 4. капитализация
    for cap, pattern in _CAP_RULES:
        if re.search(pattern, t):
            q.cap = cap
            break

    # 5. сумма — первое оставшееся число (с поддержкой «500к», «1.5 млн»)
    m = _AMOUNT_RE.search(t)
    if m:
        amount = _num(m.group(1))
        suffix = (m.group(2) or "")
        if suffix.startswith("млн"):
            amount *= 1_000_000
        elif suffix.startswith(("тыс", "к", "k")):
            amount *= 1_000
        q.amount = amount
    return q


# ───────────────────────── Валюты ─────────────────────────

_ALIASES = {
    "руб": "RUB", "₽": "RUB", "доллар": "USD", "бакс": "USD", "$": "USD",
    "евро": "EUR", "€": "EUR", "злот": "PLN", "фунт": "GBP", "£": "GBP",
    "юан": "CNY", "тенге": "KZT", "гривн": "UAH", "лир": "TRY", "иен": "JPY",
    "йен": "JPY", "франк": "CHF", "бел": "BYN",
}


def to_code(token: str) -> str | None:
    token = token.strip().lower()
    if re.fullmatch(r"[a-z]{3}", token):
        return token.upper()
    for prefix, code in _ALIASES.items():
        if token.startswith(prefix):
            return code
    return None


def parse_convert(text: str) -> tuple[float | None, list[str]]:
    """«100 usd в eur pln» → (100, ['USD', 'EUR', 'PLN'])."""
    m = _AMOUNT_RE.search(text.lower())
    amount = None
    rest = text
    if m:
        amount = _num(m.group(1))
        rest = text[:m.start()] + " " + text[m.end():]
    tokens = re.findall(r"[A-Za-z]{3}|[а-яёА-ЯЁ]+|[$€₽£]", rest)
    codes = [c for c in (to_code(tok) for tok in tokens) if c]
    return amount, codes
