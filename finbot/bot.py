"""Telegram-обёртка: команды, свободный текст, напоминания о подписках."""
from __future__ import annotations

import asyncio
import html
import io
import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from . import parsing, render, storage
from .parsing import UserError
from .rates import Rates

log = logging.getLogger("finbot")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Warsaw"))
BASE = os.getenv("BASE_CURRENCY", "PLN").upper()
REMIND_DAYS = int(os.getenv("REMIND_DAYS_BEFORE", "1"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
rates = Rates()
HTML = ParseMode.HTML

HELP = """👋 Я превращаю мелкий шрифт в понятные цифры.

<b>📱 Калькулятор с ползунками</b>: /app

<b>💰 Вклады</b>
<code>/deposit 500к 10% на год, капитализация каждый месяц</code>
Покажу итог, эффективную ставку и график. Добавьте <i>«снять через 3 мес»</i> — покажу цену досрочного снятия.
<code>/compare 500к на год: 10% ежемесячно; 10.3% в конце срока</code>

<b>🏦 Кредиты</b>
<code>/loan 500000 на 3 года под 14%</code>
Переплата, график платежей и сколько уходит на проценты в первые 3 месяца. Слово «дифф» — дифференцированные платежи.

<b>💱 Валюты</b>
<code>/convert 100 USD EUR</code> или просто напишите «100 usd в pln»

<b>🔔 Подписки</b>
<code>/sub_add Netflix 15.99 USD 25</code> — название, сумма, валюта, день списания
<code>/subs</code> — список и сколько это стоит в год
<code>/sub_del 3</code> — удалить по номеру

Можно писать и обычным текстом: «Кредит 2 млн на 5 лет под 17%»."""


def args_text(update: Update) -> str:
    parts = (update.message.text or "").split(None, 1)
    return parts[1] if len(parts) > 1 else ""


async def send(update: Update, reply: render.Reply) -> None:
    await update.message.reply_text(reply.text, parse_mode=HTML)
    if reply.photo:
        await update.message.reply_photo(io.BytesIO(reply.photo))
    if reply.document:
        name, data = reply.document
        await update.message.reply_document(io.BytesIO(data), filename=name)


async def safely(update: Update, fn, *a) -> None:
    try:
        reply = await asyncio.to_thread(fn, *a)
        await send(update, reply)
    except UserError as e:
        await update.message.reply_text(str(e), parse_mode=HTML)
    except (ValueError, OverflowError, ZeroDivisionError):
        await update.message.reply_text("Не смог посчитать — проверьте числа 🤔")


# ───────────── команды ─────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=HTML)


async def app_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not WEBAPP_URL:
        await update.message.reply_text("Мини-приложение ещё не подключено (не задан WEBAPP_URL).")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Открыть калькулятор", web_app=WebAppInfo(WEBAPP_URL))]])
    await update.message.reply_text("Вклады и кредиты в удобной форме 👇", reply_markup=kb)


async def deposit_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safely(update, lambda: render.deposit(parsing.parse(args_text(update))))


async def compare_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safely(update, lambda: render.compare(args_text(update)))


async def loan_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await safely(update, lambda: render.loan(parsing.parse(args_text(update))))


async def do_convert(update: Update, text: str):
    amount, codes = parsing.parse_convert(text)
    if amount is None:
        amount = 1.0
    if not codes:
        await update.message.reply_text("Пример: <code>/convert 100 USD EUR</code>", parse_mode=HTML)
        return
    try:
        data = await rates.get()
    except Exception:
        await update.message.reply_text("Сервис курсов сейчас недоступен, попробуйте позже.")
        return
    try:
        msg = render.convert(amount, codes, data, rates.updated)
    except UserError as e:
        msg = str(e)
    await update.message.reply_text(msg, parse_mode=HTML)


async def convert_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await do_convert(update, args_text(update))


async def free_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    low = text.lower()
    if "вклад" in low or "депозит" in low:
        await deposit_cmd(update, ctx)
    elif "кредит" in low or "ипотек" in low:
        await loan_cmd(update, ctx)
    else:
        amount, codes = parsing.parse_convert(text)
        if codes:
            await do_convert(update, text)
        else:
            await update.message.reply_text("Не понял 🙂 Список возможностей — /help")


# ───────────── подписки ─────────────

async def sub_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    a = ctx.args
    usage = "Формат: <code>/sub_add Netflix 15.99 USD 25</code> (название, сумма, валюта, день месяца)"
    if len(a) < 4:
        await update.message.reply_text(usage, parse_mode=HTML)
        return
    try:
        day = int(a[-1])
        code = parsing.to_code(a[-2])
        amount = float(a[-3].replace(",", "."))
        name = " ".join(a[:-3])[:60]
        if not (1 <= day <= 31 and code and amount > 0 and name):
            raise ValueError
    except ValueError:
        await update.message.reply_text(usage, parse_mode=HTML)
        return
    sub_id = storage.add_sub(update.effective_chat.id, name, amount, code, day)
    nxt = storage.next_charge(day, datetime.now(TZ).date())
    await update.message.reply_text(
        f"✅ #{sub_id} <b>{html.escape(name)}</b> — {render.money(amount, 2)} {code}, "
        f"следующее списание {nxt:%d.%m.%Y}. Напомню за {REMIND_DAYS} дн.", parse_mode=HTML)


async def subs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    subs = storage.list_subs(update.effective_chat.id)
    if not subs:
        await update.message.reply_text("Подписок пока нет. Добавьте: /sub_add Netflix 15.99 USD 25")
        return
    today = datetime.now(TZ).date()
    lines, total, ok = ["🔔 <b>Ваши подписки</b>", ""], 0.0, True
    try:
        data = await rates.get()
    except Exception:
        data, ok = {}, False
    for s in subs:
        nxt = storage.next_charge(s.day, today)
        lines.append(f"#{s.id} <b>{html.escape(s.name)}</b> — {render.money(s.amount, 2)} {s.currency}, "
                     f"след. {nxt:%d.%m} (через {(nxt - today).days} дн.)")
        if ok and s.currency in data and BASE in data:
            total += s.amount / data[s.currency] * data[BASE]
        else:
            ok = False
    if ok:
        lines += ["", f"В месяц: <b>{render.money(total, 2)} {BASE}</b>",
                  f"В год: <b>{render.money(total * 12, 2)} {BASE}</b> 😬"]
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


async def sub_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        sub_id = int(ctx.args[0].lstrip("#"))
    except (IndexError, ValueError):
        await update.message.reply_text("Формат: /sub_del 3 (номер из /subs)")
        return
    done = storage.delete_sub(update.effective_chat.id, sub_id)
    await update.message.reply_text("🗑 Удалено." if done else "Такой подписки нет.")


async def remind_job(ctx: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(TZ).date()
    for s in storage.all_subs():
        nxt = storage.next_charge(s.day, today)
        if (nxt - today).days == REMIND_DAYS:
            try:
                when = "завтра" if REMIND_DAYS == 1 else f"через {REMIND_DAYS} дн."
                await ctx.bot.send_message(
                    s.chat_id,
                    f"🔔 {when.capitalize()} списание: <b>{html.escape(s.name)}</b> — "
                    f"{render.money(s.amount, 2)} {s.currency}.\nНе нужна подписка? Отключить: /sub_del {s.id}",
                    parse_mode=HTML)
            except Exception:
                log.exception("reminder failed for chat %s", s.chat_id)


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=ctx.error)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()
    for name, fn in [("start", start), ("help", start), ("app", app_cmd), ("deposit", deposit_cmd), ("compare", compare_cmd),
                     ("loan", loan_cmd), ("convert", convert_cmd), ("sub_add", sub_add),
                     ("subs", subs_cmd), ("sub_del", sub_del)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    app.add_error_handler(on_error)
    app.job_queue.run_daily(remind_job, time=time(9, 0, tzinfo=TZ))
    log.info("Bot started")
    app.run_polling()
