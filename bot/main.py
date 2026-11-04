from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import get_settings
from bot.db import Database
from bot.handlers import admin, client
from bot.services.notify import Notifier
from bot.services.sheets import SheetsExporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


async def send_reminders(db: Database, notifier: Notifier, tz: str, before: int) -> None:
    now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    for o in await db.due_reminders(now, before):
        await notifier.reminder(o)
        await db.mark_reminded(o.id)
        log.info("reminder sent for order %s", o.id)


async def main() -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    await db.init()

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    sheets = SheetsExporter(settings.google_credentials_file, settings.google_sheet_id)
    notifier = Notifier(bot, settings, sheets)

    dp["settings"] = settings
    dp["db"] = db
    dp["notifier"] = notifier

    dp.include_router(admin.router)
    dp.include_router(client.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="book", description="Записаться на ремонт"),
        BotCommand(command="status", description="Статус моего ремонта"),
    ])

    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(send_reminders, "interval", minutes=5,
                      args=[db, notifier, settings.tz, settings.remind_before_minutes])
    scheduler.start()

    log.info("Bot started: %s", settings.business_name)
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
