from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.niches import CANCELLED, NICHES, Niche
from bot.services.slots import fmt_date
from bot.texts import QUOTE_CALL, QUOTE_YES


def main_menu(niche: Niche) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=niche.menu_book)],
            [KeyboardButton(text=niche.menu_status), KeyboardButton(text="💰 Цены")],
            [KeyboardButton(text="📍 Адрес и контакты")],
        ],
        resize_keyboard=True,
    )


def services_kb(services) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in services:
        price = f" — от {s['price_from']} ₽" if s["price_from"] else ""
        b.button(text=f"{s['name']}{price}", callback_data=f"svc:{s['id']}")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(1)
    return b.as_markup()


def dates_kb(dates: list[date]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for d in dates:
        b.button(text=fmt_date(d), callback_data=f"date:{d.isoformat()}")
    b.button(text="⬅️ Назад", callback_data="back:services")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(3)
    return b.as_markup()


def slots_kb(slots: list[datetime]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for s in slots:
        b.button(text=s.strftime("%H:%M"), callback_data=f"slot:{s.isoformat()}")
    b.button(text="⬅️ Другая дата", callback_data="back:dates")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(4)
    return b.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить запись", callback_data="confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
                  [KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")], [KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def cancel_only_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def quote_kb(oid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Согласен", callback_data=f"quote:{QUOTE_YES}:{oid}"),
         InlineKeyboardButton(text="📞 Перезвоните мне", callback_data=f"quote:{QUOTE_CALL}:{oid}")],
    ])


# ---------- админ ----------

def admin_new_order_kb(niche: Niche, oid: int) -> InlineKeyboardMarkup:
    step = niche.next_after_new
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=step.button or step.text, callback_data=f"adm:{step.code}:{oid}"),
         InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:{CANCELLED.code}:{oid}")],
        [InlineKeyboardButton(text="🔧 Все статусы", callback_data=f"adm:menu:{oid}")],
    ])


def admin_status_kb(niche: Niche, oid: int, current: str | None = None) -> InlineKeyboardMarkup:
    """Все статусы ниши. Если передан current, текущий статус отмечен стрелкой."""
    b = InlineKeyboardBuilder()
    for status in niche.all_statuses:
        mark = "▶️ " if status.code == current else ""
        b.button(text=f"{mark}{status.text}", callback_data=f"adm:{status.code}:{oid}")
    b.adjust(1)
    return b.as_markup()


# ---------- демо ----------

def niche_picker_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for niche in NICHES.values():
        b.button(text=f"{niche.emoji} {niche.name}", callback_data=f"niche:{niche.key}")
    b.adjust(1)
    return b.as_markup()
