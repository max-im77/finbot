"""Подписки в SQLite."""
from __future__ import annotations

import os
import sqlite3
from calendar import monthrange
from dataclasses import dataclass
from datetime import date

DB_PATH = os.getenv("DB_PATH", "finbot.sqlite3")


@dataclass
class Sub:
    id: int
    chat_id: int
    name: str
    amount: float
    currency: str
    day: int


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS subs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, name TEXT NOT NULL,
        amount REAL NOT NULL, currency TEXT NOT NULL, day INTEGER NOT NULL)""")
    return conn


def add_sub(chat_id: int, name: str, amount: float, currency: str, day: int) -> int:
    with _conn() as c:
        return c.execute("INSERT INTO subs (chat_id,name,amount,currency,day) VALUES (?,?,?,?,?)",
                         (chat_id, name, amount, currency, day)).lastrowid


def list_subs(chat_id: int) -> list[Sub]:
    with _conn() as c:
        rows = c.execute("SELECT id,chat_id,name,amount,currency,day FROM subs WHERE chat_id=? ORDER BY day",
                         (chat_id,)).fetchall()
    return [Sub(*r) for r in rows]


def all_subs() -> list[Sub]:
    with _conn() as c:
        rows = c.execute("SELECT id,chat_id,name,amount,currency,day FROM subs").fetchall()
    return [Sub(*r) for r in rows]


def delete_sub(chat_id: int, sub_id: int) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM subs WHERE id=? AND chat_id=?", (sub_id, chat_id)).rowcount > 0


def next_charge(day: int, today: date) -> date:
    """Ближайшая дата списания (день 31 в коротком месяце → последний день месяца)."""
    def clamp(y: int, m: int) -> date:
        return date(y, m, min(day, monthrange(y, m)[1]))
    d = clamp(today.year, today.month)
    if d < today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        d = clamp(y, m)
    return d
