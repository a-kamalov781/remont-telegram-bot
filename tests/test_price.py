"""Стоимость заявки: отдельное поле, разбор суммы, /price, вывод в /order, таблице и статусе готовности."""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from bot.db import Database
from bot.niches import NICHES
from bot.services.price import format_rub, parse_amount
from bot.services.sheets import SheetsExporter, header
from tests.harness import ADMIN, SLOT, make, visitor

CLIENT = visitor()
AUTO = NICHES["autoservice"]


@pytest.mark.parametrize("text,expected", [
    ("8 500 ₽, замена колодок", 8500),
    ("8500", 8500),
    ("8500р", 8500),
    ("12 000 руб", 12000),
    ("1 250 000 ₽", 1250000),
    ("Замена 2 колодок: 8 500 ₽", 8500),
    ("2 колодки и работа 8500", 8500),
    ("4 диска по 1 500 р", 1500),
    ("8 500 ₽", 8500),
    ("Смотрим подвеску", None),
    ("0", None),
    ("Перезвоните 89123456789", None),
    ("", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_format_rub():
    assert format_rub(8500) == "8 500 ₽"
    assert format_rub(900) == "900 ₽"


async def auto(tmp_path, monkeypatch, **kw):
    h = await make(tmp_path, monkeypatch, niche="autoservice", **kw)
    return h


@pytest.mark.asyncio
async def test_note_in_approval_saves_price_and_it_survives_status_changes(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/note 1 8 500 ₽, замена колодок", ADMIN)
    assert (await h.db.order(1)).price == 8500
    assert "Стоимость записана" in h.last_to(ADMIN).text

    for code in ("waiting_parts", "in_progress"):
        await h.press(f"adm:{code}:1", ADMIN)
        o = await h.db.order(1)
        assert (o.price, o.admin_note) == (8500, "")


@pytest.mark.asyncio
async def test_ready_status_shows_amount_to_client(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.say("/price 1 8500", ADMIN)
    await h.press("adm:ready:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>✅ Готово — к оплате 8 500 ₽</b>"

    await h.say("/status", CLIENT)
    assert "к оплате 8 500 ₽" in h.last_to(CLIENT).text

    # После выдачи статус обычный, а сумма остаётся в заявке
    await h.press("adm:done:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>🏁 Выдано</b>"
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_ready_status_without_price_stays_plain(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.press("adm:ready:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>✅ Готово, можно забирать</b>"


@pytest.mark.asyncio
async def test_order_card_shows_price(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.say("/order 1", ADMIN)
    assert "Стоимость" not in h.last_to(ADMIN).text
    await h.say("/price 1 12 000 ₽", ADMIN)
    await h.say("/order 1", ADMIN)
    assert "💰 Стоимость: <b>12 000 ₽</b>" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_price_command_does_not_message_the_client(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    before = len(h.texts_to(CLIENT))
    await h.say("/price 1 8500", ADMIN)
    assert len(h.texts_to(CLIENT)) == before
    assert "записана" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_new_amount_replaces_old_one(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/note 1 8 500 ₽", ADMIN)
    await h.say("/note 1 9 000 ₽ с учётом масла", ADMIN)
    assert (await h.db.order(1)).price == 9000
    await h.say("/price 1 7000", ADMIN)
    assert (await h.db.order(1)).price == 7000


@pytest.mark.asyncio
async def test_note_outside_approval_does_not_touch_price(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.say("/price 1 8500", ADMIN)
    await h.press("adm:diagnostics:1", ADMIN)
    await h.say("/note 1 Осмотр займёт 30 минут", ADMIN)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_note_without_amount_in_approval_warns_master(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/note 1 Позвоним и обсудим", ADMIN)
    assert (await h.db.order(1)).price is None
    assert "Сумму в тексте не нашёл" in h.last_to(ADMIN).text


@pytest.mark.asyncio
@pytest.mark.parametrize("args", ["", "1", "abc 100", "1 abc", "1 0"])
async def test_price_rejects_bad_input(tmp_path, monkeypatch, args):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.say(f"/price {args}".strip(), ADMIN)
    assert "Формат: /price" in h.last_to(ADMIN).text
    assert (await h.db.order(1)).price is None


@pytest.mark.asyncio
async def test_price_unknown_order(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.say("/price 99 100", ADMIN)
    assert h.last_to(ADMIN).text == "Заявка не найдена."


@pytest.mark.asyncio
async def test_price_only_for_autoservice_and_no_ready_change_elsewhere(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(CLIENT, NICHES["drycleaning"].menu_book)
    await h.say("/price 1 8500", ADMIN)
    assert "только в автосервисе" in h.last_to(ADMIN).text
    assert (await h.db.order(1)).price is None
    await h.press("adm:ready:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>✅ Готово, можно забирать</b>"


@pytest.mark.asyncio
async def test_client_cannot_use_price(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.book(CLIENT, AUTO.menu_book)
    await h.say("/price 1 1", CLIENT)
    assert (await h.db.order(1)).price is None


@pytest.mark.asyncio
async def test_demo_visitor_prices_only_own_order(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    boris = visitor(200)
    for user in (CLIENT, boris):
        await h.say("/start", user)
        await h.press("niche:autoservice", user)
    await h.book(CLIENT, AUTO.menu_book)

    await h.say("/price 1 100", boris)
    assert h.last_to(boris).text == "Заявка не найдена."
    assert (await h.db.order(1)).price is None

    await h.say("/price 1 8500", CLIENT)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_demo_quote_saves_price_and_says_so(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    await h.say("/start", CLIENT)
    await h.press("niche:autoservice", CLIENT)
    await h.book(CLIENT, AUTO.menu_book)
    await h.press("adm:approval:1", CLIENT)
    await h.say("/note 1 8 500 ₽, замена колодок", CLIENT)
    assert "Стоимость 8 500 ₽ записана" in h.last_to(CLIENT).text
    await h.press("quote:yes:1", CLIENT)
    await h.press("adm:ready:1", CLIENT)
    sent = h.texts_to(CLIENT)
    assert "к оплате 8 500 ₽" in sent[-2] and "к оплате 8 500 ₽" in sent[-1]


def test_sheet_columns():
    assert header(NICHES["autoservice"])[-1] == "Стоимость, ₽"
    assert "Стоимость, ₽" not in header(NICHES["repair"])
    assert "Стоимость, ₽" not in header(NICHES["appliance"])
    assert len(header(NICHES["repair"])) == 11  # как в уже созданных таблицах


class FakeSheet:
    def __init__(self):
        self.rows, self.updates = [], []

    def col_values(self, _):
        return [r[0] for r in self.rows]

    def append_row(self, row):
        self.rows.append(row)

    def update(self, cell_range, values):
        self.updates.append((cell_range, values[0]))


@pytest.mark.asyncio
async def test_sheet_row_has_price_column_and_status_text(tmp_path):
    db = Database(str(tmp_path / "t.db"), "autoservice")
    await db.init()
    oid = await db.create_order(user_id=1, username=None, name="Иван", phone="+7", service_id=1, service_name="ТО",
                                device="", problem="", slot=SLOT, now=datetime(2026, 11, 3), niche="autoservice")
    await db.set_price(oid, 8500)
    await db.set_status(oid, "ready")
    exporter = SheetsExporter("", "", NICHES["autoservice"])
    exporter.enabled, exporter._ws = True, FakeSheet()

    await exporter.upsert(await db.order(oid))
    row = exporter._ws.rows[0]
    assert len(row) == len(header(NICHES["autoservice"]))
    assert row[-1] == "8500" and row[3] == "✅ Готово — к оплате 8 500 ₽"

    await exporter.upsert(await db.order(oid))
    assert exporter._ws.updates[0][0] == "A1:L1"


@pytest.mark.asyncio
async def test_price_column_added_to_old_database(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    await db.init()
    oid = await db.create_order(user_id=1, username=None, name="Иван", phone="+7", service_id=1, service_name="x",
                                device="", problem="", slot=SLOT, now=datetime(2026, 11, 3))
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE orders DROP COLUMN price")
    await Database(path).init()
    assert (await db.order(oid)).price is None
