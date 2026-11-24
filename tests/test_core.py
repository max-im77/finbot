import math
from datetime import date

from finbot import calc, parsing, render, storage


def test_monthly_capitalization():
    final = calc.deposit_balance(100_000, 10, 12, "monthly")
    assert math.isclose(final, 100_000 * (1 + 0.1 / 12) ** 12)
    assert math.isclose(calc.effective_rate(10, "monthly"), 10.4713, abs_tol=1e-3)


def test_simple_and_partial_periods():
    assert math.isclose(calc.deposit_balance(100_000, 10, 6, "end"), 105_000)
    # 18 месяцев, ежегодная капитализация: 1 полный год + полгода простых
    assert math.isclose(calc.deposit_balance(100, 10, 18, "yearly"), 100 * 1.1 * 1.05)


def test_early_withdrawal():
    ew = calc.early_withdrawal(500_000, 10, 12, "monthly", 3, 0.01)
    assert ew.received < 500_500 and ew.lost > 50_000


def test_annuity_loan():
    res = calc.loan_schedule(500_000, 14, 36)
    assert math.isclose(sum(r.principal for r in res.rows), 500_000)
    assert abs(res.rows[-1].balance) < 1e-6
    pays = {round(r.payment, 2) for r in res.rows[:-1]}
    assert len(pays) == 1
    assert res.overpayment > 0


def test_zero_rate_and_diff():
    res = calc.loan_schedule(120_000, 0, 12)
    assert math.isclose(res.overpayment, 0, abs_tol=1e-6)
    d = calc.loan_schedule(120_000, 12, 12, "diff")
    assert d.rows[0].payment > d.rows[-1].payment
    assert math.isclose(sum(r.principal for r in d.rows), 120_000)


def test_parse_deposit_example_from_brief():
    q = parsing.parse("Вклад 10% на год, капитализация каждый месяц")
    assert (q.rate, q.months, q.cap, q.amount) == (10, 12, "monthly", None)


def test_parse_variants():
    q = parsing.parse("вклад 1.5 млн под 9,5% на 18 месяцев ежедневно, снять через 3 месяца, штраф 0.01%")
    assert q.amount == 1_500_000 and q.rate == 9.5 and q.months == 18
    assert q.cap == "daily" and q.withdraw_month == 3 and q.penalty_rate == 0.01
    q = parsing.parse("кредит 500 000 на 3 года под 14%")
    assert q.amount == 500_000 and q.months == 36 and q.rate == 14
    assert parsing.parse("500к на полгода 8% без капитализации").cap == "end"
    assert parsing.parse("дифф кредит 100к 12% на 2 года").kind == "diff"


def test_parse_convert():
    assert parsing.parse_convert("100 usd в eur pln") == (100, ["USD", "EUR", "PLN"])
    assert parsing.parse_convert("1 500 долларов в злотых") == (1500, ["USD", "PLN"])


def test_render_deposit_and_trap():
    r = render.deposit(parsing.parse("вклад 500к 10% на год ежемесячно, снять через 3 месяца"))
    assert "Эффективная ставка" in r.text and "досрочное снятие" in r.text
    assert r.photo and r.photo[:4] == b"\x89PNG"


def test_render_loan():
    r = render.loan(parsing.parse("кредит 500000 на 3 года под 14%"))
    assert "Переплата" in r.text and "Первые 3 месяца" in r.text
    assert r.document and r.photo


def test_render_compare_and_errors():
    r = render.compare("500к на год: 10% ежемесячно; 10.3% в конце срока; 9.8% ежедневно")
    assert "✅" in r.text
    for bad in (lambda: render.deposit(parsing.parse("вклад")), lambda: render.loan(parsing.parse("кредит 100"))):
        try:
            bad()
            assert False
        except parsing.UserError:
            pass


def test_render_convert():
    out = render.convert(100, ["USD", "EUR"], {"USD": 1.0, "EUR": 0.9})
    assert "90.00" in out


def test_next_charge():
    assert storage.next_charge(31, date(2026, 2, 10)) == date(2026, 2, 28)
    assert storage.next_charge(5, date(2026, 12, 20)) == date(2027, 1, 5)
    assert storage.next_charge(25, date(2026, 11, 25)) == date(2026, 11, 25)
