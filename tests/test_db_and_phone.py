from datetime import datetime

import pytest

from bot.db import Database
from bot.handlers.client import normalize_phone


@pytest.mark.parametrize("raw,expected", [
    ("+7 912 345-67-89", "+7 (912) 345-67-89"),
    ("89123456789", "+7 (912) 345-67-89"),
    ("9123456789", "+7 (912) 345-67-89"),
    ("+79123456789", "+7 (912) 345-67-89"),
    ("12345", None),
    ("привет", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    await d.init()
    return d


async def _create(db, slot, phone="+7 (912) 345-67-89", user_id=1):
    return await db.create_order(user_id=user_id, username="u", name="Иван", phone=phone,
                                 service_id=1, service_name="Диагностика", device="iPhone",
                                 problem="не включается", slot=slot, now=datetime(2026, 11, 3, 22, 0))


@pytest.mark.asyncio
async def test_default_services_seeded(db):
    assert len(await db.services()) == 6


@pytest.mark.asyncio
async def test_slot_taken_after_order_and_freed_after_cancel(db):
    slot = datetime(2026, 11, 5, 14, 0)
    assert await db.slot_is_free(slot)
    oid = await _create(db, slot)
    assert not await db.slot_is_free(slot)
    assert slot in await db.taken_slots("2026-11-05")
    await db.set_status(oid, "cancelled")
    assert await db.slot_is_free(slot)


@pytest.mark.asyncio
async def test_slot_still_taken_when_received_but_not_double_counted(db):
    """После приёма устройства слот визита уже прошёл, но заявка не должна занимать новый слот."""
    slot = datetime(2026, 11, 5, 14, 0)
    oid = await _create(db, slot)
    await db.set_status(oid, "received")
    # received не в ACTIVE_STATUSES: визит состоялся, слот освобождён для других
    assert await db.slot_is_free(slot)


@pytest.mark.asyncio
async def test_antidouble_same_phone_same_slot(db):
    slot = datetime(2026, 11, 5, 15, 0)
    await _create(db, slot)
    assert await db.has_active_order_at("+7 (912) 345-67-89", slot)
    assert not await db.has_active_order_at("+7 (999) 000-00-00", slot)


@pytest.mark.asyncio
async def test_block_unblock(db):
    slot = datetime(2026, 11, 6, 11, 0)
    await db.block_slot(slot)
    assert not await db.slot_is_free(slot)
    assert slot in await db.blocked_slots("2026-11-06")
    await db.unblock_slot(slot)
    assert await db.slot_is_free(slot)


@pytest.mark.asyncio
async def test_due_reminders_window_and_once(db):
    slot = datetime(2026, 11, 5, 14, 0)
    oid = await _create(db, slot)
    now = datetime(2026, 11, 5, 12, 30)
    due = await db.due_reminders(now, 120)
    assert [o.id for o in due] == [oid]
    await db.mark_reminded(oid)
    assert await db.due_reminders(now, 120) == []
    # слишком рано — не в окне
    oid2 = await _create(db, datetime(2026, 11, 5, 17, 0), user_id=2)
    assert all(o.id != oid2 for o in await db.due_reminders(now, 120))


@pytest.mark.asyncio
async def test_move_resets_reminder_and_confirms(db):
    oid = await _create(db, datetime(2026, 11, 5, 14, 0))
    await db.mark_reminded(oid)
    await db.set_slot(oid, datetime(2026, 11, 6, 10, 0))
    o = await db.order(oid)
    assert o.status == "confirmed" and o.reminded is False
    assert o.slot == datetime(2026, 11, 6, 10, 0)


@pytest.mark.asyncio
async def test_stats_and_open(db):
    a = await _create(db, datetime(2026, 11, 5, 14, 0))
    b = await _create(db, datetime(2026, 11, 5, 15, 0), user_id=2)
    await db.set_status(b, "done")
    assert await db.stats() == {"new": 1, "done": 1}
    assert [o.id for o in await db.open_orders()] == [a]
