"""Пресеты ниш, настройка NICHE, миграция старой базы."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest
from pydantic import ValidationError

from bot.config import Settings
from bot.db import Database
from bot.niches import ACTIVE_STATUSES, NICHES, get_niche, status_label

ALL = sorted(NICHES)


def test_all_required_niches_exist():
    assert set(NICHES) == {"repair", "drycleaning", "atelier", "autoservice", "appliance"}


@pytest.mark.parametrize("key", ALL)
def test_preset_is_valid(key):
    assert NICHES[key].problems() == []


@pytest.mark.parametrize("key", ALL)
def test_statuses_unique_with_final_and_cancelled(key):
    niche = NICHES[key]
    codes = [s.code for s in niche.all_statuses]
    assert len(codes) == len(set(codes))
    assert niche.final.code == "done"
    assert codes[-1] == "cancelled"
    assert all(s.text.strip() for s in niche.all_statuses)


def test_validator_catches_a_broken_preset():
    from dataclasses import replace

    from bot.niches import Status
    broken = replace(NICHES["repair"], menu_book=" ",
                     statuses=(Status("new", "A", holds_slot=True), Status("new", "A"), Status("x", "B")))
    found = "; ".join(broken.problems())
    assert "коды статусов повторяются" in found
    assert "тексты статусов повторяются" in found
    assert "последний статус" in found
    assert "пустое поле menu_book" in found


def test_same_status_code_means_the_same_slot_behaviour_everywhere():
    """ACTIVE_STATUSES общий на все ниши, поэтому код не может занимать время только в одной из них."""
    for niche in NICHES.values():
        for status in niche.statuses:
            assert status.holds_slot == (status.code in ACTIVE_STATUSES), (niche.key, status.code)


def test_repair_stays_as_it_was():
    repair = NICHES["repair"]
    assert [s.code for s in repair.all_statuses] == [
        "new", "confirmed", "received", "diagnosed", "waiting_parts", "in_progress", "ready", "done", "cancelled",
    ]
    assert repair.status_text("ready") == "✅ Готово — можно забирать"
    assert repair.menu_book == "📝 Записаться на ремонт"
    assert repair.slot_minutes == 60
    assert repair.visit_status == "confirmed"
    assert len(repair.services) == 6


@pytest.mark.parametrize("key,codes", [
    ("drycleaning", ["new", "assessment", "cleaning", "ready", "done"]),
    ("atelier", ["new", "fitting", "in_progress", "ready", "done"]),
    ("autoservice", ["new", "diagnostics", "approval", "waiting_parts", "in_progress", "ready", "done"]),
])
def test_requested_status_chains(key, codes):
    assert [s.code for s in NICHES[key].statuses] == codes


def test_only_autoservice_has_quote_approval_and_only_appliance_asks_address():
    assert [k for k, n in NICHES.items() if any(s.approval for s in n.statuses)] == ["autoservice"]
    assert [k for k, n in NICHES.items() if n.ask_address] == ["appliance"]


def test_get_niche_falls_back_for_unknown_key():
    assert get_niche("нет такой").key == "repair"


def test_status_label_prefers_given_niche_and_knows_other_niches():
    assert status_label("ready", NICHES["appliance"]) == "✅ Ремонт завершён"
    assert status_label("assessment", NICHES["repair"]) == "🔍 Вещь на оценке"
    assert status_label("неизвестный") == "неизвестный"


def test_settings_reject_unknown_niche():
    with pytest.raises(ValidationError):
        Settings(bot_token="1:x", admin_ids=[1], niche="пекарня", _env_file=None)


def test_settings_parse_demo_and_niche_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=1:x\nADMIN_IDS=1\nNICHE=autoservice\nDEMO_MODE=true\nDEMO_CONTACT=@someone\nSLOT_MINUTES=\n",
        encoding="utf-8",
    )
    for name in ("BOT_TOKEN", "ADMIN_IDS", "NICHE", "DEMO_MODE", "DEMO_CONTACT", "SLOT_MINUTES"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=env_file)
    assert (s.niche, s.demo_mode, s.demo_contact, s.slot_minutes) == ("autoservice", True, "@someone", None)


@pytest.mark.asyncio
async def test_services_seeded_only_for_chosen_niche(tmp_path):
    db = Database(str(tmp_path / "t.db"), "drycleaning")
    await db.init()
    assert [s["name"] for s in await db.services()] == [s.name for s in NICHES["drycleaning"].services]
    assert await db.services("repair") == []


@pytest.mark.asyncio
async def test_services_are_not_reseeded_on_restart(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path, "atelier")
    await db.init()
    with sqlite3.connect(path) as con:
        con.execute("UPDATE services SET price_from=999 WHERE name='Укоротить брюки'")
        con.execute("DELETE FROM services WHERE name='Замена молнии'")
    await Database(path, "atelier").init()
    names = {s["name"]: s["price_from"] for s in await db.services()}
    assert names["Укоротить брюки"] == 999
    assert "Замена молнии" not in names


@pytest.mark.asyncio
async def test_demo_seeds_every_niche(tmp_path):
    db = Database(str(tmp_path / "t.db"), "repair", seed_all=True)
    await db.init()
    for key, niche in NICHES.items():
        assert len(await db.services(key)) == len(niche.services)


OLD_SCHEMA = """
CREATE TABLE services (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '', price_from INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, username TEXT,
    name TEXT NOT NULL, phone TEXT NOT NULL, service_id INTEGER NOT NULL, service_name TEXT NOT NULL,
    device TEXT NOT NULL DEFAULT '', problem TEXT NOT NULL DEFAULT '', slot TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new', admin_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0);
CREATE TABLE blocked_slots (slot TEXT PRIMARY KEY);
INSERT INTO services(name, description, price_from) VALUES ('Своя услуга', 'Правка владельца', 777);
INSERT INTO orders(user_id, username, name, phone, service_id, service_name, device, problem, slot, status,
    admin_note, created_at) VALUES (5, 'old', 'Пётр', '+7 (900) 000-00-00', 1, 'Своя услуга', 'iPhone', 'экран',
    '2026-12-01T12:00:00', 'ready', 'заказали экран', '2026-11-01T10:00:00');
"""


@pytest.mark.asyncio
async def test_old_database_is_migrated_without_losing_data(tmp_path):
    path = str(tmp_path / "old.db")
    with sqlite3.connect(path) as con:
        con.executescript(OLD_SCHEMA)

    db = Database(path, "repair", seed_all=True)
    await db.init()
    await db.init()  # повторный запуск ничего не ломает

    o = await db.order(1)
    assert (o.name, o.status, o.admin_note, o.niche, o.demo, o.address) == (
        "Пётр", "ready", "заказали экран", "repair", False, "")
    assert o.status_text == "✅ Готово — можно забирать"
    # Правленые услуги ремонта остаются как есть, новых услуг ремонта не появляется
    assert [(s["name"], s["price_from"]) for s in await db.services("repair")] == [("Своя услуга", 777)]
    assert len(await db.services("drycleaning")) == len(NICHES["drycleaning"].services)
    # Старая заявка не считается демо и не удаляется автоочисткой
    assert await db.purge_demo_orders(datetime(2030, 1, 1)) == 0
    assert await db.order(1) is not None
