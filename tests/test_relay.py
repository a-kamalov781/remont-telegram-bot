"""Переписка: клиент пишет в бота, сообщение приходит мастеру, мастер отвечает оттуда же."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from bot.niches import NICHES
from tests.harness import ADMIN, SLOT, make, photo, reply, visitor

ANNA = visitor(100)
BORIS = visitor(200)
REPAIR = NICHES["repair"]


async def repair(tmp_path, monkeypatch):
    return await make(tmp_path, monkeypatch)


def from_client(h, user=ADMIN):
    """Последнее сообщение мастеру с подписью о клиенте."""
    return [s for s in h.bot.sent if s.chat_id == user.id and "Сообщение от клиента" in s.text][-1]


@pytest.mark.asyncio
async def test_client_message_reaches_master_with_order_context(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.book(ANNA, REPAIR.menu_book)
    await h.say("Когда будет готово?", ANNA)

    card = from_client(h)
    assert "Когда будет готово?" in card.text
    assert "Заявка №1" in card.text and "@user100" in card.text
    assert "Reply" in card.text
    assert "Передали мастеру" in h.texts_to(ANNA)[-1]


@pytest.mark.asyncio
async def test_message_without_order_still_reaches_master(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Вы работаете в воскресенье?", ANNA)
    card = from_client(h)
    assert "Вы работаете в воскресенье?" in card.text and "Заявка" not in card.text


@pytest.mark.asyncio
async def test_open_order_is_preferred_over_finished_one(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.book(ANNA, REPAIR.menu_book)
    await h.book(ANNA, REPAIR.menu_book, slot=SLOT + timedelta(hours=2))
    await h.press("adm:done:2", ADMIN)
    await h.say("Как там мой заказ?", ANNA)
    assert "Заявка №1" in from_client(h).text  # новее закрытая №2, но открыта №1


@pytest.mark.asyncio
async def test_finished_order_is_used_when_nothing_is_open(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.book(ANNA, REPAIR.menu_book)
    await h.press("adm:done:1", ADMIN)
    await h.say("Ещё вопрос", ANNA)
    assert "Заявка №1" in from_client(h).text


@pytest.mark.asyncio
async def test_every_admin_gets_the_message_and_can_answer(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    second = visitor(778)
    h.settings.admin_ids = [ADMIN.id, second.id]
    await h.say("Вопрос", ANNA)
    card = from_client(h, second)
    await h.dp.feed_update(h.bot, reply("Ответ второго", second, card.message_id))
    assert "Ответ второго" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_master_reply_reaches_client(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Когда будет готово?", ANNA)
    await h.dp.feed_update(h.bot, reply("Завтра к обеду", ADMIN, from_client(h).message_id))

    assert h.last_to(ANNA).text == "💬 <b>Мастер:</b> Завтра к обеду"
    assert "Отправлено клиенту" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_client_can_answer_the_master_back(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Вопрос", ANNA)
    await h.dp.feed_update(h.bot, reply("Ответ", ADMIN, from_client(h).message_id))
    # Клиент отвечает через Reply на сообщение мастера: это обычное сообщение мастеру
    client_copy = h.last_to(ANNA)
    await h.dp.feed_update(h.bot, reply("Спасибо!", ANNA, client_copy.message_id))
    assert "Спасибо!" in from_client(h).text


@pytest.mark.asyncio
async def test_replies_go_to_the_right_client(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("От Анны", ANNA)
    anna_card = from_client(h)
    await h.say("От Бориса", BORIS)
    await h.dp.feed_update(h.bot, reply("Анне", ADMIN, anna_card.message_id))
    assert "Анне" in h.last_to(ANNA).text
    assert "Анне" not in h.last_to(BORIS).text


@pytest.mark.asyncio
async def test_photo_from_client_and_master_is_copied(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.dp.feed_update(h.bot, photo(ANNA))
    copy = h.last_to(ADMIN)
    assert copy.copied_from is not None and "Сообщение от клиента" in from_client(h).text

    # Ответить можно и на подпись, и на саму копию
    await h.dp.feed_update(h.bot, reply("Вижу пятно", ADMIN, copy.message_id))
    assert "Вижу пятно" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_long_text_is_copied_instead_of_cut(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("я" * 4000, ANNA)
    assert h.last_to(ADMIN).copied_from is not None
    assert len(from_client(h).text) < 1000


@pytest.mark.asyncio
async def test_client_input_is_escaped(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("<b>a & b</b>", ANNA)
    assert "&lt;b&gt;a &amp; b&lt;/b&gt;" in from_client(h).text
    await h.dp.feed_update(h.bot, reply("<i>ок</i>", ADMIN, from_client(h).message_id))
    assert "&lt;i&gt;ок&lt;/i&gt;" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_blocked_client_is_reported_to_master(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Вопрос", ANNA)
    h.bot.blocked.add(ANNA.id)
    await h.dp.feed_update(h.bot, reply("Ответ", ADMIN, from_client(h).message_id))
    assert "Не удалось доставить" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_client_is_told_when_master_is_unreachable(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    h.bot.blocked.add(ADMIN.id)
    await h.say("Вопрос", ANNA)
    assert "Не получилось передать" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_booking_steps_are_not_sent_to_master(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.book(ANNA, REPAIR.menu_book, device="iPhone 13", problem="экран")
    assert not any("Сообщение от клиента" in t for t in h.texts_to(ADMIN))


@pytest.mark.asyncio
async def test_unknown_commands_and_stale_skip_button_are_not_sent(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("/stats", ANNA)
    await h.say("Пропустить", ANNA)
    assert not any("Сообщение от клиента" in t for t in h.texts_to(ADMIN))


@pytest.mark.asyncio
async def test_admin_plain_message_gets_a_hint_and_goes_nowhere(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("просто текст", ADMIN)
    assert "Reply" in h.last_to(ADMIN).text
    assert not any("Сообщение от клиента" in s.text for s in h.bot.sent)


@pytest.mark.asyncio
async def test_admin_commands_still_work_as_a_reply(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Вопрос", ANNA)
    before = len(h.texts_to(ANNA))
    await h.dp.feed_update(h.bot, reply("/open", ADMIN, from_client(h).message_id))
    assert "Открытых заявок нет" in h.last_to(ADMIN).text
    assert len(h.texts_to(ANNA)) == before


@pytest.mark.asyncio
async def test_reply_to_a_message_without_record_is_not_delivered(tmp_path, monkeypatch):
    h = await repair(tmp_path, monkeypatch)
    await h.say("Вопрос", ANNA)
    before = len(h.texts_to(ANNA))
    await h.dp.feed_update(h.bot, reply("Куда это?", ADMIN, 999_999))
    assert len(h.texts_to(ANNA)) == before


# ---------- демо ----------

async def demo(tmp_path, monkeypatch):
    return await make(tmp_path, monkeypatch, demo_mode=True, demo_contact="@kamalovTG")


async def choose(h, user, key="drycleaning"):
    await h.say("/start", user)
    await h.press(f"niche:{key}", user)


@pytest.mark.asyncio
async def test_demo_visitor_sees_both_sides_of_the_chat(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA)
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    admin_before = len(h.texts_to(ADMIN))

    await h.say("Выведете кофе?", ANNA)
    card = from_client(h, ANNA)
    assert "Так мастер видит сообщение клиента" in card.text and "Заявка №1" in card.text
    # Вопрос посетителя демо не уходит настоящему администратору
    assert len(h.texts_to(ADMIN)) == admin_before

    await h.dp.feed_update(h.bot, reply("Да, выведем", ANNA, card.message_id))
    assert h.last_to(ANNA).text == "👤 <i>Клиент получил:</i>\n\n💬 <b>Мастер:</b> Да, выведем"


@pytest.mark.asyncio
async def test_demo_reply_works_during_booking_and_does_not_break_it(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA)
    await h.say("Вопрос", ANNA)
    card = from_client(h, ANNA)
    await h.say("/book", ANNA)
    await h.dp.feed_update(h.bot, reply("Ответ мастера", ANNA, card.message_id))
    assert "Ответ мастера" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_demo_visitor_cannot_answer_through_someone_elses_message(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA)
    await choose(h, BORIS)
    await h.say("Вопрос Анны", ANNA)
    anna_card = from_client(h, ANNA)
    anna_before = len(h.texts_to(ANNA))

    await h.dp.feed_update(h.bot, reply("Чужой ответ", BORIS, anna_card.message_id))
    assert len(h.texts_to(ANNA)) == anna_before


@pytest.mark.asyncio
async def test_demo_relay_records_expire_with_demo_orders(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await choose(h, ANNA)
    await h.say("Вопрос", ANNA)
    card = from_client(h, ANNA)
    await h.db.save_relay([(5, 5)], client_id=9, demo=False, now=datetime.now() - timedelta(days=30))

    assert await h.db.relay_target(ANNA.id, card.message_id) == (ANNA.id, True)
    await h.db.purge_demo_orders(datetime.now() + timedelta(days=1))
    assert await h.db.relay_target(ANNA.id, card.message_id) is None
    assert await h.db.relay_target(5, 5) == (9, False)
