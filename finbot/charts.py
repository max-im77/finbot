"""Графики (matplotlib → PNG-байты)."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

_money = FuncFormatter(lambda x, _: f"{x:,.0f}".replace(",", " "))


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def deposit_chart(schedule, principal: float, title: str) -> bytes:
    months = [m for m, _ in schedule]
    bal = [b for _, b in schedule]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=140)
    ax.fill_between(months, [principal] * len(months), bal, alpha=0.25, color="#2e7d32", label="Проценты")
    ax.plot(months, bal, lw=2.5, color="#2e7d32", label="Баланс")
    ax.axhline(principal, ls="--", lw=1, color="#555", label="Вложено")
    ax.set(title=title, xlabel="Месяцы", ylabel="Сумма")
    ax.yaxis.set_major_formatter(_money)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", frameon=False)
    return _png(fig)


def loan_chart(rows, title: str) -> bytes:
    x = [r.n for r in rows]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=140)
    ax.bar(x, [r.principal for r in rows], color="#1565c0", label="Основной долг")
    ax.bar(x, [r.interest for r in rows], bottom=[r.principal for r in rows],
           color="#e53935", label="Проценты")
    ax.set(title=title, xlabel="Месяц платежа", ylabel="Платёж")
    ax.yaxis.set_major_formatter(_money)
    ax.grid(alpha=0.3, axis="y")
    ax.set_ylim(0, max(r.payment for r in rows) * 1.18)  # запас сверху под легенду
    ax.legend(loc="upper center", ncol=2, frameon=False)
    return _png(fig)
