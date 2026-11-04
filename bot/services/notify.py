"""Уведомления: мастеру о новой заявке, клиенту о смене статуса и напоминание.

В демо посетитель и клиент, и мастер своей заявки, поэтому оба потока сообщений уходят ему.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Order
from bot.niches import CANCELLED
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
        if o.demo:
            await self._send(o.user_id, texts.demo_new_card(o),
                             reply_markup=kb.admin_status_kb(o.preset, o.id, current=o.status))
            return
        for admin in self.settings.admin_ids:
            await self._send(admin, texts.admin_order(o), reply_markup=kb.admin_new_order_kb(o.preset, o.id))
        await self.sheets.upsert(o)

    async def status_changed(self, o: Order) -> None:
        markup = kb.quote_kb(o.id) if o.awaits_quote_answer else None
        if o.demo:
            await self._send(o.user_id, texts.demo_client_view(o), reply_markup=markup)
            await self._demo_next_step(o)
            return
        await self._send(o.user_id, texts.status_changed(o), reply_markup=markup)
        await self.sheets.upsert(o)

    async def _demo_next_step(self, o: Order) -> None:
        """Держим следующий шаг внизу чата, чтобы не листать вверх к старой карточке."""
        if o.status == o.preset.final.code:
            await self._send(o.user_id, texts.demo_finish(self.settings))
        elif o.status == CANCELLED.code:
            await self._send(o.user_id, texts.demo_cancelled())
        elif o.awaits_quote_answer:
            await self._send(o.user_id, texts.demo_quote_hint())
        else:
            await self._send(o.user_id, texts.demo_master_card(o),
                             reply_markup=kb.admin_status_kb(o.preset, o.id, current=o.status))

    async def quote_answered(self, o: Order, answer: str) -> None:
        markup = kb.admin_status_kb(o.preset, o.id, current=o.status)
        if o.demo:
            await self._send(o.user_id, texts.demo_quote_card(o, answer), reply_markup=markup)
            return
        for admin in self.settings.admin_ids:
            await self._send(admin, texts.quote_master_answer(o, answer), reply_markup=markup)
        await self.sheets.upsert(o)

    async def slot_moved(self, o: Order) -> None:
        await self._send(o.user_id, f"🔔 Заявка №{o.id}: время изменилось, теперь <b>{texts.fmt_dt(o.slot)}</b>.")
        await self.sheets.upsert(o)

    async def reminder(self, o: Order) -> None:
        await self._send(o.user_id, texts.reminder(o, self.settings))
