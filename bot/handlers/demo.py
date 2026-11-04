"""Демо-режим: выбор ниши и действия мастера посетителя над своими демо-заявками.

Роутер подключён после admin и перед client. Администраторов обрабатывает admin,
сюда попадают все остальные, и им доступны только их собственные демо-заявки.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database, Order
from bot.handlers import admin, client
from bot.niches import NICHES, get_niche
from bot.services.notify import Notifier

router = Router(name="demo")


class DemoOn(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return settings.demo_mode


router.message.filter(DemoOn())
router.callback_query.filter(DemoOn())


async def _own_order(db: Database, user_id: int, oid: int) -> Order | None:
    o = await db.order(oid)
    return o if o and o.demo and o.user_id == user_id else None


# ---------- выбор ниши ----------

@router.message(CommandStart())
async def start(m: Message, state: FSMContext, db: Database, settings: Settings):
    await state.clear()
    await db.demo_touch(m.from_user.id, settings.now())
    key = await db.demo_niche(m.from_user.id)
    if key:
        await client.show_menu(m, settings, get_niche(key))
    else:
        await m.answer(texts.demo_pick(), reply_markup=kb.niche_picker_kb())


@router.message(Command("niche"))
async def change_niche(m: Message, state: FSMContext, db: Database, settings: Settings):
    await state.clear()
    await db.demo_touch(m.from_user.id, settings.now())
    await m.answer(texts.demo_pick(), reply_markup=kb.niche_picker_kb())


@router.callback_query(F.data.startswith("niche:"))
async def pick_niche(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings):
    key = c.data.split(":", 1)[1]
    if key not in NICHES:
        await c.answer("Такой ниши нет", show_alert=True)
        return
    await state.clear()
    await db.set_demo_niche(c.from_user.id, key, settings.now())
    niche = NICHES[key]
    await c.message.edit_text(texts.demo_intro(niche))
    await client.show_menu(c.message, settings, niche)
    await c.answer()


# ---------- посетитель как мастер своей заявки ----------

@router.message(Command("order"))
async def order_card(m: Message, command: CommandObject, db: Database):
    args = (command.args or "").strip()
    if not args.isdigit():
        await m.answer("Формат: /order 12")
        return
    o = await _own_order(db, m.from_user.id, int(args))
    if not o:
        await m.answer("Заявка не найдена.")
        return
    await m.answer(texts.admin_order_with_status(o), reply_markup=kb.admin_status_kb(o.preset, o.id, current=o.status))


@router.message(Command("note"))
async def note(m: Message, command: CommandObject, db: Database, notifier: Notifier):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) == 2 and parts[0].isdigit() and not await _own_order(db, m.from_user.id, int(parts[0])):
        await m.answer("Заявка не найдена.")
        return
    await admin.note(m, command, db, notifier)


@router.callback_query(F.data.startswith("adm:"))
async def status_button(c: CallbackQuery, db: Database, notifier: Notifier, settings: Settings):
    oid_s = c.data.rsplit(":", 1)[-1]
    if not oid_s.isdigit() or not await _own_order(db, c.from_user.id, int(oid_s)):
        await c.answer("Это не ваша заявка", show_alert=True)
        return
    await admin.admin_action(c, db, notifier, settings)
