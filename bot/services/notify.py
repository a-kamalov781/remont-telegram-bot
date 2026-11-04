"""Уведомления: сотруднику о новой заявке, клиенту о смене статуса и напоминание.

В демо посетитель и клиент, и сотрудник своей заявки, поэтому оба потока сообщений уходят ему.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
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

# Демо: карточка ушла выше стольких сообщений — присылаем её заново внизу чата
CARD_MAX_AGE = 4


@dataclass
class _Card:
    message_id: int
    born: int  # значение счётчика сообщений в чате, когда карточка появилась


class Notifier:
    def __init__(self, bot: Bot, settings: Settings, sheets: SheetsExporter):
        self.bot = bot
        self.settings = settings
        self.sheets = sheets
        # Демо: карточка каждой заявки и счётчик сообщений в чате. В памяти: после перезапуска
        # карточка снова станет известна при первом нажатии на неё
        self._cards: dict[tuple[int, int], _Card] = {}
        self._activity: dict[int, int] = {}

    def note_activity(self, chat_id: int, count: int = 1) -> None:
        self._activity[chat_id] = self._activity.get(chat_id, 0) + count

    async def clear_markup(self, chat_id: int, message_id: int) -> None:
        try:
            await self.bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramAPIError as e:
            log.warning("buttons of %s in %s not removed: %s", message_id, chat_id, e)

    async def _retire(self, chat_id: int, card: _Card) -> None:
        """Убирает прежнюю карточку. Слишком старую Telegram удалить не даст, тогда снимаем с неё кнопки."""
        try:
            await self.bot.delete_message(chat_id, card.message_id)
        except TelegramAPIError:
            await self.clear_markup(chat_id, card.message_id)

    async def adopt_card(self, o: Order, message_id: int) -> None:
        """Считает карточкой заявки сообщение, на кнопку которого нажали."""
        key = (o.user_id, o.id)
        card = self._cards.get(key)
        if card and card.message_id == message_id:
            return
        if card:
            await self._retire(o.user_id, card)
        self._cards[key] = _Card(message_id, self._activity.get(o.user_id, 0))

    async def _edit_card(self, chat_id: int, card: _Card, text: str, markup) -> bool:
        try:
            await self.bot.edit_message_text(text=text, chat_id=chat_id, message_id=card.message_id,
                                             reply_markup=markup)
            return True
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                return True
            log.warning("card %s in %s not edited: %s", card.message_id, chat_id, e)
        except TelegramAPIError as e:
            log.warning("card %s in %s not edited: %s", card.message_id, chat_id, e)
        return False

    async def show_card(self, o: Order, text: str, markup, force_new: bool = False) -> None:
        """Карточка меняется на месте. Новая внизу — только если старая ушла выше CARD_MAX_AGE сообщений."""
        chat_id, key = o.user_id, (o.user_id, o.id)
        card = self._cards.get(key)
        if card and not force_new and self._activity.get(chat_id, 0) - card.born <= CARD_MAX_AGE:
            if await self._edit_card(chat_id, card, text, markup):
                return
        message_id = await self._send_get_id(chat_id, text, reply_markup=markup)
        if message_id is None:
            return  # старая карточка остаётся рабочей
        if card:
            await self._retire(chat_id, card)
        self._cards[key] = _Card(message_id, self._activity.get(chat_id, 0))

    async def close_card(self, o: Order, text: str) -> None:
        """Заявка закрыта: карточка остаётся на месте со своим статусом и без кнопок."""
        card = self._cards.pop((o.user_id, o.id), None)
        if not card or not await self._edit_card(o.user_id, card, text, None):
            await self._send(o.user_id, text)

    async def _send(self, chat_id: int, text: str, **kwargs) -> bool:
        try:
            await self.bot.send_message(chat_id, text, **kwargs)
            self.note_activity(chat_id)
            return True
        except TelegramAPIError as e:
            log.warning("send to %s failed: %s", chat_id, e)
            return False

    async def _send_get_id(self, chat_id: int, text: str, **kwargs) -> int | None:
        try:
            message_id = (await self.bot.send_message(chat_id, text, **kwargs)).message_id
            self.note_activity(chat_id)
            return message_id
        except TelegramAPIError as e:
            log.warning("send to %s failed: %s", chat_id, e)
            return None

    async def _copy_get_id(self, chat_id: int, m: Message) -> int | None:
        try:
            self.note_activity(chat_id)
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
            await self.show_card(o, texts.demo_new_card(o), kb.admin_card_kb(o))
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
        """Карточка заявки одна и меняется на месте, сообщение клиента всегда отдельное."""
        if o.status == o.preset.final.code:
            await self.close_card(o, texts.admin_order(o))
            await self._send(o.user_id, texts.demo_finish(self.settings))
        elif o.status == CANCELLED.code:
            await self.close_card(o, texts.admin_order(o))
            await self._send(o.user_id, texts.demo_cancelled())
        else:
            await self.show_card(o, texts.demo_master_card(o), kb.admin_card_kb(o))
            if o.awaits_quote_answer:
                await self._send(o.user_id, texts.demo_quote_hint(o))

    async def quote_answered(self, o: Order, answer: str) -> None:
        markup = kb.admin_card_kb(o)
        if o.demo:
            await self._send(o.user_id, texts.demo_quote_answer(o, answer))
            await self.show_card(o, texts.demo_master_card(o), markup)
            return
        for admin in self.settings.admin_ids:
            await self._send(admin, texts.quote_master_answer(o, answer), reply_markup=markup)
        await self.sheets.upsert(o)

    async def slot_moved(self, o: Order) -> None:
        await self._send(o.user_id, f"🔔 Заявка №{o.id}: время изменилось, теперь <b>{texts.fmt_dt(o.slot)}</b>.")
        await self.sheets.upsert(o)

    async def reminder(self, o: Order) -> None:
        await self._send(o.user_id, texts.reminder(o, self.settings))
