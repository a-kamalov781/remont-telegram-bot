"""Уведомления: сотруднику о новой заявке, клиенту о смене статуса и напоминание.

В демо посетитель и клиент, и сотрудник своей заявки, поэтому оба потока сообщений уходят ему.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import Order
from bot.niches import CANCELLED, Niche
from bot.services.sheets import SheetsExporter

log = logging.getLogger(__name__)

# Лимит Telegram — 4096 символов. Текст длиннее не помещается рядом с подписью и идёт копией
RELAY_INLINE_LIMIT = 3500


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

    async def _send_get_id(self, chat_id: int, text: str) -> int | None:
        try:
            return (await self.bot.send_message(chat_id, text)).message_id
        except TelegramAPIError as e:
            log.warning("send to %s failed: %s", chat_id, e)
            return None

    async def _copy_get_id(self, chat_id: int, m: Message) -> int | None:
        try:
            return (await self.bot.copy_message(chat_id, m.chat.id, m.message_id)).message_id
        except TelegramAPIError as e:
            log.warning("copy to %s failed: %s", chat_id, e)
            return None

    async def client_message(self, m: Message, o: Order | None, demo: bool, niche: Niche) -> list[tuple[int, int]]:
        """Передаёт сообщение клиента сотруднику. Возвращает (чат, сообщение) всего, на что можно ответить."""
        targets = [m.chat.id] if demo else self.settings.admin_ids
        inline = m.text if m.text and len(m.text) <= RELAY_INLINE_LIMIT else None
        header = texts.relay_to_master(m.from_user, o, inline, demo, niche)
        sent: list[tuple[int, int]] = []
        for chat_id in targets:
            ids = [await self._send_get_id(chat_id, header)]
            if inline is None:
                ids.append(await self._copy_get_id(chat_id, m))
            sent += [(chat_id, message_id) for message_id in ids if message_id]
        return sent

    async def master_reply(self, m: Message, client_id: int, demo: bool, niche: Niche) -> bool:
        """Передаёт клиенту ответ сотрудника: текст с подписью, остальное (фото, файл, длинный текст) копией."""
        if m.text and len(m.text) <= RELAY_INLINE_LIMIT:
            return await self._send(client_id, texts.master_answer(m.text, demo, niche))
        return await self._copy_get_id(client_id, m) is not None

    async def new_order(self, o: Order) -> None:
        if o.demo:
            # Настоящее напоминание в демо не приходит, поэтому показываем его сразу. Карточка остаётся внизу чата
            await self._send(o.user_id, texts.demo_reminder_preview(o, self.settings))
            await self._send(o.user_id, texts.demo_new_card(o), reply_markup=kb.admin_card_kb(o))
            return
        for admin in self.settings.admin_ids:
            await self._send(admin, texts.admin_order(o), reply_markup=kb.admin_card_kb(o))
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
            await self._send(o.user_id, texts.demo_quote_hint(o))
        else:
            await self._send(o.user_id, texts.demo_master_card(o), reply_markup=kb.admin_card_kb(o))

    async def quote_answered(self, o: Order, answer: str) -> None:
        markup = kb.admin_card_kb(o)
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
