"""Общие middleware: «часики» на кнопках не остаются, сообщения в чате считаются для возраста карточки."""
from __future__ import annotations

from aiogram import BaseMiddleware, Dispatcher
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message


class CallbackGuard(BaseMiddleware):
    """Обработчики отвечают на нажатие сами и сразу. Это страховка: на ошибку и на кнопку без обработчика."""

    @staticmethod
    async def _answer(event: CallbackQuery) -> None:
        try:
            await event.answer()
        except TelegramAPIError:
            pass

    async def __call__(self, handler, event: CallbackQuery, data: dict):
        try:
            result = await handler(event, data)
        except Exception:
            await self._answer(event)
            raise
        if result is UNHANDLED:
            await self._answer(event)
        return result


class ChatActivity(BaseMiddleware):
    """Сообщение пользователя и обычно один ответ на него. Возраст карточки считается приблизительно."""

    async def __call__(self, handler, event: Message, data: dict):
        notifier = data.get("notifier")
        if notifier is not None:
            notifier.note_activity(event.chat.id, 2)
        return await handler(event, data)


def install(dp: Dispatcher) -> None:
    dp.callback_query.outer_middleware(CallbackGuard())
    dp.message.outer_middleware(ChatActivity())
