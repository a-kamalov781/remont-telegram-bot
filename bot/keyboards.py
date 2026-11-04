from __future__ import annotations

from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import STATUSES
from bot.services.slots import fmt_date


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Записаться на ремонт")],
            [KeyboardButton(text="🔎 Статус моего ремонта"), KeyboardButton(text="💰 Цены")],
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


# ---------- админ ----------

def admin_new_order_kb(oid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm:confirmed:{oid}"),
         InlineKeyboardButton(text="❌ Отменить", callback_data=f"adm:cancelled:{oid}")],
        [InlineKeyboardButton(text="🔧 Все статусы", callback_data=f"adm:menu:{oid}")],
    ])


def admin_status_kb(oid: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, text in STATUSES.items():
        b.button(text=text, callback_data=f"adm:{code}:{oid}")
    b.adjust(1)
    return b.as_markup()
