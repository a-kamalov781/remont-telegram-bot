"""Комментарий мастера показывается только в том статусе, к которому его добавили."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bot.db import Database
from bot.niches import NICHES
from tests.harness import ADMIN, SLOT, make, visitor

CLIENT = visitor()


@pytest.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    await d.init()
    return d


async def _order(db) -> int:
    return await db.create_order(user_id=1, username="u", name="Иван", phone="+7 (912) 345-67-89",
                                 service_id=1, service_name="Диагностика", device="iPhone", problem="экран",
                                 slot=SLOT, now=datetime(2026, 11, 3, 22, 0))


@pytest.mark.asyncio
async def test_status_change_clears_note(db):
    oid = await _order(db)
    await db.set_status(oid, "received", note="Нужна замена платы")
    await db.set_status(oid, "in_progress")
    o = await db.order(oid)
    assert (o.status, o.admin_note) == ("in_progress", "")


@pytest.mark.asyncio
async def test_same_status_keeps_note(db):
    oid = await _order(db)
    await db.set_status(oid, "received", note="Нужна замена платы")
    await db.set_status(oid, "received")
    assert (await db.order(oid)).admin_note == "Нужна замена платы"


@pytest.mark.asyncio
async def test_status_change_with_new_note_keeps_new_note(db):
    oid = await _order(db)
    await db.set_status(oid, "received", note="Старый")
    await db.set_status(oid, "in_progress", note="Новый")
    assert (await db.order(oid)).admin_note == "Новый"


@pytest.mark.asyncio
async def test_move_clears_note_only_when_status_changes(db):
    oid = await _order(db)
    await db.set_status(oid, "confirmed", note="Приезжайте со шнуром")
    await db.set_slot(oid, SLOT + timedelta(hours=1))
    assert (await db.order(oid)).admin_note == "Приезжайте со шнуром"

    await db.set_status(oid, "received", note="Принято")
    await db.set_slot(oid, SLOT + timedelta(hours=2))
    o = await db.order(oid)
    assert (o.status, o.admin_note) == ("confirmed", "")


@pytest.mark.asyncio
async def test_client_does_not_see_old_note_after_status_button(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch)
    await h.book(CLIENT, NICHES["repair"].menu_book)
    await h.press("adm:received:1", ADMIN)

    await h.say("/note 1 Нужна замена платы, срок 3 дня", ADMIN)
    assert "Нужна замена платы" in h.last_to(CLIENT).text

    await h.say("/status", CLIENT)
    assert "Нужна замена платы" in h.last_to(CLIENT).text

    await h.press("adm:in_progress:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>⚙️ В работе</b>"
    assert (await h.db.order(1)).admin_note == ""

    await h.say("/status", CLIENT)
    assert "Нужна замена платы" not in h.last_to(CLIENT).text

    # Новый комментарий работает в новом статусе и тоже живёт только в нём
    await h.say("/note 1 Плата приехала", ADMIN)
    assert "Плата приехала" in h.last_to(CLIENT).text
    await h.press("adm:ready:1", ADMIN)
    assert "Плата приехала" not in h.last_to(CLIENT).text


@pytest.mark.asyncio
async def test_pressing_current_status_keeps_note(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch)
    await h.book(CLIENT, NICHES["repair"].menu_book)
    await h.press("adm:received:1", ADMIN)
    await h.say("/note 1 Нужна замена платы", ADMIN)
    await h.press("adm:received:1", ADMIN)
    assert (await h.db.order(1)).admin_note == "Нужна замена платы"


@pytest.mark.asyncio
async def test_agreed_sum_does_not_repeat_in_following_demo_statuses(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True, demo_contact="@kamalovTG")
    await h.say("/start", CLIENT)
    await h.press("niche:autoservice", CLIENT)
    await h.book(CLIENT, NICHES["autoservice"].menu_book)
    await h.press("adm:approval:1", CLIENT)
    await h.say("/note 1 8 500 ₽, замена колодок", CLIENT)
    await h.press("quote:yes:1", CLIENT)
    assert "8 500 ₽" in h.last_to(CLIENT).text  # мастер видит сумму в ответе клиента

    seen = len(h.bot.sent)
    for code in ("in_progress", "ready", "done"):
        await h.press(f"adm:{code}:1", CLIENT)
    assert not any("8 500 ₽" in s.text for s in h.bot.sent[seen:])
