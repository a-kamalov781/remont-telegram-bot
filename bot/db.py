"""SQLite через aiosqlite. Одна таблица заявок + услуги + блокировки слотов."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

# Статусы заявки — ровно то, что видит клиент
STATUSES: dict[str, str] = {
    "new": "🆕 Заявка принята",
    "confirmed": "📅 Визит подтверждён",
    "received": "🔧 Устройство принято в ремонт",
    "diagnosed": "🔍 Диагностика завершена",
    "waiting_parts": "📦 Ожидаем запчасти",
    "in_progress": "⚙️ В работе",
    "ready": "✅ Готово — можно забирать",
    "done": "🏁 Выдано",
    "cancelled": "❌ Отменено",
}

DEFAULT_SERVICES: list[tuple[str, str, int]] = [
    ("Диагностика", "Бесплатно при ремонте у нас", 0),
    ("Замена экрана телефона", "От 2 500 ₽, 1–2 часа", 2500),
    ("Замена аккумулятора", "От 1 500 ₽, 30–60 минут", 1500),
    ("Ремонт после воды", "От 2 000 ₽, 1–3 дня", 2000),
    ("Чистка ноутбука + термопаста", "От 1 800 ₽, 1–2 часа", 1800),
    ("Замена разъёма зарядки", "От 1 200 ₽, 1 час", 1200),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_from INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    service_id INTEGER NOT NULL,
    service_name TEXT NOT NULL,
    device TEXT NOT NULL DEFAULT '',
    problem TEXT NOT NULL DEFAULT '',
    slot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    admin_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_orders_slot ON orders(slot);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE TABLE IF NOT EXISTS blocked_slots (
    slot TEXT PRIMARY KEY
);
"""

ACTIVE_STATUSES = ("new", "confirmed")  # занимают слот


@dataclass
class Order:
    id: int
    user_id: int
    username: str | None
    name: str
    phone: str
    service_id: int
    service_name: str
    device: str
    problem: str
    slot: datetime
    status: str
    admin_note: str
    created_at: datetime
    reminded: bool

    @classmethod
    def from_row(cls, r: aiosqlite.Row) -> "Order":
        return cls(
            id=r["id"], user_id=r["user_id"], username=r["username"], name=r["name"],
            phone=r["phone"], service_id=r["service_id"], service_name=r["service_name"],
            device=r["device"], problem=r["problem"],
            slot=datetime.fromisoformat(r["slot"]), status=r["status"],
            admin_note=r["admin_note"], created_at=datetime.fromisoformat(r["created_at"]),
            reminded=bool(r["reminded"]),
        )

    @property
    def status_text(self) -> str:
        return STATUSES.get(self.status, self.status)


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            cur = await db.execute("SELECT COUNT(*) FROM services")
            (n,) = await cur.fetchone()
            if n == 0:
                await db.executemany(
                    "INSERT INTO services(name, description, price_from) VALUES (?,?,?)",
                    DEFAULT_SERVICES,
                )
            await db.commit()

    # ---------- services ----------
    async def services(self) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM services WHERE active=1 ORDER BY id")
            return list(await cur.fetchall())

    async def service(self, sid: int) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM services WHERE id=?", (sid,))
            return await cur.fetchone()

    # ---------- slots ----------
    async def taken_slots(self, day_iso: str) -> set[datetime]:
        q = "SELECT slot FROM orders WHERE substr(slot,1,10)=? AND status IN (?,?)"
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(q, (day_iso, *ACTIVE_STATUSES))
            return {datetime.fromisoformat(r[0]) for r in await cur.fetchall()}

    async def blocked_slots(self, day_iso: str) -> set[datetime]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT slot FROM blocked_slots WHERE substr(slot,1,10)=?", (day_iso,))
            return {datetime.fromisoformat(r[0]) for r in await cur.fetchall()}

    async def block_slot(self, slot: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR IGNORE INTO blocked_slots(slot) VALUES (?)", (slot.isoformat(),))
            await db.commit()

    async def unblock_slot(self, slot: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM blocked_slots WHERE slot=?", (slot.isoformat(),))
            await db.commit()

    # ---------- orders ----------
    async def has_active_order_at(self, phone: str, slot: datetime) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT 1 FROM orders WHERE phone=? AND slot=? AND status IN (?,?)",
                (phone, slot.isoformat(), *ACTIVE_STATUSES),
            )
            return await cur.fetchone() is not None

    async def slot_is_free(self, slot: datetime) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT 1 FROM orders WHERE slot=? AND status IN (?,?) "
                "UNION SELECT 1 FROM blocked_slots WHERE slot=?",
                (slot.isoformat(), *ACTIVE_STATUSES, slot.isoformat()),
            )
            return await cur.fetchone() is None

    async def create_order(self, *, user_id: int, username: str | None, name: str, phone: str,
                           service_id: int, service_name: str, device: str, problem: str,
                           slot: datetime, now: datetime) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO orders(user_id, username, name, phone, service_id, service_name, "
                "device, problem, slot, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,'new',?)",
                (user_id, username, name, phone, service_id, service_name, device, problem,
                 slot.isoformat(), now.isoformat()),
            )
            await db.commit()
            return cur.lastrowid  # type: ignore[return-value]

    async def order(self, oid: int) -> Order | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM orders WHERE id=?", (oid,))
            r = await cur.fetchone()
            return Order.from_row(r) if r else None

    async def set_status(self, oid: int, status: str, note: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            if note is None:
                await db.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
            else:
                await db.execute("UPDATE orders SET status=?, admin_note=? WHERE id=?", (status, note, oid))
            await db.commit()

    async def set_slot(self, oid: int, slot: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET slot=?, status='confirmed', reminded=0 WHERE id=?",
                             (slot.isoformat(), oid))
            await db.commit()

    async def orders_for_day(self, day_iso: str) -> list[Order]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM orders WHERE substr(slot,1,10)=? AND status!='cancelled' ORDER BY slot",
                (day_iso,),
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def user_orders(self, user_id: int, limit: int = 5) -> list[Order]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit)
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def open_orders(self) -> list[Order]:
        """Всё, что ещё не выдано и не отменено — для /open."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM orders WHERE status NOT IN ('done','cancelled') ORDER BY slot"
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def due_reminders(self, now: datetime, before_minutes: int) -> list[Order]:
        """Подтверждённые/новые заявки, визит в окне [now, now+before], ещё не напоминали."""
        from datetime import timedelta
        hi = (now + timedelta(minutes=before_minutes)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM orders WHERE reminded=0 AND status IN (?,?) AND slot>? AND slot<=?",
                (*ACTIVE_STATUSES, now.isoformat(), hi),
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def mark_reminded(self, oid: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET reminded=1 WHERE id=?", (oid,))
            await db.commit()

    async def stats(self) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
            return {s: n for s, n in await cur.fetchall()}
