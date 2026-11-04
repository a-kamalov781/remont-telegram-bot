"""Ввод стоимости: сотрудник нажимает «Согласование стоимости», следующим сообщением пишет сумму и что делаем.

Статус меняется и клиент получает сообщение только после ввода суммы, поэтому отмена ничего не откатывает.
Пока ждём сумму, кнопки статусов не работают. Обработчики подключены в роутерах admin и demo.
Состояние своё у каждого пользователя, поэтому ввести сумму можно только для заявки,
у которой он сам нажал кнопку.
"""
from __future__ import annotations

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from bot.db import Database, Order
from bot.niches import BOOK_BUTTONS, STATUS_BUTTONS
from bot.services.notify import Notifier
from bot.services.price import parse_quote

# Кнопки меню работают как обычно и суммой не считаются
MENU_TEXTS = frozenset(BOOK_BUTTONS | STATUS_BUTTONS | {"💰 Цены", "📍 Адрес и контакты", "❌ Отмена"})

# Что считать вводом суммы: всё, кроме команд и кнопок меню
AMOUNT_INPUT = F.func(lambda m: not (m.text or "").startswith("/") and m.text not in MENU_TEXTS)


class QuoteInput(StatesGroup):
    amount = State()


def approval_code(o: Order) -> str:
    return next(s.code for s in o.preset.statuses if s.approval)


async def ask_amount(c: CallbackQuery, state: FSMContext, o: Order) -> None:
    await c.answer()
    await state.set_state(QuoteInput.amount)
    sent = await c.message.answer(texts.quote_prompt(o), reply_markup=kb.quote_cancel_kb(o.id))
    await state.update_data(quote_order=o.id, quote_prompt=sent.message_id)


async def pending_order(state: FSMContext) -> int | None:
    """Заявка, для которой сейчас ждём сумму."""
    if await state.get_state() != QuoteInput.amount.state:
        return None
    return (await state.get_data()).get("quote_order")


async def close_input(state: FSMContext, notifier: Notifier, chat_id: int) -> None:
    """Ввод закрыт: у вопроса больше нет кнопки «Отмена», кнопки статусов снова работают."""
    if await state.get_state() != QuoteInput.amount.state:
        return
    prompt = (await state.get_data()).get("quote_prompt")
    await state.clear()
    if prompt:
        await notifier.clear_markup(chat_id, prompt)


async def amount_entered(m: Message, state: FSMContext, db: Database, notifier: Notifier) -> None:
    oid = await pending_order(state)
    o = await db.order(oid) if oid else None
    if not o:
        await close_input(state, notifier, m.chat.id)
        await m.answer("Заявка не найдена.")
        return
    amount, comment = parse_quote(m.text or "")
    if not amount:
        # Кнопка «Отмена» переезжает вниз, к новому вопросу
        prompt = (await state.get_data()).get("quote_prompt")
        sent = await m.answer(texts.quote_retry(), reply_markup=kb.quote_cancel_kb(oid))
        await state.update_data(quote_prompt=sent.message_id)
        if prompt:
            await notifier.clear_markup(m.chat.id, prompt)
        return
    await db.set_quote(oid, approval_code(o), amount, comment)
    await close_input(state, notifier, m.chat.id)
    o = await db.order(oid)
    await notifier.status_changed(o)
    if not o.demo:
        await m.answer(texts.quote_sent(o))


async def cancel_input(c: CallbackQuery, state: FSMContext) -> None:
    oid = int(c.data.split(":")[1])
    if await pending_order(state) != oid:
        await c.answer("Этот ввод уже закрыт")
        await c.message.edit_reply_markup(reply_markup=None)
        return
    await c.answer()
    await state.clear()
    await c.message.edit_text(texts.quote_cancelled(), reply_markup=None)
