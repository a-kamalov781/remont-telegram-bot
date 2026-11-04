"""SQLite через aiosqlite: заявки, услуги по нишам, блокировки слотов, аналитика демо."""
from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiosqlite

from bot.niches import ACTIVE_STATUSES, DEFAULT_NICHE, NICHES, Niche, get_niche

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
CREATE TABLE IF NOT EXISTS demo_users (
    user_id INTEGER PRIMARY KEY,
    niche TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demo_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    niche TEXT NOT NULL,
    event TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Колонки, появившиеся после первой версии. Строки старой базы получают значения по умолчанию,
# поэтому существующие заявки и услуги становятся заявками и услугами ниши repair.
MIGRATIONS: dict[str, dict[str, str]] = {
    "services": {"niche": f"TEXT NOT NULL DEFAULT '{DEFAULT_NICHE}'"},
    "orders": {
        "niche": f"TEXT NOT NULL DEFAULT '{DEFAULT_NICHE}'",
        "demo": "INTEGER NOT NULL DEFAULT 0",
        "address": "TEXT NOT NULL DEFAULT ''",
        "quote_answer": "TEXT NOT NULL DEFAULT ''",
    },
}

_ACTIVE_MARKS = ",".join("?" * len(ACTIVE_STATUSES))

DEMO_EVENT_NICHE = "niche"
DEMO_EVENT_BOOKED = "booked"
DEMO_EVENT_FINISHED = "finished"


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
    niche: str = DEFAULT_NICHE
    demo: bool = False
    address: str = ""
    quote_answer: str = ""

    @classmethod
    def from_row(cls, r: aiosqlite.Row) -> "Order":
        return cls(
            id=r["id"], user_id=r["user_id"], username=r["username"], name=r["name"],
            phone=r["phone"], service_id=r["service_id"], service_name=r["service_name"],
            device=r["device"], problem=r["problem"],
            slot=datetime.fromisoformat(r["slot"]), status=r["status"],
            admin_note=r["admin_note"], created_at=datetime.fromisoformat(r["created_at"]),
            reminded=bool(r["reminded"]), niche=r["niche"], demo=bool(r["demo"]),
            address=r["address"], quote_answer=r["quote_answer"],
        )

    @property
    def preset(self) -> Niche:
        return get_niche(self.niche)

    @property
    def status_text(self) -> str:
        return self.preset.status_text(self.status)

    @property
    def awaits_quote_answer(self) -> bool:
        """Мастер указал сумму, клиент ещё не ответил."""
        status = self.preset.status(self.status)
        return bool(status and status.approval and self.admin_note and not self.quote_answer)


def _scope(user_id: int | None) -> tuple[str, tuple]:
    """Демо-заявки посетителя видны только ему и не пересекаются с настоящими записями."""
    if user_id is None:
        return "demo=0", ()
    return "demo=1 AND user_id=?", (user_id,)


class Database:
    def __init__(self, path: str, niche: str = DEFAULT_NICHE, seed_all: bool = False):
        self.path = path
        self.niche = niche
        self.seed_all = seed_all

    async def init(self) -> None:
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            await self._migrate(db)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_services_niche ON services(niche)")
            for key in (NICHES if self.seed_all else (self.niche,)):
                await self._seed_services(db, key)
            await db.commit()

    @staticmethod
    async def _migrate(db: aiosqlite.Connection) -> None:
        for table, columns in MIGRATIONS.items():
            cur = await db.execute(f"PRAGMA table_info({table})")
            have = {row[1] for row in await cur.fetchall()}
            for column, definition in columns.items():
                if column not in have:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    async def _seed_services(db: aiosqlite.Connection, key: str) -> None:
        """Услуги пресета попадают в базу один раз: дальше ими управляет владелец."""
        cur = await db.execute("SELECT COUNT(*) FROM services WHERE niche=?", (key,))
        (n,) = await cur.fetchone()
        if n == 0:
            await db.executemany(
                "INSERT INTO services(name, description, price_from, niche) VALUES (?,?,?,?)",
                [(s.name, s.description, s.price_from, key) for s in NICHES[key].services],
            )

    # ---------- services ----------
    async def services(self, niche: str | None = None) -> list[aiosqlite.Row]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM services WHERE active=1 AND niche=? ORDER BY id",
                                   (niche or self.niche,))
            return list(await cur.fetchall())

    async def service(self, sid: int) -> aiosqlite.Row | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM services WHERE id=?", (sid,))
            return await cur.fetchone()

    # ---------- slots ----------
    async def taken_slots(self, day_iso: str, user_id: int | None = None) -> set[datetime]:
        where, params = _scope(user_id)
        q = f"SELECT slot FROM orders WHERE substr(slot,1,10)=? AND status IN ({_ACTIVE_MARKS}) AND {where}"
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(q, (day_iso, *ACTIVE_STATUSES, *params))
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
    async def has_active_order_at(self, phone: str, slot: datetime, user_id: int | None = None) -> bool:
        where, params = _scope(user_id)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                f"SELECT 1 FROM orders WHERE phone=? AND slot=? AND status IN ({_ACTIVE_MARKS}) AND {where}",
                (phone, slot.isoformat(), *ACTIVE_STATUSES, *params),
            )
            return await cur.fetchone() is not None

    async def slot_is_free(self, slot: datetime, user_id: int | None = None) -> bool:
        where, params = _scope(user_id)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                f"SELECT 1 FROM orders WHERE slot=? AND status IN ({_ACTIVE_MARKS}) AND {where} "
                "UNION SELECT 1 FROM blocked_slots WHERE slot=?",
                (slot.isoformat(), *ACTIVE_STATUSES, *params, slot.isoformat()),
            )
            return await cur.fetchone() is None

    async def create_order(self, *, user_id: int, username: str | None, name: str, phone: str,
                           service_id: int, service_name: str, device: str, problem: str,
                           slot: datetime, now: datetime, niche: str | None = None,
                           demo: bool = False, address: str = "") -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO orders(user_id, username, name, phone, service_id, service_name, "
                "device, problem, slot, status, created_at, niche, demo, address) "
                "VALUES (?,?,?,?,?,?,?,?,?,'new',?,?,?,?)",
                (user_id, username, name, phone, service_id, service_name, device, problem,
                 slot.isoformat(), now.isoformat(), niche or self.niche, int(demo), address),
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

    async def set_quote_answer(self, oid: int, answer: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET quote_answer=? WHERE id=?", (answer, oid))
            await db.commit()

    async def set_slot(self, oid: int, slot: datetime, status: str = "confirmed") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET slot=?, status=?, reminded=0 WHERE id=?",
                             (slot.isoformat(), status, oid))
            await db.commit()

    async def orders_for_day(self, day_iso: str) -> list[Order]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM orders WHERE substr(slot,1,10)=? AND status!='cancelled' ORDER BY slot",
                (day_iso,),
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def user_orders(self, user_id: int, limit: int = 5, niche: str | None = None) -> list[Order]:
        extra, params = (" AND niche=?", (niche,)) if niche else ("", ())
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"SELECT * FROM orders WHERE user_id=?{extra} ORDER BY id DESC LIMIT ?",
                (user_id, *params, limit),
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
        """Подтверждённые/новые заявки, визит в окне [now, now+before], ещё не напоминали.
        Посетителям демо напоминания не приходят: они не ждут визита."""
        hi = (now + timedelta(minutes=before_minutes)).isoformat()
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                f"SELECT * FROM orders WHERE reminded=0 AND demo=0 AND status IN ({_ACTIVE_MARKS}) "
                "AND slot>? AND slot<=?",
                (*ACTIVE_STATUSES, now.isoformat(), hi),
            )
            return [Order.from_row(r) for r in await cur.fetchall()]

    async def mark_reminded(self, oid: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE orders SET reminded=1 WHERE id=?", (oid,))
            await db.commit()

    async def stats(self, demo: bool | None = None) -> dict[str, int]:
        where, params = ("", ()) if demo is None else (" WHERE demo=?", (int(demo),))
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(f"SELECT status, COUNT(*) FROM orders{where} GROUP BY status", params)
            return {s: n for s, n in await cur.fetchall()}

    # ---------- демо ----------
    async def demo_touch(self, user_id: int, now: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR IGNORE INTO demo_users(user_id, created_at) VALUES (?,?)",
                             (user_id, now.isoformat()))
            await db.commit()

    async def demo_niche(self, user_id: int) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT niche FROM demo_users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_demo_niche(self, user_id: int, niche: str, now: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO demo_users(user_id, niche, created_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET niche=excluded.niche",
                (user_id, niche, now.isoformat()),
            )
            await db.commit()
        await self.demo_event(user_id, niche, DEMO_EVENT_NICHE, now)

    async def demo_event(self, user_id: int, niche: str, event: str, now: datetime) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT INTO demo_events(user_id, niche, event, created_at) VALUES (?,?,?,?)",
                             (user_id, niche, event, now.isoformat()))
            await db.commit()

    async def purge_demo_orders(self, cutoff: datetime) -> int:
        """Удаляет только демо-заявки старше cutoff. Аналитика в demo_events остаётся."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM orders WHERE demo=1 AND created_at<?", (cutoff.isoformat(),))
            await db.commit()
            return cur.rowcount

    async def demo_stats(self, exclude: Iterable[int] = ()) -> dict:
        """Люди, а не события: один посетитель считается один раз на шаг и нишу."""
        skip = tuple(exclude)
        marks = ",".join("?" * len(skip))
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(f"SELECT COUNT(*) FROM demo_users WHERE user_id NOT IN ({marks})", skip)
            (visitors,) = await cur.fetchone()
            cur = await db.execute(
                f"SELECT event, COUNT(DISTINCT user_id) FROM demo_events WHERE user_id NOT IN ({marks}) GROUP BY event",
                skip,
            )
            totals = {event: n for event, n in await cur.fetchall()}
            cur = await db.execute(
                "SELECT niche, event, COUNT(DISTINCT user_id) FROM demo_events "
                f"WHERE user_id NOT IN ({marks}) GROUP BY niche, event",
                skip,
            )
            by_niche: dict[str, dict[str, int]] = {}
            for niche, event, n in await cur.fetchall():
                by_niche.setdefault(niche, {})[event] = n
        return {
            "visitors": visitors,
            "chose": totals.get(DEMO_EVENT_NICHE, 0),
            "booked": totals.get(DEMO_EVENT_BOOKED, 0),
            "finished": totals.get(DEMO_EVENT_FINISHED, 0),
            "by_niche": by_niche,
        }
