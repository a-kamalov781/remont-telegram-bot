"""Клиентский сценарий: меню, запись, статус, цены, контакты. Тексты и шаги берутся из пресета ниши."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import DEMO_EVENT_BOOKED, Database
from bot.niches import BOOK_BUTTONS, CANCELLED, STATUS_BUTTONS, Niche, get_niche
from bot.services.notify import Notifier
from bot.services.slots import ScheduleConfig, fmt_dt, free_slots, working_dates

router = Router(name="client")

PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s()]{9,17}$")

# Антиспам переписки: сколько сообщений одного клиента доходит до мастера за окно времени
RELAY_LIMIT = 10
RELAY_WINDOW = timedelta(minutes=10)


class NicheMiddleware(BaseMiddleware):
    """Подставляет в обработчик пресет ниши: из настроек или, в демо, выбранный посетителем."""

    async def __call__(self, handler, event: Message | CallbackQuery, data: dict):
        settings: Settings = data["settings"]
        if not settings.demo_mode:
            data["niche"] = get_niche(settings.niche)
            return await handler(event, data)
        db: Database = data["db"]
        key = await db.demo_niche(event.from_user.id)
        if key:
            data["niche"] = get_niche(key)
            return await handler(event, data)
        await db.demo_touch(event.from_user.id, settings.now())
        if isinstance(event, CallbackQuery):
            await event.answer("Сначала выберите бизнес: /niche", show_alert=True)
        else:
            await event.answer(texts.demo_pick(), reply_markup=kb.niche_picker_kb())
        return None


router.message.outer_middleware(NicheMiddleware())
router.callback_query.outer_middleware(NicheMiddleware())


class Booking(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    device = State()
    problem = State()
    address = State()
    confirm = State()


def _cfg(s: Settings, niche: Niche) -> ScheduleConfig:
    slot_minutes = niche.slot_minutes if s.demo_mode or s.slot_minutes is None else s.slot_minutes
    return ScheduleConfig(
        work_start=s.work_start, work_end=s.work_end, slot_minutes=slot_minutes,
        work_days=tuple(s.work_days), days_ahead=s.days_ahead,
    )


def _scope(s: Settings, user_id: int) -> int | None:
    """В демо занятость времени считается отдельно для каждого посетителя."""
    return user_id if s.demo_mode else None


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

async def show_menu(m: Message, s: Settings, niche: Niche) -> None:
    await m.answer(texts.welcome(s, niche), reply_markup=kb.main_menu(niche))
    await m.answer(texts.business_card(s, niche), reply_markup=kb.book_kb(niche))


@router.message(CommandStart())
@router.message(Command("menu"))
async def start(m: Message, state: FSMContext, settings: Settings, niche: Niche):
    await state.clear()
    await show_menu(m, settings, niche)


@router.message(F.text == "📍 Адрес и контакты")
async def contacts(m: Message, settings: Settings, niche: Niche):
    await m.answer(texts.contacts(settings, niche))


@router.message(F.text == "💰 Цены")
async def prices(m: Message, db: Database, niche: Niche):
    await m.answer(texts.prices(await db.services(niche.key), niche))


@router.message(F.text.in_(STATUS_BUTTONS))
@router.message(Command("status"))
async def my_status(m: Message, db: Database, settings: Settings, niche: Niche):
    orders = await db.user_orders(m.from_user.id, niche=niche.key if settings.demo_mode else None)
    if not orders:
        await m.answer(texts.no_orders(niche))
        return
    await m.answer("\n\n".join(texts.order_status_card(o) for o in orders))


@router.message(F.text == "❌ Отмена")
@router.callback_query(F.data == "cancel")
async def cancel(event: Message | CallbackQuery, state: FSMContext, niche: Niche):
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.message.edit_text("Запись отменена. Вернуться — /menu")
        await event.answer()
    else:
        await event.answer("Запись отменена.", reply_markup=kb.main_menu(niche))


# ---------- запись: услуга → дата → слот → имя → телефон → объект → проблема → (адрес) → подтверждение ----------

@router.message(F.text.in_(BOOK_BUTTONS))
@router.message(Command("book"))
async def book_start(m: Message, state: FSMContext, db: Database, niche: Niche):
    await state.clear()
    await state.set_state(Booking.service)
    await m.answer(niche.book_prompt, reply_markup=kb.services_kb(await db.services(niche.key)))


@router.callback_query(F.data == "book")
async def book_from_card(c: CallbackQuery, state: FSMContext, db: Database, niche: Niche):
    await state.clear()
    await state.set_state(Booking.service)
    await c.message.answer(niche.book_prompt, reply_markup=kb.services_kb(await db.services(niche.key)))
    await c.answer()


@router.callback_query(Booking.service, F.data.startswith("svc:"))
async def pick_service(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings, niche: Niche):
    sid = int(c.data.split(":")[1])
    svc = await db.service(sid)
    if not svc or svc["niche"] != niche.key:
        await c.answer("Услуга недоступна", show_alert=True)
        return
    await state.update_data(service_id=sid, service_name=svc["name"])
    await state.set_state(Booking.date)
    dates = working_dates(_cfg(settings, niche), settings.now().date())
    header = texts.booking_header(settings, niche, svc["name"])
    await c.message.edit_text(f"{header}\n\nВыберите день:", reply_markup=kb.dates_kb(dates))
    await c.answer()


@router.callback_query(F.data == "back:services")
async def back_services(c: CallbackQuery, state: FSMContext, db: Database, niche: Niche):
    await state.set_state(Booking.service)
    await c.message.edit_text(niche.book_prompt, reply_markup=kb.services_kb(await db.services(niche.key)))
    await c.answer()


@router.callback_query(Booking.date, F.data.startswith("date:"))
@router.callback_query(Booking.slot, F.data.startswith("date:"))
async def pick_date(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings, niche: Niche):
    d = date.fromisoformat(c.data.split(":")[1])
    taken = await db.taken_slots(d.isoformat(), _scope(settings, c.from_user.id))
    slots = free_slots(_cfg(settings, niche), d, taken, await db.blocked_slots(d.isoformat()), settings.now())
    if not slots:
        await c.answer("На этот день всё занято, выберите другой", show_alert=True)
        return
    await state.update_data(date=d.isoformat())
    await state.set_state(Booking.slot)
    service = (await state.get_data()).get("service_name", "")
    header = texts.booking_header(settings, niche, service, d)
    await c.message.edit_text(f"{header}\n\nВыберите время:", reply_markup=kb.slots_kb(slots))
    await c.answer()


@router.callback_query(F.data == "back:dates")
async def back_dates(c: CallbackQuery, state: FSMContext, settings: Settings, niche: Niche):
    await state.set_state(Booking.date)
    dates = working_dates(_cfg(settings, niche), settings.now().date())
    service = (await state.get_data()).get("service_name", "")
    header = texts.booking_header(settings, niche, service)
    await c.message.edit_text(f"{header}\n\nВыберите день:", reply_markup=kb.dates_kb(dates))
    await c.answer()


@router.callback_query(Booking.slot, F.data.startswith("slot:"))
async def pick_slot(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings, niche: Niche):
    slot = datetime.fromisoformat(c.data.split(":", 1)[1])
    if not await db.slot_is_free(slot, _scope(settings, c.from_user.id)):
        await c.answer("Это время только что заняли. Выберите другое.", show_alert=True)
        return
    await state.update_data(slot=slot.isoformat())
    await state.set_state(Booking.name)
    await c.message.edit_text(f"🕒 {fmt_dt(slot)}\n\nКак к вам обращаться?")
    await c.answer()


@router.message(Booking.name, F.text)
async def enter_name(m: Message, state: FSMContext, settings: Settings):
    name = m.text.strip()
    if len(name) < 2 or len(name) > 50:
        await m.answer("Напишите имя от 2 до 50 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(Booking.phone)
    note = texts.demo_phone_note() if settings.demo_mode else ""
    await m.answer(f"Телефон для связи — нажмите кнопку или введите вручную:{note}", reply_markup=kb.phone_kb())


@router.message(Booking.phone, F.contact)
async def enter_phone_contact(m: Message, state: FSMContext, niche: Niche):
    await _accept_phone(m, state, m.contact.phone_number, niche)


@router.message(Booking.phone, F.text)
async def enter_phone_text(m: Message, state: FSMContext, niche: Niche):
    await _accept_phone(m, state, m.text, niche)


async def _accept_phone(m: Message, state: FSMContext, raw: str, niche: Niche):
    phone = normalize_phone(raw)
    if not phone:
        await m.answer("Не похоже на номер. Пример: +7 912 345-67-89", reply_markup=kb.phone_kb())
        return
    await state.update_data(phone=phone)
    await state.set_state(Booking.device)
    await m.answer(niche.object_prompt, reply_markup=kb.skip_kb())


@router.message(Booking.device, F.text)
async def enter_device(m: Message, state: FSMContext, niche: Niche):
    device = "" if m.text == "Пропустить" else m.text.strip()[:100]
    await state.update_data(device=device)
    await state.set_state(Booking.problem)
    await m.answer(niche.problem_prompt, reply_markup=kb.skip_kb())


@router.message(Booking.problem, F.text)
async def enter_problem(m: Message, state: FSMContext, niche: Niche):
    problem = "" if m.text == "Пропустить" else m.text.strip()[:300]
    await state.update_data(problem=problem, address="")
    if niche.ask_address:
        await state.set_state(Booking.address)
        await m.answer(niche.address_prompt, reply_markup=kb.cancel_only_kb())
        return
    await _show_summary(m, state, niche)


@router.message(Booking.address, F.text)
async def enter_address(m: Message, state: FSMContext, niche: Niche):
    address = m.text.strip()
    if len(address) < 5 or len(address) > 200:
        await m.answer("Напишите адрес от 5 до 200 символов: улица, дом, квартира.")
        return
    await state.update_data(address=address)
    await _show_summary(m, state, niche)


async def _show_summary(m: Message, state: FSMContext, niche: Niche):
    d = await state.get_data()
    await state.set_state(Booking.confirm)
    await m.answer("Секунду…", reply_markup=ReplyKeyboardRemove())
    await m.answer(
        texts.order_summary(niche, d["name"], d["phone"], d["service_name"], d["device"], d["problem"],
                            datetime.fromisoformat(d["slot"]), d["address"]),
        reply_markup=kb.confirm_kb(),
    )


@router.callback_query(Booking.confirm, F.data == "confirm")
async def confirm(c: CallbackQuery, state: FSMContext, db: Database, settings: Settings, notifier: Notifier,
                  niche: Niche):
    d = await state.get_data()
    slot = datetime.fromisoformat(d["slot"])
    scope = _scope(settings, c.from_user.id)
    if not await db.slot_is_free(slot, scope):
        await state.set_state(Booking.date)
        await c.message.edit_text(
            "Это время только что заняли 😔 Выберите другое:",
            reply_markup=kb.dates_kb(working_dates(_cfg(settings, niche), settings.now().date())),
        )
        await c.answer()
        return
    if await db.has_active_order_at(d["phone"], slot, scope):
        await c.answer("У вас уже есть запись на это время.", show_alert=True)
        return
    now = settings.now()
    oid = await db.create_order(
        user_id=c.from_user.id, username=c.from_user.username, name=d["name"], phone=d["phone"],
        service_id=d["service_id"], service_name=d["service_name"], device=d["device"],
        problem=d["problem"], slot=slot, now=now, niche=niche.key, demo=settings.demo_mode, address=d["address"],
    )
    await state.clear()
    order = await db.order(oid)
    await c.message.edit_text(texts.order_created(order, settings))
    await c.message.answer("Главное меню:", reply_markup=kb.main_menu(niche))
    await c.answer()
    if order.demo:
        await db.demo_event(c.from_user.id, niche.key, DEMO_EVENT_BOOKED, now)
    await notifier.new_order(order)


@router.message(Booking.service)
@router.message(Booking.date)
@router.message(Booking.slot)
@router.message(Booking.confirm)
async def nudge(m: Message):
    await m.answer("Нажмите кнопку выше, чтобы продолжить, или «❌ Отмена».")


# ---------- ответ клиента на сумму от мастера ----------

@router.callback_query(F.data.startswith("quote:"))
async def quote_answer(c: CallbackQuery, db: Database, notifier: Notifier):
    _, answer, oid_s = c.data.split(":")
    o = await db.order(int(oid_s))
    if not o or o.user_id != c.from_user.id or answer not in texts.QUOTE_ANSWERS:
        await c.answer("Заявка не найдена", show_alert=True)
        return
    if not o.awaits_quote_answer:
        await c.message.edit_reply_markup(reply_markup=None)
        await c.answer("Этот вопрос уже закрыт")
        return
    await db.set_quote_answer(o.id, answer)
    o = await db.order(o.id)
    await c.message.edit_reply_markup(reply_markup=None)
    await c.message.answer(texts.quote_client_ack(answer))
    await c.answer()
    await notifier.quote_answered(o, answer)


# ---------- свободное сообщение мастеру. Обработчик последний: всё остальное уже разобрано выше ----------

def _is_free_message(m: Message) -> bool:
    """Неизвестные команды и кнопка «Пропустить» из старой клавиатуры — не сообщение мастеру."""
    text = m.text or ""
    return not text.startswith("/") and text != "Пропустить"


@router.message(StateFilter(None), F.func(_is_free_message))
async def message_to_master(m: Message, db: Database, settings: Settings, notifier: Notifier, niche: Niche):
    if not settings.demo_mode and m.from_user.id in settings.admin_ids:
        await m.answer(texts.admin_relay_hint())
        return
    if not await db.relay_allow(m.from_user.id, settings.now(), RELAY_LIMIT, RELAY_WINDOW):
        await m.answer(texts.relay_too_many())
        return
    orders = await db.user_orders(m.from_user.id, niche=niche.key if settings.demo_mode else None)
    closed = {niche.final.code, CANCELLED.code}
    order = next((o for o in orders if o.status not in closed), orders[0] if orders else None)
    await m.answer(texts.relay_ack())
    sent = await notifier.client_message(m, order, settings.demo_mode)
    if not sent:
        await m.answer(texts.relay_failed())
        return
    await db.save_relay(sent, m.from_user.id, settings.demo_mode, settings.now())
