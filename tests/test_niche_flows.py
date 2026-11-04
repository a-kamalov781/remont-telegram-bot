"""Сценарии записи через Dispatcher в обычном режиме для других ниш."""
from __future__ import annotations

import pytest

from bot.niches import NICHES
from tests.harness import ADMIN, SLOT, make, visitor

CLIENT = visitor()


@pytest.mark.asyncio
async def test_drycleaning_booking_flow(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    niche = NICHES["drycleaning"]

    await h.say("/start", CLIENT)
    assert "«Белый Лист»" in h.texts_to(CLIENT)[-1]
    assert h.bot.sent[-2].markup.keyboard[0][0].text == "🧺 Сдать вещь в чистку"

    await h.book(CLIENT, niche.menu_book, device="Пальто", problem="Пятно от кофе")
    sent = "\n".join(h.texts_to(CLIENT))
    assert niche.object_prompt in sent and niche.problem_prompt in sent
    assert "Какое устройство" not in sent
    assert "Вещь: Пальто" in sent and "Что сделать: Пятно от кофе" in sent
    assert "Вы записаны в <b>«Белый Лист»</b>" in sent

    o = await h.db.order(1)
    assert (o.niche, o.demo, o.slot, o.status, o.service_name) == ("drycleaning", False, SLOT, "new", "Чистка пальто")
    assert not await h.db.slot_is_free(SLOT)

    # Мастеру — карточка с кнопками статусов этой ниши, посетителю карточка не приходит
    card = h.last_to(ADMIN)
    assert "Новая заявка №1" in card.text
    assert "adm:assessment:1" in card.callbacks() and "adm:cancelled:1" in card.callbacks()
    assert not any("Новая заявка" in t for t in h.texts_to(CLIENT))

    for code in ("assessment", "cleaning", "ready"):
        await h.press(f"adm:{code}:1", ADMIN)
        assert h.last_to(CLIENT).text == f"🔔 Заявка №1: <b>{niche.status_text(code)}</b>"

    await h.say("🔎 Статус моего заказа", CLIENT)
    assert "✅ Готово, можно забирать" in h.texts_to(CLIENT)[-1]

    # Приняли вещь — время снова свободно, как и в ремонте после приёма устройства
    assert await h.db.slot_is_free(SLOT)
    await h.press("adm:done:1", ADMIN)
    assert not any("Это демо" in t for t in h.texts_to(CLIENT))


@pytest.mark.asyncio
async def test_autoservice_booking_and_quote_approval(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="autoservice")
    niche = NICHES["autoservice"]

    await h.book(CLIENT, niche.menu_book, device="Kia Rio, А123ВС 178", problem="Стук")
    assert "Марка, модель, госномер" in "\n".join(h.texts_to(CLIENT))
    assert (await h.db.order(1)).device == "Kia Rio, А123ВС 178"

    # Вход в согласование: мастеру подсказка, клиенту статус без кнопок
    await h.press("adm:approval:1", ADMIN)
    assert h.last_to(CLIENT).text == "🔔 Заявка №1: <b>💰 Согласование стоимости</b>"
    assert h.last_to(CLIENT).buttons() == []
    assert "/note 1" in h.last_to(ADMIN).text

    # Сумма через /note — клиенту приходят кнопки
    await h.say("/note 1 8 500 ₽, замена колодок", ADMIN)
    offer = h.last_to(CLIENT)
    assert "8 500 ₽" in offer.text and "Согласны" in offer.text
    assert offer.buttons() == [("✅ Согласен", "quote:yes:1"), ("📞 Перезвоните мне", "quote:call:1")]

    # Ответ клиента приходит мастеру
    await h.press("quote:yes:1", CLIENT)
    assert "Клиент согласен" in h.last_to(ADMIN).text
    assert (await h.db.order(1)).quote_answer == "yes"

    # Повторное нажатие не шлёт мастеру второй ответ
    before = len(h.texts_to(ADMIN))
    await h.press("quote:call:1", CLIENT)
    assert len(h.texts_to(ADMIN)) == before
    assert (await h.db.order(1)).quote_answer == "yes"


@pytest.mark.asyncio
async def test_quote_answer_call_back_and_stranger_is_rejected(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="autoservice")
    await h.book(CLIENT, NICHES["autoservice"].menu_book)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/note 1 12 000 ₽", ADMIN)

    stranger = visitor(200)
    before = len(h.texts_to(ADMIN))
    await h.press("quote:yes:1", stranger)
    assert len(h.texts_to(ADMIN)) == before
    assert (await h.db.order(1)).quote_answer == ""

    await h.press("quote:call:1", CLIENT)
    assert "просит перезвонить" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_quote_buttons_do_not_appear_outside_approval(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="autoservice")
    await h.book(CLIENT, NICHES["autoservice"].menu_book)
    await h.press("adm:diagnostics:1", ADMIN)
    await h.say("/note 1 Смотрим подвеску", ADMIN)
    assert h.last_to(CLIENT).buttons() == []

    # Прежний комментарий не становится суммой при входе в согласование
    await h.press("adm:approval:1", ADMIN)
    assert h.last_to(CLIENT).buttons() == []
    assert (await h.db.order(1)).admin_note == ""


@pytest.mark.asyncio
async def test_appliance_asks_for_address(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="appliance")
    niche = NICHES["appliance"]
    await h.book(CLIENT, niche.menu_book, device="Стиральная машина", problem="Не сливает",
                 address="Невский пр., 10, кв. 5")
    sent = "\n".join(h.texts_to(CLIENT))
    assert niche.address_prompt in sent and "Адрес: Невский пр., 10, кв. 5" in sent
    assert "мастер приедет по адресу" in sent

    o = await h.db.order(1)
    assert o.address == "Невский пр., 10, кв. 5"
    assert "Невский пр., 10, кв. 5" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_appliance_rejects_too_short_address(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="appliance")
    await h.say(NICHES["appliance"].menu_book, CLIENT)
    await h.press(h.last_to(CLIENT).callbacks()[0], CLIENT)
    await h.press(f"date:{SLOT.date().isoformat()}", CLIENT)
    await h.press(f"slot:{SLOT.isoformat()}", CLIENT)
    for answer in ("Анна", "8 912 345 67 89", "Плита", "Не греет", "дом"):
        await h.say(answer, CLIENT)
    assert "от 5 до 200" in h.texts_to(CLIENT)[-1]


@pytest.mark.asyncio
async def test_niche_slot_minutes_used_unless_env_overrides(tmp_path, monkeypatch):
    from bot.handlers.client import _cfg

    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    assert _cfg(h.settings, NICHES["drycleaning"]).slot_minutes == 30
    h.settings.slot_minutes = 45
    assert _cfg(h.settings, NICHES["drycleaning"]).slot_minutes == 45
    h.settings.demo_mode = True
    assert _cfg(h.settings, NICHES["appliance"]).slot_minutes == 120


@pytest.mark.asyncio
async def test_user_input_is_escaped_in_html_messages(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="repair")
    await h.book(CLIENT, NICHES["repair"].menu_book, device="<b>iPhone", problem="a & b")
    sent = "\n".join(h.texts_to(CLIENT))
    assert "&lt;b&gt;iPhone" in sent and "a &amp; b" in sent
    assert "&lt;b&gt;iPhone" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_move_keeps_status_valid_for_niche_without_confirmed(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(CLIENT, NICHES["drycleaning"].menu_book)
    await h.say(f"/move 1 {SLOT.date().isoformat()} 15:00", ADMIN)
    o = await h.db.order(1)
    assert o.slot.hour == 15 and o.status == "new"
    assert "15:00" in h.last_to(CLIENT).text
