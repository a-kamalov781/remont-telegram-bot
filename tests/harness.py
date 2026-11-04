"""Прогон обновлений через Dispatcher без сети: все ответы бота складываются в список."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import count

from aiogram import Dispatcher
from aiogram.exceptions import TelegramForbiddenError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, PhotoSize, Update, User

from bot.config import Settings
from bot.db import Database
from bot.handlers import admin, client, demo
from bot.services.notify import Notifier
from bot.services.sheets import SheetsExporter

_ids = count(1)
TOMORROW = date.today() + timedelta(days=1)
SLOT = datetime.combine(TOMORROW, time(12, 0))
ADMIN = User(id=777, is_bot=False, first_name="Владелец")


@dataclass
class Sent:
    chat_id: int
    text: str
    markup: object = None
    message_id: int = 0
    copied_from: int | None = None

    def buttons(self) -> list[tuple[str, str]]:
        if not isinstance(self.markup, InlineKeyboardMarkup):
            return []
        return [(b.text, b.callback_data) for row in self.markup.inline_keyboard for b in row]

    def callbacks(self) -> list[str]:
        return [data for _, data in self.buttons()]


@dataclass
class RecordingBot:
    sent: list[Sent] = field(default_factory=list)
    id: int = 1

    blocked: set[int] = field(default_factory=set)

    def _check_reachable(self, chat_id):
        if chat_id in self.blocked:
            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self._check_reachable(chat_id)
        sent = Sent(chat_id, text, reply_markup, message_id=next(_ids))
        self.sent.append(sent)
        return sent

    async def copy_message(self, chat_id, from_chat_id, message_id, **kw):
        self._check_reachable(chat_id)
        sent = Sent(chat_id, "", message_id=next(_ids), copied_from=message_id)
        self.sent.append(sent)
        return sent

    async def __call__(self, method, *a, **kw):
        return True


def visitor(uid: int = 100) -> User:
    return User(id=uid, is_bot=False, first_name="Посетитель", username=f"user{uid}")


def message(text: str, user: User) -> Update:
    m = Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=user, text=text)
    return Update(update_id=next(_ids), message=m)


def reply(text: str, user: User, to_message_id: int) -> Update:
    chat = Chat(id=user.id, type="private")
    replied = Message(message_id=to_message_id, date=datetime.now(), chat=chat, text="исходное")
    m = Message(message_id=next(_ids), date=datetime.now(), chat=chat, from_user=user, text=text,
                reply_to_message=replied)
    return Update(update_id=next(_ids), message=m)


def photo(user: User) -> Update:
    size = PhotoSize(file_id="f", file_unique_id="u", width=1, height=1)
    m = Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=user, photo=[size], caption="вот пятно")
    return Update(update_id=next(_ids), message=m)


def callback(data: str, user: User) -> Update:
    m = Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                from_user=user, text="x")
    q = CallbackQuery(id=str(next(_ids)), from_user=user, chat_instance="ci", message=m, data=data)
    return Update(update_id=next(_ids), callback_query=q)


class Harness:
    def __init__(self, settings: Settings, db: Database, monkeypatch):
        self.settings, self.db = settings, db
        self.bot = RecordingBot()
        self.alerts: list[str] = []
        self.notifier = Notifier(self.bot, settings, SheetsExporter("", ""))
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp["settings"], self.dp["db"], self.dp["notifier"] = settings, db, self.notifier
        self.dp.include_router(admin.router)
        self.dp.include_router(demo.router)
        self.dp.include_router(client.router)

        sent = self.bot.sent
        alerts = self.alerts

        async def answer(msg, text=None, reply_markup=None, **kw):
            sent.append(Sent(msg.chat.id, text or "", reply_markup))

        async def edit_text(msg, text=None, reply_markup=None, **kw):
            sent.append(Sent(msg.chat.id, text or "", reply_markup))

        markups = self.markups = []

        async def edit_markup(msg, reply_markup=None, **kw):
            markups.append(Sent(msg.chat.id, "", reply_markup))
            return True

        async def cb_answer(query, text=None, **kw):
            if text:
                alerts.append(text)
            return True

        monkeypatch.setattr(Message, "answer", answer)
        monkeypatch.setattr(Message, "edit_text", edit_text)
        monkeypatch.setattr(Message, "edit_reply_markup", edit_markup)
        monkeypatch.setattr(CallbackQuery, "answer", cb_answer)

    async def say(self, text: str, user: User) -> None:
        await self.dp.feed_update(self.bot, message(text, user))

    async def press(self, data: str, user: User) -> None:
        await self.dp.feed_update(self.bot, callback(data, user))

    def texts_to(self, user: User) -> list[str]:
        return [s.text for s in self.bot.sent if s.chat_id == user.id]

    def last_to(self, user: User) -> Sent:
        return [s for s in self.bot.sent if s.chat_id == user.id][-1]

    async def book(self, user: User, menu_button: str, device: str = "Объект", problem: str = "Проблема",
                   address: str | None = None, slot: datetime = SLOT, phone: str = "8 912 345 67 89") -> None:
        """Полный сценарий записи: первая услуга ниши, завтра в 12:00."""
        await self.say(menu_button, user)
        first_service = next(d for _, d in self.last_to(user).buttons() if d.startswith("svc:"))
        await self.press(first_service, user)
        await self.press(f"date:{slot.date().isoformat()}", user)
        await self.press(f"slot:{slot.isoformat()}", user)
        await self.say("Анна", user)
        await self.say(phone, user)
        await self.say(device, user)
        await self.say(problem, user)
        if address is not None:
            await self.say(address, user)
        await self.press("confirm", user)


async def make(tmp_path, monkeypatch, niche: str = "repair", demo_mode: bool = False,
               demo_contact: str = "") -> Harness:
    settings = Settings(bot_token="1:x", admin_ids=[ADMIN.id], db_path=str(tmp_path / "db.sqlite"),
                        niche=niche, demo_mode=demo_mode, demo_contact=demo_contact,
                        work_start=time(0, 0), work_end=time(23, 59),
                        work_days=[0, 1, 2, 3, 4, 5, 6], days_ahead=3, _env_file=None)
    db = Database(settings.db_path, settings.niche, seed_all=demo_mode)
    await db.init()
    return Harness(settings, db, monkeypatch)
