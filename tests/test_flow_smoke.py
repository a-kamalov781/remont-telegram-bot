"""Дымовой тест полного сценария записи через Dispatcher без сети (MockedBot)."""
from __future__ import annotations

from datetime import datetime, time

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.config import Settings
from bot.db import Database
from bot.handlers import admin, client
from bot.services.notify import Notifier
from bot.services.sheets import SheetsExporter

try:
    from aiogram.tests.mocked_bot import MockedBot  # type: ignore
except ImportError:  # aiogram без tests-пакета
    MockedBot = None  # type: ignore


class CapturingNotifier(Notifier):
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def new_order(self, o):
        self.calls.append(("new", o.id))

    async def status_changed(self, o):
        self.calls.append(("status", o.id))

    async def slot_moved(self, o):
        self.calls.append(("moved", o.id))


class FakeBot:
    """Минимальный бот: собирает вызовы методов, ничего не шлёт."""
    def __init__(self):
        self.sent: list[str] = []
        self.id = 1

    async def __call__(self, method, *a, **kw):
        if isinstance(method, (SendMessage, EditMessageText)):
            self.sent.append(method.text)
        return True

    async def set_my_commands(self, *a, **kw):
        return True


USER = User(id=100, is_bot=False, first_name="Клиент", username="client")
ADMIN = User(id=777, is_bot=False, first_name="Мастер")
CHAT = Chat(id=100, type="private")
_mid = iter(range(1, 10_000))


def msg(text: str, user: User = USER) -> Update:
    m = Message(message_id=next(_mid), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=user, text=text)
    return Update(update_id=next(_mid), message=m)


def cb(data: str, user: User = USER) -> Update:
    m = Message(message_id=next(_mid), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=user, text="x")
    q = CallbackQuery(id=str(next(_mid)), from_user=user, chat_instance="ci", message=m, data=data)
    return Update(update_id=next(_mid), callback_query=q)


@pytest.mark.asyncio
async def test_full_booking_flow(tmp_path, monkeypatch):
    settings = Settings(bot_token="1:x", admin_ids=[777], db_path=str(tmp_path / "db.sqlite"),
                        work_start=time(0, 0), work_end=time(23, 59), slot_minutes=60,
                        work_days=[0, 1, 2, 3, 4, 5, 6], days_ahead=3, _env_file=None)
    db = Database(settings.db_path)
    await db.init()
    notifier = CapturingNotifier()
    bot = FakeBot()

    dp = Dispatcher(storage=MemoryStorage())
    dp["settings"], dp["db"], dp["notifier"] = settings, db, notifier
    dp.include_router(admin.router)
    dp.include_router(client.router)

    # Патчим Message.answer / edit_text и CallbackQuery.answer, чтобы не ходить в сеть
    async def _answer(self, text=None, **kw):
        bot.sent.append(text or "")
    async def _edit(self, text=None, **kw):
        bot.sent.append(text or "")
    async def _noop(self, *a, **kw):
        return True
    monkeypatch.setattr(Message, "answer", _answer)
    monkeypatch.setattr(Message, "edit_text", _edit)
    monkeypatch.setattr(Message, "edit_reply_markup", _noop)
    monkeypatch.setattr(CallbackQuery, "answer", _noop)

    await dp.feed_update(bot, msg("/start"))
    assert any("Это бот" in t for t in bot.sent)

    await dp.feed_update(bot, msg("📝 Записаться на ремонт"))
    await dp.feed_update(bot, cb("svc:2"))
    # дата — завтра
    from datetime import date, timedelta
    d = (date.today() + timedelta(days=1)).isoformat()
    await dp.feed_update(bot, cb(f"date:{d}"))
    slot = datetime.fromisoformat(f"{d}T12:00:00")
    await dp.feed_update(bot, cb(f"slot:{slot.isoformat()}"))
    await dp.feed_update(bot, msg("Иван"))
    await dp.feed_update(bot, msg("8 912 345 67 89"))
    await dp.feed_update(bot, msg("iPhone 13"))
    await dp.feed_update(bot, msg("разбит экран"))
    assert any("Проверьте заявку" in t for t in bot.sent)
    await dp.feed_update(bot, cb("confirm"))

    assert notifier.calls == [("new", 1)]
    o = await db.order(1)
    assert o.phone == "+7 (912) 345-67-89" and o.slot == slot and o.status == "new"

    # Клиент смотрит статус
    await dp.feed_update(bot, msg("🔎 Статус моего ремонта"))
    assert any("Заявка №1" in t for t in bot.sent)

    # Мастер меняет статус кнопкой — клиент получает уведомление
    await dp.feed_update(bot, cb("adm:ready:1", ADMIN))
    assert ("status", 1) in notifier.calls
    assert (await db.order(1)).status == "ready"

    # Не-админ не может
    before = len(notifier.calls)
    await dp.feed_update(bot, cb("adm:done:1", USER))
    assert len(notifier.calls) == before

    # Команды мастера
    await dp.feed_update(bot, msg("/today", ADMIN))
    await dp.feed_update(bot, msg("/note 1 Экран заказан, будет завтра", ADMIN))
    assert (await db.order(1)).admin_note.startswith("Экран заказан")
    await dp.feed_update(bot, msg("/stats", ADMIN))
    assert any("Готово" in t for t in bot.sent)
