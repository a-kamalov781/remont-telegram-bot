"""Демо-режим: посетитель выбирает нишу и становится клиентом и мастером своей заявки."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bot.niches import NICHES
from tests.harness import ADMIN, SLOT, make, visitor

ANNA = visitor(100)
BORIS = visitor(200)
CONTACT = "@kamalovTG"


async def demo(tmp_path, monkeypatch):
    return await make(tmp_path, monkeypatch, demo_mode=True, demo_contact=CONTACT)


async def choose(h, user, key):
    await h.say("/start", user)
    await h.press(f"niche:{key}", user)


@pytest.mark.asyncio
async def test_start_offers_every_niche_and_saves_choice(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await h.say("/start", ANNA)
    picker = h.last_to(ANNA)
    assert "Какой у вас бизнес?" in picker.text
    assert picker.callbacks() == [f"niche:{k}" for k in NICHES]

    await h.press("niche:drycleaning", ANNA)
    assert await h.db.demo_niche(ANNA.id) == "drycleaning"
    assert h.bot.sent[-2].markup.keyboard[0][0].text == "🧺 Сдать вещь в чистку"

    # Выбор живёт отдельно у каждого посетителя
    assert await h.db.demo_niche(BORIS.id) is None
    await h.say("/start", ANNA)
    assert "«Белый Лист»" in h.texts_to(ANNA)[-1]


@pytest.mark.asyncio
async def test_niche_command_changes_choice_and_resets_booking(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.say(NICHES["drycleaning"].menu_book, ANNA)

    await h.say("/niche", ANNA)
    assert "Какой у вас бизнес?" in h.texts_to(ANNA)[-1]
    await h.press("niche:autoservice", ANNA)
    assert await h.db.demo_niche(ANNA.id) == "autoservice"

    await h.say("/book", ANNA)
    names = [text for text, _ in h.last_to(ANNA).buttons()]
    assert any("Шиномонтаж" in n for n in names) and not any("пальто" in n for n in names)


@pytest.mark.asyncio
async def test_unknown_niche_callback_is_rejected(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await h.press("niche:пекарня", ANNA)
    assert await h.db.demo_niche(ANNA.id) is None


@pytest.mark.asyncio
async def test_anything_before_choosing_shows_the_picker(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await h.say("💰 Цены", ANNA)
    assert "Какой у вас бизнес?" in h.texts_to(ANNA)[-1]
    assert (await h.db.demo_stats())["visitors"] == 1


@pytest.mark.asyncio
async def test_prices_come_from_chosen_niche(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "atelier")
    await h.say("💰 Цены", ANNA)
    assert "Укоротить брюки" in h.texts_to(ANNA)[-1]


@pytest.mark.asyncio
async def test_visitor_receives_master_card_of_own_order(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    admin_messages = len(h.texts_to(ADMIN))
    await h.book(ANNA, NICHES["drycleaning"].menu_book, device="Пальто")

    card = h.last_to(ANNA)
    assert "Новая заявка №1" in card.text
    assert "👆 Так заявку видит приёмщик. Нажмите статус — и посмотрите, что получит клиент." in card.text
    assert card.callbacks() == ["adm:assessment:1", "adm:menu:1", "adm:cancelled:1"]
    # Заявки посетителей не засоряют личку администратора
    assert len(h.texts_to(ADMIN)) == admin_messages

    o = await h.db.order(1)
    assert o.demo is True and o.niche == "drycleaning" and o.user_id == ANNA.id


@pytest.mark.asyncio
async def test_reminder_preview_comes_before_master_card(tmp_path, monkeypatch):
    from bot import texts

    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "appliance")
    await h.book(ANNA, NICHES["appliance"].menu_book, address="Невский пр., 10, кв. 5")
    sent = h.texts_to(ANNA)
    o = await h.db.order(1)
    assert sent[-2].startswith("⏰ <b>Так выглядит напоминание за 2 часа до визита</b>")
    assert texts.reminder(o, h.settings) in sent[-2]  # текст настоящего напоминания
    assert "приедет мастер" in sent[-2] and "Невский пр., 10" in sent[-2]
    assert "Новая заявка №1" in sent[-1]


@pytest.mark.asyncio
async def test_reminder_preview_only_in_demo(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    assert not any("Так выглядит напоминание" in s.text for s in h.bot.sent)


@pytest.mark.parametrize("minutes,expected", [
    (120, "2 часа"), (60, "час"), (300, "5 часов"), (90, "90 минут"), (1320, "22 часа"), (660, "11 часов"),
])
def test_reminder_period_wording(minutes, expected):
    from bot.texts import _remind_period

    assert _remind_period(minutes) == expected


@pytest.mark.asyncio
async def test_full_scenario_ends_with_sales_message(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)

    for code in ("assessment", "cleaning", "ready"):
        await h.press(f"adm:{code}:1", ANNA)
        sent = h.texts_to(ANNA)
        assert NICHES["drycleaning"].status_text(code) in sent[-2]  # что получил клиент
        assert sent[-2].startswith("👤 <i>Клиент получил:</i>")
        assert h.last_to(ANNA).callbacks()  # следующая карточка внизу чата

    await h.press("adm:done:1", ANNA)
    final = h.last_to(ANNA)
    assert "Это демо. Такой бот под ваш бизнес — 2 дня, ваше название, услуги и цены." in final.text
    assert "Написать разработчику: @kamalovTG" in final.text
    assert final.buttons() == []
    assert (await h.db.order(1)).status == "done"


@pytest.mark.asyncio
async def test_visitor_cannot_touch_someone_elses_order(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "autoservice")
    await h.book(ANNA, NICHES["autoservice"].menu_book)
    await choose(h, BORIS, "autoservice")
    anna_messages = len(h.texts_to(ANNA))

    await h.press("adm:done:1", BORIS)
    assert "Это не ваша заявка" in h.alerts
    assert (await h.db.order(1)).status == "new"

    await h.say("/order 1", BORIS)
    assert h.texts_to(BORIS)[-1] == "Заявка не найдена."
    await h.say("/note 1 Взлом", BORIS)
    assert h.texts_to(BORIS)[-1] == "Заявка не найдена."
    assert (await h.db.order(1)).admin_note == ""

    await h.say("/status", BORIS)
    assert "№1" not in h.texts_to(BORIS)[-1]
    assert len(h.texts_to(ANNA)) == anna_messages


@pytest.mark.asyncio
async def test_visitor_cannot_touch_real_orders_or_use_admin_commands(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    oid = await h.db.create_order(user_id=ANNA.id, username=None, name="Настоящий", phone="+7 (900) 000-00-00",
                                  service_id=1, service_name="Диагностика", device="", problem="",
                                  slot=SLOT, now=datetime.now())
    await choose(h, ANNA, "repair")

    # Даже своя настоящая заявка не становится демо-заявкой
    await h.press(f"adm:done:{oid}", ANNA)
    assert (await h.db.order(oid)).status == "new"

    await h.say("/stats", ANNA)
    await h.say("/block 2030-01-01 12:00", ANNA)
    assert not any("Демо" in t or "закрыт" in t for t in h.texts_to(ANNA))


@pytest.mark.asyncio
async def test_visitors_do_not_take_each_others_slots(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await choose(h, BORIS, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.book(BORIS, NICHES["drycleaning"].menu_book)  # тот же час и тот же телефон

    assert (await h.db.order(1)).user_id == ANNA.id
    assert (await h.db.order(2)).user_id == BORIS.id
    assert not await h.db.slot_is_free(SLOT, ANNA.id)
    # Настоящая запись на это время демо-заявками не занята
    assert await h.db.slot_is_free(SLOT)


@pytest.mark.asyncio
async def test_autoservice_quote_buttons_in_demo(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "autoservice")
    await h.book(ANNA, NICHES["autoservice"].menu_book, device="Kia Rio, А123ВС 178")

    await h.press("adm:diagnostics:1", ANNA)
    await h.press("adm:approval:1", ANNA)
    card = h.last_to(ANNA)
    assert "Введите сумму и что делаем" in card.text and card.callbacks() == ["qcancel:1"]

    await h.say("8 500 ₽, замена колодок", ANNA)
    sent = h.bot.sent
    offer = sent[-2]
    assert offer.buttons() == [("✅ Согласен", "quote:yes:1"), ("📞 Перезвоните мне", "quote:call:1")]
    assert "8 500 ₽" in offer.text
    assert "Нажмите за клиента" in sent[-1].text

    await h.press("quote:yes:1", ANNA)
    answer = h.last_to(ANNA)
    assert "Клиент согласен" in answer.text and "Так мастеру-приёмщику приходит ответ" in answer.text
    assert "adm:waiting_parts:1" in answer.callbacks()

    for code in ("waiting_parts", "in_progress", "ready", "done"):
        await h.press(f"adm:{code}:1", ANNA)
    assert CONTACT in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_quote_buttons_absent_in_other_demo_niches(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.say("/note 1 1 500 ₽", ANNA)
    assert all(not s.callbacks() or not s.callbacks()[0].startswith("quote:") for s in h.bot.sent)


@pytest.mark.asyncio
async def test_appliance_demo_asks_address(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "appliance")
    await h.book(ANNA, NICHES["appliance"].menu_book, address="Невский пр., 10, кв. 5")
    assert (await h.db.order(1)).address == "Невский пр., 10, кв. 5"
    assert "Невский пр., 10" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_old_orders_expire_but_analytics_and_real_orders_stay(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    real = await h.db.create_order(user_id=5, username=None, name="Настоящий", phone="+7 (900) 000-00-00",
                                   service_id=1, service_name="Диагностика", device="", problem="",
                                   slot=SLOT, now=datetime.now() - timedelta(days=30))

    # Младше 7 дней — остаётся
    assert await h.db.purge_demo_orders(datetime.now() - timedelta(days=7)) == 0
    assert await h.db.order(1) is not None

    assert await h.db.purge_demo_orders(datetime.now() + timedelta(days=1)) == 1
    assert await h.db.order(1) is None
    assert await h.db.order(real) is not None
    assert (await h.db.demo_stats())["booked"] == 1


@pytest.mark.asyncio
async def test_reminders_skip_demo_orders(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    assert await h.db.due_reminders(SLOT - timedelta(minutes=30), 120) == []


@pytest.mark.asyncio
async def test_stats_show_interest_analytics_without_admins(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.press("adm:done:1", ANNA)
    await choose(h, BORIS, "autoservice")
    await h.say("/start", visitor(300))  # зашёл и ничего не выбрал
    await choose(h, ADMIN, "atelier")  # проверка владельца не считается

    await h.say("/stats", ADMIN)
    report = h.texts_to(ADMIN)[-1]
    assert "Зашли: <b>3</b>" in report
    assert "Выбрали нишу: <b>2</b>" in report
    assert "Записались: <b>1</b>" in report
    assert "Дошли до конца: <b>1</b>" in report
    assert "Химчистка: 1 / 1 / 1" in report
    assert "Автосервис: 1 / 0 / 0" in report
    assert "Ателье" not in report


@pytest.mark.asyncio
async def test_finishing_twice_counts_one_person(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.press("adm:done:1", ANNA)
    await h.press("adm:ready:1", ANNA)
    await h.press("adm:done:1", ANNA)
    assert (await h.db.demo_stats())["finished"] == 1


@pytest.mark.asyncio
async def test_admin_commands_and_own_demo_order_work_for_admin(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ADMIN, "drycleaning")
    await h.book(ADMIN, NICHES["drycleaning"].menu_book)
    assert "Новая заявка №1" in h.last_to(ADMIN).text

    await h.press("adm:done:1", ADMIN)
    assert CONTACT in h.last_to(ADMIN).text

    await h.say("/open", ADMIN)
    assert "Открытых заявок нет" in h.texts_to(ADMIN)[-1]

    # Администратор по-прежнему управляет любой заявкой
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.press("adm:cleaning:2", ADMIN)
    assert (await h.db.order(2)).status == "cleaning"


@pytest.mark.asyncio
async def test_demo_contact_is_optional(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    await choose(h, ANNA, "drycleaning")
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    await h.press("adm:done:1", ANNA)
    assert "Написать разработчику" not in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_demo_router_is_inert_without_demo_mode(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="atelier")
    await h.say("/start", ANNA)
    assert "Какой у вас бизнес?" not in h.texts_to(ANNA)[-1]
    assert "«Золотая Игла»" in h.texts_to(ANNA)[-1]
    await h.press("niche:drycleaning", ANNA)
    assert await h.db.demo_niche(ANNA.id) is None
