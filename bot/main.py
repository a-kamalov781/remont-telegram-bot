from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot import texts
from bot.config import Settings, get_settings
from bot.db import Database
from bot.handlers import admin, client, demo
from bot.middlewares import install as install_middlewares
from bot.niches import get_niche
from bot.services.notify import Notifier
from bot.services.profile import sync_profile
from bot.services.retry import RetryRequests
from bot.services.sheets import SheetsExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

DEMO_RETENTION_DAYS = 7


async def send_reminders(db: Database, notifier: Notifier, tz: str, before: int) -> None:
    now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    for o in await db.due_reminders(now, before):
        await notifier.reminder(o)
        await db.mark_reminded(o.id)
        log.info("reminder sent for order %s", o.id)


async def purge_demo(db: Database, settings: Settings) -> None:
    removed = await db.purge_demo_orders(settings.now() - timedelta(days=DEMO_RETENTION_DAYS))
    if removed:
        log.info("demo orders removed: %s", removed)


def bot_defaults() -> DefaultBotProperties:
    # Без превью: ссылка на карту не должна разворачиваться в большую картинку под каждым сообщением
    return DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)


def bot_commands(settings: Settings) -> list[BotCommand]:
    if settings.demo_mode:
        return [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="niche", description="Сменить бизнес"),
            BotCommand(command="book", description="Записаться"),
            BotCommand(command="status", description="Статус заявки"),
        ]
    niche = get_niche(settings.niche)
    return [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="book", description=niche.menu_book.split(" ", 1)[1]),
        BotCommand(command="status", description=niche.menu_status.split(" ", 1)[1]),
    ]


async def main() -> None:
    settings = get_settings()
    niche = get_niche(settings.niche)
    db = Database(settings.db_path, settings.niche, seed_all=settings.demo_mode)
    await db.init()

    bot = Bot(settings.bot_token, default=bot_defaults())
    bot.session.middleware(RetryRequests())
    dp = Dispatcher(storage=MemoryStorage())
    sheets = SheetsExporter(settings.google_credentials_file, settings.google_sheet_id, niche)
    notifier = Notifier(bot, settings, sheets)

    dp["settings"] = settings
    dp["db"] = db
    dp["notifier"] = notifier

    install_middlewares(dp)
    dp.include_router(admin.router)
    dp.include_router(demo.router)
    dp.include_router(client.router)

    await bot.set_my_commands(bot_commands(settings))
    await sync_profile(bot, settings)

    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(send_reminders, "interval", minutes=5,
                      args=[db, notifier, settings.tz, settings.remind_before_minutes])
    if settings.demo_mode:
        await purge_demo(db, settings)
        scheduler.add_job(purge_demo, "interval", hours=6, args=[db, settings])
    scheduler.start()

    log.info("Bot started: niche=%s demo=%s name=%s", niche.key, settings.demo_mode, texts.biz_name(settings, niche))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
