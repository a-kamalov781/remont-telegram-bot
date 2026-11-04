"""Демо: карточка заявки одна и меняется на месте, новая внизу — только если старая ушла далеко вверх."""
from __future__ import annotations

import pytest

from bot.niches import NICHES
from bot.services.notify import CARD_MAX_AGE
from tests.harness import ADMIN, make, visitor

ANNA = visitor(100)
AUTO = NICHES["autoservice"]
DRY = NICHES["drycleaning"]


async def demo(tmp_path, monkeypatch, key="drycleaning"):
    h = await make(tmp_path, monkeypatch, demo_mode=True, demo_contact="@kamalovTG")
    await h.say("/start", ANNA)
    await h.press(f"niche:{key}", ANNA)
    await h.book(ANNA, NICHES[key].menu_book)
    return h


def cards(h, user=ANNA):
    return [s for s in h.bot.sent if s.chat_id == user.id and not s.deleted
            and any(data.startswith("adm:") for data in s.callbacks())]


def client_views(h, user=ANNA):
    return [t for t in h.texts_to(user) if t.startswith("👤 <i>Клиент получил:</i>")]


@pytest.mark.asyncio
async def test_card_is_edited_in_place_and_client_message_stays_separate(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    assert card.text.startswith("🆕 <b>Новая заявка №1</b>")

    for count, status in enumerate(DRY.statuses[1:-1], start=1):
        await h.press(card.callbacks()[0], ANNA)
        assert cards(h) == [card]
        title = status.text.split(" ", 1)[1]
        assert card.text.startswith(f"<b>Заявка №1 · {title}</b>")
        assert "Чистка" in card.text
        assert len(client_views(h)) == count
        assert status.text in client_views(h)[-1]
        assert h.bot.edits == count
    assert not any(s.deleted for s in h.bot.sent)


@pytest.mark.asyncio
async def test_final_status_edits_card_without_buttons_and_offer_comes_after(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    await h.press("adm:done:1", ANNA)
    assert card.text.startswith("<b>Заявка №1 · Выдано</b>") and card.buttons() == []
    assert cards(h) == []
    assert "Это демо" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_cancel_status_edits_card_without_buttons(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    await h.press("adm:cancelled:1", ANNA)
    assert card.text.startswith("<b>Заявка №1 · Отменено</b>") and card.buttons() == []


@pytest.mark.asyncio
async def test_card_stays_up_to_the_limit(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    h.notifier.note_activity(ANNA.id, CARD_MAX_AGE - 1)  # статус добавит ещё одно сообщение клиента
    await h.press("adm:assessment:1", ANNA)
    assert h.card(ANNA) is card


@pytest.mark.asyncio
async def test_new_card_at_the_bottom_when_old_one_went_up(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    h.notifier.note_activity(ANNA.id, CARD_MAX_AGE + 1)
    await h.press("adm:assessment:1", ANNA)

    assert old.deleted is True
    new = h.card(ANNA)
    assert new is h.last_to(ANNA)
    assert new.text.startswith("<b>Заявка №1 · Вещь на оценке</b>")
    assert cards(h) == [new]

    # Счёт начинается заново: следующая смена статуса снова правит на месте
    await h.press("adm:cleaning:1", ANNA)
    assert h.card(ANNA) is new


@pytest.mark.asyncio
async def test_chat_messages_age_the_card(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    for i in range(6):
        await h.say(f"Вопрос {i}", ANNA)
    await h.press("adm:assessment:1", ANNA)
    assert old.deleted is True and h.card(ANNA) is h.last_to(ANNA)


@pytest.mark.asyncio
async def test_old_message_that_cannot_be_deleted_loses_its_buttons(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    h.bot.undeletable = True
    h.notifier.note_activity(ANNA.id, CARD_MAX_AGE + 1)
    await h.press("adm:assessment:1", ANNA)
    assert old.deleted is False and old.buttons() == []
    assert len(cards(h)) == 1


@pytest.mark.asyncio
async def test_card_that_cannot_be_edited_is_sent_anew(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    h.bot.uneditable = True
    await h.press("adm:assessment:1", ANNA)
    new = h.card(ANNA)
    assert new is not old and old.deleted is True
    assert new.text.startswith("<b>Заявка №1 · Вещь на оценке</b>")


@pytest.mark.asyncio
async def test_old_card_stays_when_the_new_one_cannot_be_sent(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    o = await h.db.order(1)
    h.bot.blocked.add(ANNA.id)
    await h.notifier.show_card(o, "новая", old.markup, force_new=True)
    assert old.deleted is False


@pytest.mark.asyncio
async def test_expanding_statuses_keeps_one_card(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    await h.press("adm:menu:1", ANNA)
    assert cards(h) == [card] and "adm:less:1" in card.callbacks()
    await h.press("adm:assessment:1", ANNA)
    assert cards(h) == [card] and "adm:less:1" not in card.callbacks()


@pytest.mark.asyncio
async def test_order_command_moves_card_down(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    old = h.card(ANNA)
    await h.say("/order 1", ANNA)
    assert old.deleted is True and cards(h) == [h.last_to(ANNA)]


@pytest.mark.asyncio
async def test_note_edits_card_and_client_gets_the_text(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    await h.say("/note 1 Будет готово завтра", ANNA)
    assert cards(h) == [card]
    assert "Будет готово завтра" in client_views(h)[-1]


@pytest.mark.asyncio
async def test_quote_flow_keeps_one_card(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch, key="autoservice")
    card = h.card(ANNA)
    await h.press("adm:approval:1", ANNA)
    assert cards(h) == [card]
    await h.say("8500 колодки", ANNA)
    assert cards(h) == [card]
    assert card.text.startswith("<b>Заявка №1 · Согласование стоимости</b>") and "Ждём ответ клиента" in card.text
    assert "Нажмите за клиента" in h.last_to(ANNA).text

    # Сообщений накопилось больше порога: карточка уходит вниз, под ответ клиента
    await h.press("quote:yes:1", ANNA)
    new = h.card(ANNA)
    assert card.deleted is True and cards(h) == [new] and new is h.last_to(ANNA)
    assert "Клиент ответил" in new.text and "8 500 ₽" in new.text
    assert any("Клиент согласен" in t for t in h.texts_to(ANNA))  # ответ клиента отдельным сообщением

    await h.press("adm:waiting_parts:1", ANNA)
    assert cards(h) == [new]
    assert any("Клиент согласен" in t for t in h.texts_to(ANNA))


def test_card_threshold_is_four_messages():
    assert CARD_MAX_AGE == 4


@pytest.mark.asyncio
async def test_each_order_has_its_own_card(tmp_path, monkeypatch):
    from tests.harness import SLOT
    from datetime import timedelta

    h = await demo(tmp_path, monkeypatch)
    first = h.card(ANNA)
    await h.book(ANNA, DRY.menu_book, slot=SLOT + timedelta(hours=2))
    second = h.card(ANNA)
    assert second is not first and first.deleted is False

    # Запись заняла много сообщений, поэтому карточка №1 приходит заново вниз. Карточку №2 это не трогает
    await h.press("adm:assessment:1", ANNA)
    assert h.last_to(ANNA).text.startswith("<b>Заявка №1 · Вещь на оценке</b>")
    assert first.deleted is True and second.deleted is False
    assert second.text.startswith("🆕 <b>Новая заявка №2</b>")


@pytest.mark.asyncio
async def test_visitors_cards_are_independent(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    boris = visitor(200)
    await h.say("/start", boris)
    await h.press("niche:drycleaning", boris)
    await h.book(boris, DRY.menu_book)
    anna_card, boris_card = h.card(ANNA), h.card(boris)
    await h.press("adm:assessment:2", boris)
    assert anna_card.text.startswith("🆕") and boris_card.text.startswith("<b>Заявка №2")


@pytest.mark.asyncio
async def test_admin_pressing_visitor_order_updates_visitor_card(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    await h.press("adm:assessment:1", ADMIN)
    assert (await h.db.order(1)).status == "assessment"
    assert card.text.startswith("<b>Заявка №1 · Вещь на оценке</b>")
    assert not any(key[0] == ADMIN.id for key in h.notifier._cards)


@pytest.mark.asyncio
async def test_card_is_recognised_after_restart(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    card = h.card(ANNA)
    h.notifier._cards.clear()
    await h.press("adm:assessment:1", ANNA)
    assert cards(h) == [card]
    assert card.text.startswith("<b>Заявка №1 · Вещь на оценке</b>")


@pytest.mark.asyncio
async def test_real_bot_does_not_use_demo_cards(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, DRY.menu_book)
    await h.press("adm:assessment:1", ADMIN)
    assert not any(s.deleted for s in h.bot.sent)
    assert h.notifier._cards == {}
