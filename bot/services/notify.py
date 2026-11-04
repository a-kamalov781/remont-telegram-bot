"""Уведомления: мастеру о новой заявке, клиенту о смене статуса и напоминание."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Order
from bot.services.sheets import SheetsExporter

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, bot: Bot, settings: Settings, sheets: SheetsExporter):
        self.bot = bot
        self.settings = settings
        self.sheets = sheets

    async def _send(self, chat_id: int, text: str, **kwargs) -> bool:
        try:
            await self.bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramAPIError as e:
            log.warning("send to %s failed: %s", chat_id, e)
            return False

    async def new_order(self, o: Order) -> None:
        for admin in self.settings.admin_ids:
            await self._send(admin, texts.admin_new_order(o), reply_markup=kb.admin_new_order_kb(o.id))
        await self.sheets.upsert(o)

    async def status_changed(self, o: Order) -> None:
        await self._send(o.user_id, texts.status_changed(o))
        await self.sheets.upsert(o)

    async def slot_moved(self, o: Order) -> None:
        await self._send(o.user_id, f"🔔 Заявка №{o.id}: визит перенесён на <b>{texts.fmt_dt(o.slot)}</b>.")
        await self.sheets.upsert(o)

    async def reminder(self, o: Order) -> None:
        await self._send(o.user_id, texts.reminder(o, self.settings))
