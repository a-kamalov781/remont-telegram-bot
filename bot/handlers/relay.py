"""Ответ мастера клиенту: Reply на сообщение клиента в чате с ботом.

Обработчик подключён в роутерах admin и demo после их команд. Запись ищется по чату мастера,
поэтому ответить можно только на сообщение, которое бот прислал именно в этот чат.
"""
from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot import texts
from bot.db import Database
from bot.services.notify import Notifier


class RelayReply(BaseFilter):
    async def __call__(self, m: Message, db: Database) -> bool | dict:
        replied = m.reply_to_message
        if replied is None or (m.text or "").startswith("/"):
            return False
        target = await db.relay_target(m.chat.id, replied.message_id)
        return {"relay": target} if target else False


async def answer_client(m: Message, relay: tuple[int, bool], notifier: Notifier) -> None:
    client_id, demo = relay
    delivered = await notifier.master_reply(m, client_id, demo)
    if not delivered:
        await m.answer(texts.master_answer_failed())
    elif not demo:
        await m.answer(texts.master_answer_sent())
