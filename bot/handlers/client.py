"""Клиентский сценарий: меню, запись на ремонт, статус, цены, контакты."""
from __future__ import annotations

import re
from datetime import date, datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Database
from bot.services.notify import Notifier
from bot.services.slots import ScheduleConfig, fmt_dt, free_slots, working_dates

router = Router(name="client")

PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{9,17}$")


class Booking(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    device = State()
    problem = State()
    confirm = State()


def _cfg(s: Settings) -> ScheduleConfig:
    return ScheduleConfig(
        work_start=s.work_start, work_end=s.work_end, slot_minutes=s.slot_minutes,
        work_days=tuple(s.work_days), days_ahead=s.days_ahead,
    )


def _now(s: Settings) -> datetime:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(s.tz)).replace(tzinfo=None)


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        return None
    return f"+{digits[0]} ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:]}"


# ---------- меню ----------

@router.message(CommandStart())
@router.message(Command("menu"))
async def start(m: Message, state: FSMContext, settings: Settings):
    await state.clear()
    await m.answer(texts.welcome(settings), reply_markup=kb.main_menu())


@router.message(F.text == "📍 Адрес и контакты")
async def contacts(m: Message, settings: Settings):
    await m.answer(texts.contacts(settings))


@router.message(F.text == "💰 Цены")
async def prices(m: Message, db: Database):
    await m.answer(texts.prices(await db.services()))


@router.message(F.text == "🔎 Статус моего ремонта")
@router.message(Command("status"))
async def my_status(m: Message, db: Database):
    orders = await db.user_orders(m.from_user.id)
    if not orders:
        await m.answer("У вас пока нет заявок. Нажмите «Записаться на ремонт».")
        return
    await m.answer("\n\n".join(texts.order_status_card(o) for o in orders))


@router.message(F.text == "❌ Отмена")
@router.callback_query(F.data == "cancel")
async def cancel(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.message.edit_text("Запись отменена. Вернуться — /menu")
        await event.answer()
    else:
        await event.answer("Запись отменена.", reply_markup=kb.main_menu())


# ---------- запись: услуга → дата → слот → имя → телефон → устройство → проблема → подтверждение ----------

@router.message(F.text == "📝 Записаться на ремонт")
@router.message(Command("book"))
async def book_start(m: Message, state: FSMContext, db: Database):
    await state.clear()
    await state.set_state(Booking.service)
    await m.answer("С чем помочь?", reply_markup=kb.services_kb(await db.services()))


@router.callback_query(Booking.service, F.data.startswith("svc:"))
async def pick_service(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings):
    sid = int(c.data.split(":")[1])
    svc = await db.service(sid)
    if not svc:
        await c.answer("Услуга недоступна", show_alert=True)
        return
    await state.update_data(service_id=sid, service_name=svc["name"])
    await state.set_state(Booking.date)
    dates = working_dates(_cfg(settings), _now(settings).date())
    await c.message.edit_text(f"🔧 {svc['name']}\n\nВыберите день:", reply_markup=kb.dates_kb(dates))
    await c.answer()


@router.callback_query(F.data == "back:services")
async def back_services(c: CallbackQuery, state: FSMContext, db: Database):
    await state.set_state(Booking.service)
    await c.message.edit_text("С чем помочь?", reply_markup=kb.services_kb(await db.services()))
    await c.answer()


@router.callback_query(Booking.date, F.data.startswith("date:"))
@router.callback_query(Booking.slot, F.data.startswith("date:"))
async def pick_date(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings):
    d = date.fromisoformat(c.data.split(":")[1])
    slots = free_slots(_cfg(settings), d, await db.taken_slots(d.isoformat()),
                       await db.blocked_slots(d.isoformat()), _now(settings))
    if not slots:
        await c.answer("На этот день всё занято, выберите другой", show_alert=True)
        return
    await state.update_data(date=d.isoformat())
    await state.set_state(Booking.slot)
    await c.message.edit_text("Выберите время:", reply_markup=kb.slots_kb(slots))
    await c.answer()


@router.callback_query(F.data == "back:dates")
async def back_dates(c: CallbackQuery, state: FSMContext, settings: Settings):
    await state.set_state(Booking.date)
    dates = working_dates(_cfg(settings), _now(settings).date())
    await c.message.edit_text("Выберите день:", reply_markup=kb.dates_kb(dates))
    await c.answer()


@router.callback_query(Booking.slot, F.data.startswith("slot:"))
async def pick_slot(c: CallbackQuery, state: FSMContext, db: Database):
    slot = datetime.fromisoformat(c.data.split(":", 1)[1])
    if not await db.slot_is_free(slot):
        await c.answer("Это время только что заняли. Выберите другое.", show_alert=True)
        return
    await state.update_data(slot=slot.isoformat())
    await state.set_state(Booking.name)
    await c.message.edit_text(f"🕒 {fmt_dt(slot)}\n\nКак к вам обращаться?")
    await c.answer()


@router.message(Booking.name, F.text)
async def enter_name(m: Message, state: FSMContext):
    name = m.text.strip()
    if len(name) < 2 or len(name) > 50:
        await m.answer("Напишите имя от 2 до 50 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    await m.answer("Телефон для связи — нажмите кнопку или введите вручную:", reply_markup=kb.phone_kb())


@router.message(Booking.phone, F.contact)
async def enter_phone_contact(m: Message, state: FSMContext):
    await _accept_phone(m, state, m.contact.phone_number)


@router.message(Booking.phone, F.text)
async def enter_phone_text(m: Message, state: FSMContext):
    await _accept_phone(m, state, m.text)


async def _accept_phone(m: Message, state: FSMContext, raw: str):
    phone = normalize_phone(raw)
    if not phone:
        await m.answer("Не похоже на номер. Пример: +7 912 345-67-89", reply_markup=kb.phone_kb())
        return
    await state.update_data(phone=phone)
    await state.set_state(Booking.device)
    await m.answer("Какое устройство? (модель, например «iPhone 13» или «ноутбук Lenovo»)",
                   reply_markup=kb.skip_kb())


@router.message(Booking.device, F.text)
async def enter_device(m: Message, state: FSMContext):
    device = "" if m.text == "Пропустить" else m.text.strip()[:100]
    await state.update_data(device=device)
    await state.set_state(Booking.problem)
    await m.answer("Опишите проблему в двух словах:", reply_markup=kb.skip_kb())


@router.message(Booking.problem, F.text)
async def enter_problem(m: Message, state: FSMContext):
    problem = "" if m.text == "Пропустить" else m.text.strip()[:300]
    await state.update_data(problem=problem)
    d = await state.get_data()
    await state.set_state(Booking.confirm)
    await m.answer("Секунду…", reply_markup=ReplyKeyboardRemove())
    await m.answer(
        texts.order_summary(d["name"], d["phone"], d["service_name"], d["device"], problem,
                            datetime.fromisoformat(d["slot"])),
        reply_markup=kb.confirm_kb(),
    )


@router.callback_query(Booking.confirm, F.data == "confirm")
async def confirm(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings, notifier: Notifier):
    d = await state.get_data()
    slot = datetime.fromisoformat(d["slot"])
    if not await db.slot_is_free(slot):
        await state.set_state(Booking.date)
        await c.message.edit_text("Это время только что заняли 😔 Выберите другое:",
                                  reply_markup=kb.dates_kb(working_dates(_cfg(settings), _now(settings).date())))
        await c.answer()
        return
    if await db.has_active_order_at(d["phone"], slot):
        await c.answer("У вас уже есть запись на это время.", show_alert=True)
        return
    oid = await db.create_order(
        user_id=c.from_user.id, username=c.from_user.username, name=d["name"], phone=d["phone"],
        service_id=d["service_id"], service_name=d["service_name"], device=d["device"],
        problem=d["problem"], slot=slot, now=_now(settings),
    )
    await state.clear()
    order = await db.order(oid)
    await c.message.edit_text(texts.order_created(order, settings))
    await c.message.answer("Главное меню:", reply_markup=kb.main_menu())
    await c.answer()
    await notifier.new_order(order)


@router.message(Booking.service)
@router.message(Booking.date)
@router.message(Booking.slot)
@router.message(Booking.confirm)
async def nudge(m: Message):
    await m.answer("Нажмите кнопку выше, чтобы продолжить, или «❌ Отмена».")
