"""Профиль бота в Telegram: название и описания. В демо нейтральные, у клиента — из его настроек."""
from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Лимиты Telegram
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 512
SHORT_DESCRIPTION_LIMIT = 120

DEMO_NAME = "Демо: бот записи и статусов для сервиса"
DEMO_DESCRIPTION = (
    "Витрина бота для сервисного бизнеса: химчистки, ателье, автосервисы, ремонт телефонов и бытовой техники.\n\n"
    "Выберите свой тип бизнеса и пройдите путь клиента и сотрудника: запись, статусы заказа, согласование цены.\n\n"
    "Названия, адреса и телефоны внутри демо вымышленные."
)
DEMO_SHORT = "Витрина для химчисток, ателье, автосервисов и ремонта: запись и статусы заказа в Telegram"


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    short_description: str


def business_profile(name: str, address: str, phone: str, start: str, end: str) -> Profile:
    plain = name.strip("«»\"' ")
    lines = [line for line in (plain, f"📍 {address}" if address else "", f"🕒 {start}–{end}",
                               f"📞 {phone}" if phone else "") if line]
    description = "\n".join(lines) + "\n\nЗапись, статус заказа и вопрос сотруднику прямо в этом чате."
    short = ", ".join(part for part in (address, f"{start}–{end}") if part)
    return Profile(plain, description, short)


def profile_for(settings) -> Profile:
    if settings.demo_mode:
        return Profile(DEMO_NAME, DEMO_DESCRIPTION, DEMO_SHORT)
    if not settings.business_name and not settings.business_address:
        return Profile("", "", "")  # настройки не заполнены: профиль не трогаем, вымышленное не подставляем
    return business_profile(settings.business_name, settings.business_address, settings.business_phone,
                            settings.work_start.strftime("%H:%M"), settings.work_end.strftime("%H:%M"))


async def sync_profile(bot, settings) -> None:
    """Обновляет только то, что изменилось: Telegram строго ограничивает частоту этих вызовов.
    Ошибка профиля не мешает боту работать."""
    from aiogram.exceptions import TelegramAPIError

    wanted = profile_for(settings)
    fields = (
        ("name", wanted.name[:NAME_LIMIT], bot.get_my_name, bot.set_my_name),
        ("description", wanted.description[:DESCRIPTION_LIMIT], bot.get_my_description, bot.set_my_description),
        ("short_description", wanted.short_description[:SHORT_DESCRIPTION_LIMIT],
         bot.get_my_short_description, bot.set_my_short_description),
    )
    for field, value, getter, setter in fields:
        if not value:  # пустая настройка не стирает то, что уже заполнено
            continue
        try:
            if getattr(await getter(), field) != value:
                await setter(**{field: value})
                log.info("bot profile updated: %s", field)
        except TelegramAPIError as e:
            log.warning("bot profile %s not updated: %s", field, e)
