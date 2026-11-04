"""Правки по итогам проверки глазами посетителя."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot import keyboards as kb
from bot import texts
from bot.niches import NICHES
from bot.services import profile
from bot.services.price import parse_quote
from tests.harness import ADMIN, SLOT, Sent, make, photo, reply, visitor

ANNA = visitor(100)
BORIS = visitor(200)
AUTO = NICHES["autoservice"]
DRY = NICHES["drycleaning"]


async def auto(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="autoservice")
    await h.book(ANNA, AUTO.menu_book, device="Kia Rio", problem="Скрип")
    return h


async def demo(tmp_path, monkeypatch, key="autoservice", user=ANNA):
    h = await make(tmp_path, monkeypatch, demo_mode=True, demo_contact="@kamalovTG")
    await h.say("/start", user)
    await h.press(f"niche:{key}", user)
    return h


# ---------- 1. Ввод суммы ----------

@pytest.mark.parametrize("text,expected", [
    ("8500 замена колодок", (8500, "замена колодок")),
    ("8 500 ₽, замена колодок", (8500, "замена колодок")),
    ("8 500", (8500, "")),
    ("8500р", (8500, "")),
    ("8500 рублей, колодки", (8500, "колодки")),
    ("Замена 2 колодок: 8 500 ₽", (8500, "Замена 2 колодок")),
    ("8500 работа и запчасти", (8500, "работа и запчасти")),
    ("Позвоним и обсудим", (None, "Позвоним и обсудим")),
])
def test_parse_quote(text, expected):
    assert parse_quote(text) == expected


@pytest.mark.asyncio
async def test_next_message_after_approval_button_is_the_amount(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    before = len(h.texts_to(ANNA))
    await h.press("adm:approval:1", ADMIN)

    prompt = h.last_to(ADMIN)
    assert "Введите сумму и что делаем (например: 8500 замена колодок)" in prompt.text
    assert prompt.buttons() == [("❌ Отмена", "qcancel:1")]
    assert (await h.db.order(1)).status == "new"
    assert len(h.texts_to(ANNA)) == before

    await h.say("8500 замена колодок", ADMIN)
    o = await h.db.order(1)
    assert (o.status, o.price, o.admin_note, o.quote_answer) == ("approval", 8500, "замена колодок", "")
    offer = h.last_to(ANNA)
    assert "💰 Стоимость: <b>8 500 ₽</b>" in offer.text and "💬 замена колодок" in offer.text
    assert offer.callbacks() == ["quote:yes:1", "quote:call:1"]
    assert "записана и отправлена клиенту" in h.last_to(ADMIN).text

    # Ожидание закончилось: следующее сообщение уже не сумма
    await h.say("просто текст", ADMIN)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_amount_alone_is_enough(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.say("8 500", ADMIN)
    o = await h.db.order(1)
    assert (o.price, o.admin_note) == (8500, "")
    assert h.last_to(ANNA).callbacks() == ["quote:yes:1", "quote:call:1"]
    assert "8 500 ₽" in h.last_to(ANNA).text


@pytest.mark.asyncio
async def test_text_without_amount_asks_again(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    client_before = len(h.texts_to(ANNA))
    await h.say("замена колодок", ADMIN)
    assert "Не нашёл сумму" in h.last_to(ADMIN).text
    assert h.last_to(ADMIN).callbacks() == ["qcancel:1"]
    assert (await h.db.order(1)).status == "new"
    assert len(h.texts_to(ANNA)) == client_before

    await h.say("9000 колодки", ADMIN)
    assert (await h.db.order(1)).price == 9000


@pytest.mark.asyncio
async def test_photo_while_waiting_does_not_break_input(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.dp.feed_update(h.bot, photo(ADMIN))
    assert "Не нашёл сумму" in h.last_to(ADMIN).text


@pytest.mark.asyncio
async def test_cancel_button_changes_nothing(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:diagnostics:1", ADMIN)
    await h.say("/note 1 Осмотр 30 минут", ADMIN)
    await h.press("adm:approval:1", ADMIN)
    client_before = len(h.texts_to(ANNA))

    await h.press("qcancel:1", ADMIN)
    o = await h.db.order(1)
    assert (o.status, o.price, o.admin_note) == ("diagnostics", None, "Осмотр 30 минут")
    assert "отменён" in h.last_to(ADMIN).text
    assert "adm:approval:1" in h.card(ADMIN).callbacks()
    assert len(h.texts_to(ANNA)) == client_before

    # После отмены текст сотрудника не считается суммой
    await h.say("8500", ADMIN)
    assert (await h.db.order(1)).price is None

    # Повторная отмена ничего не ломает
    await h.press("qcancel:1", ADMIN)
    assert "Этот ввод уже закрыт" in h.alerts


@pytest.mark.asyncio
async def test_other_status_button_does_not_interrupt_waiting(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.press("adm:diagnostics:1", ADMIN)
    await h.say("8500", ADMIN)
    o = await h.db.order(1)
    assert (o.status, o.price) == ("approval", 8500)


@pytest.mark.asyncio
async def test_pressing_approval_again_replaces_amount_and_asks_client_again(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.say("8500 колодки", ADMIN)
    await h.press("quote:yes:1", ANNA)
    assert (await h.db.order(1)).quote_answer == "yes"

    await h.press("adm:approval:1", ADMIN)
    await h.say("9500 колодки и диски", ADMIN)
    o = await h.db.order(1)
    assert (o.price, o.quote_answer) == (9500, "")
    assert h.last_to(ANNA).callbacks() == ["quote:yes:1", "quote:call:1"]


@pytest.mark.asyncio
async def test_note_and_price_still_work_while_waiting(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/note 1 8 500 ₽, замена колодок", ADMIN)
    o = await h.db.order(1)
    assert (o.status, o.price, o.admin_note) == ("approval", 8500, "замена колодок")
    await h.say("7000", ADMIN)  # ожидание закрыто
    assert (await h.db.order(1)).price == 8500

    await h.press("adm:approval:1", ADMIN)
    await h.say("/price 1 7000", ADMIN)
    await h.say("6000", ADMIN)
    assert (await h.db.order(1)).price == 7000


@pytest.mark.asyncio
async def test_commands_and_menu_buttons_are_not_taken_for_the_amount(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.say("/open", ADMIN)
    assert "Открытые заявки" in h.last_to(ADMIN).text
    await h.say("💰 Цены", ADMIN)
    assert "Цены" in h.last_to(ADMIN).text and "Не нашёл сумму" not in h.last_to(ADMIN).text
    await h.say("8500", ADMIN)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_reply_to_client_while_waiting_goes_to_client(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.say("Когда будет готово?", ANNA)
    card = [s for s in h.bot.sent if s.chat_id == ADMIN.id and "Сообщение от клиента" in s.text][-1]
    await h.press("adm:approval:1", ADMIN)
    await h.dp.feed_update(h.bot, reply("Завтра, 1000 раз извините", ADMIN, card.message_id))
    assert "Завтра" in h.last_to(ANNA).text
    assert (await h.db.order(1)).price is None


@pytest.mark.asyncio
async def test_non_admin_cannot_start_input_in_real_bot(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ANNA)
    await h.press("qcancel:1", ANNA)
    await h.say("100", ANNA)
    assert (await h.db.order(1)).price is None


@pytest.mark.asyncio
async def test_demo_visitor_enters_amount_only_for_own_order(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await h.say("/start", BORIS)
    await h.press("niche:autoservice", BORIS)
    await h.book(ANNA, AUTO.menu_book)

    await h.press("adm:approval:1", BORIS)
    assert "Это не ваша заявка" in h.alerts
    await h.say("100", BORIS)  # обычное сообщение, не сумма
    assert (await h.db.order(1)).price is None

    await h.press("adm:approval:1", ANNA)
    await h.press("qcancel:1", BORIS)
    await h.say("8500 колодки", ANNA)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
async def test_plain_amount_outside_input_stays_a_client_message(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch)
    await h.book(ANNA, AUTO.menu_book)
    await h.say("8 500", ANNA)
    assert any("Сообщение от клиента" in t for t in h.texts_to(ANNA))
    assert (await h.db.order(1)).price is None


# ---------- 2. Валюта ----------

@pytest.mark.asyncio
async def test_amount_has_currency_everywhere_client_sees_it(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:approval:1", ADMIN)
    await h.say("8500", ADMIN)
    assert "8 500 ₽" in h.last_to(ANNA).text and "8500" not in h.last_to(ANNA).text
    await h.say("/status", ANNA)
    assert "8 500 ₽" in h.last_to(ANNA).text
    await h.press("quote:yes:1", ANNA)
    assert "8 500 ₽" in [s for s in h.bot.sent if s.chat_id == ADMIN.id][-1].text
    await h.press("adm:ready:1", ADMIN)
    assert "к оплате 8 500 ₽" in h.last_to(ANNA).text


def test_price_list_and_service_buttons_format_thousands():
    services = [{"id": 1, "name": "ТО", "description": "x", "price_from": 5000}]
    assert "от 5 000 ₽" in texts.prices(services, AUTO)
    assert kb.services_kb(services).inline_keyboard[0][0].text == "ТО — от 5 000 ₽"


# ---------- 3. Кнопка равна статусу ----------

@pytest.mark.asyncio
async def test_button_text_equals_client_status_text(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.say("/price 1 8500", ADMIN)
    await h.press("adm:in_progress:1", ADMIN)
    o = await h.db.order(1)

    labels = [b.text for row in kb.admin_card_kb(o).inline_keyboard for b in row]
    assert "▶ ✅ Готово — к оплате 8 500 ₽" in labels
    full = [b.text for row in kb.admin_status_kb(o).inline_keyboard for b in row]
    assert "✅ Готово — к оплате 8 500 ₽" in full

    await h.press("adm:ready:1", ADMIN)
    assert h.last_to(ANNA).text == "🔔 Заявка №1: <b>✅ Готово — к оплате 8 500 ₽</b>"


def test_every_preset_button_matches_status_text():
    for niche in NICHES.values():
        o = _order(niche.key)
        data = {b.callback_data: b.text for row in kb.admin_status_kb(o).inline_keyboard for b in row}
        for status in niche.all_statuses:
            assert data[f"adm:{status.code}:1"].removeprefix("✓ ") == status.text


def _order(niche_key, status="new", price=None):
    from datetime import datetime

    from bot.db import Order
    return Order(id=1, user_id=1, username=None, name="А", phone="+7", service_id=1, service_name="Услуга",
                 device="", problem="", slot=SLOT, status=status, admin_note="", created_at=datetime(2026, 1, 1),
                 reminded=False, niche=niche_key, price=price)


# ---------- 4. Заголовок карточки ----------

@pytest.mark.parametrize("status,price,title", [
    ("new", None, "🆕 <b>Новая заявка №1</b>"),
    ("done", None, "<b>Заявка №1 · Выдано</b>"),
    ("cancelled", None, "<b>Заявка №1 · Отменено</b>"),
    ("ready", 8500, "<b>Заявка №1 · Готово — к оплате 8 500 ₽</b>"),
])
def test_card_title_shows_current_status(status, price, title):
    assert texts.admin_order(_order("autoservice", status, price)).startswith(title)


@pytest.mark.asyncio
async def test_old_card_in_demo_shows_new_status(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch, key="drycleaning")
    await h.book(ANNA, DRY.menu_book)
    await h.press("adm:done:1", ANNA)
    assert any(t.startswith("<b>Заявка №1 · Выдано</b>") for t in h.texts_to(ANNA))
    assert not any(t.startswith("🆕") and "Выдано" in t for t in h.texts_to(ANNA))


# ---------- 5. Роль сотрудника ----------

@pytest.mark.parametrize("key,name,dative,genitive", [
    ("repair", "мастер", "мастеру", "мастера"),
    ("appliance", "мастер", "мастеру", "мастера"),
    ("drycleaning", "приёмщик", "приёмщику", "приёмщика"),
    ("atelier", "приёмщик", "приёмщику", "приёмщика"),
    ("autoservice", "мастер-приёмщик", "мастеру-приёмщику", "мастера-приёмщика"),
])
def test_staff_names(key, name, dative, genitive):
    niche = NICHES[key]
    assert (niche.staff_name, niche.staff_dative, niche.staff_genitive) == (name, dative, genitive)


async def _full_demo_run(h, user, niche):
    await h.say(niche.menu_book, user)
    await h.press(h.last_to(user).callbacks()[0], user)
    await h.press(f"date:{SLOT.date().isoformat()}", user)
    await h.press(f"slot:{SLOT.isoformat()}", user)
    for text in ("Анна", "8 912 345 67 89", "Шерстяное", "Описание"):
        await h.say(text, user)
    if niche.ask_address:
        await h.say("Невский пр., 10", user)
    await h.press("confirm", user)
    await h.say("Вопрос", user)
    card = [s for s in h.bot.sent if "Сообщение от клиента" in s.text][-1]
    await h.dp.feed_update(h.bot, reply("Ответ", user, card.message_id))
    await h.say("📍 Адрес и контакты", user)
    await h.say("💰 Цены", user)
    await h.say("/status", user)
    for status in niche.statuses[1:]:
        if status.approval:
            await h.press(f"adm:{status.code}:1", user)
            await h.say("8500 работа", user)
            await h.press("quote:yes:1", user)
        else:
            await h.press(f"adm:{status.code}:1", user)


def _everything_shown(h):
    shown = [s.text for s in h.bot.sent]
    for s in h.bot.sent:
        shown += [text for text, _ in s.buttons()]
    return "\n".join(shown)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["drycleaning", "atelier"])
async def test_reception_niches_never_say_master(tmp_path, monkeypatch, key):
    h = await demo(tmp_path, monkeypatch, key=key)
    await _full_demo_run(h, ANNA, NICHES[key])
    shown = _everything_shown(h).casefold()
    assert "мастер" not in shown and "приёмщик" in shown


@pytest.mark.asyncio
async def test_autoservice_always_says_master_receptionist(tmp_path, monkeypatch):
    import re

    h = await demo(tmp_path, monkeypatch, key="autoservice")
    await _full_demo_run(h, ANNA, AUTO)
    shown = _everything_shown(h)
    # Название бизнеса «Автомастер» — не роль
    shown = shown.replace("Автомастер", "")
    found = re.findall(r"[Мм]астер\w*-?\w*", shown)
    assert found and all("приёмщик" in word for word in found), found


# ---------- 6. Кнопка записи ----------

@pytest.mark.asyncio
async def test_autoservice_book_button(tmp_path, monkeypatch):
    assert AUTO.menu_book == "🚗 Записаться"
    h = await make(tmp_path, monkeypatch, niche="autoservice")
    await h.say("🚗 Записаться на диагностику", ANNA)  # старая клавиатура у тех, кто уже открывал бота
    assert h.last_to(ANNA).text == AUTO.book_prompt
    assert not any("Сообщение от клиента" in t for t in h.texts_to(ADMIN))


# ---------- 7. Профиль бота ----------

class ProfileBot:
    def __init__(self, name="старое", description="старое", short="старое", fail=False):
        self.values = {"name": name, "description": description, "short_description": short}
        self.calls = []
        self.fail = fail

    async def get_my_name(self):
        return SimpleNamespace(name=self.values["name"])

    async def get_my_description(self):
        return SimpleNamespace(description=self.values["description"])

    async def get_my_short_description(self):
        return SimpleNamespace(short_description=self.values["short_description"])

    def _set(self, **kw):
        if self.fail:
            raise TelegramAPIError(method=None, message="Too Many Requests")
        self.calls += list(kw)
        self.values.update(kw)

    async def set_my_name(self, name):
        self._set(name=name)

    async def set_my_description(self, description):
        self._set(description=description)

    async def set_my_short_description(self, short_description):
        self._set(short_description=short_description)


def _settings(**kw):
    from datetime import time

    from bot.config import Settings
    return Settings(bot_token="1:x", admin_ids=[1], work_start=time(10, 0), work_end=time(20, 0), _env_file=None, **kw)


@pytest.mark.asyncio
async def test_demo_profile_is_neutral():
    bot = ProfileBot()
    await profile.sync_profile(bot, _settings(demo_mode=True, business_name="«Ремонт Плюс»"))
    assert bot.values["name"] == "Демо: бот записи и статусов для сервиса"
    for word in ("химчистки", "ателье", "автосервисы", "ремонт"):
        assert word in bot.values["description"]
    assert "Ремонт Плюс" not in bot.values["description"]
    assert set(bot.calls) == {"name", "description", "short_description"}


@pytest.mark.asyncio
async def test_real_profile_comes_from_settings():
    bot = ProfileBot()
    await profile.sync_profile(bot, _settings(business_name="«Химчистка на Литейном»",
                                              business_address="СПб, Литейный пр., 10", business_phone="+7 812"))
    assert bot.values["name"] == "Химчистка на Литейном"
    assert "СПб, Литейный пр., 10" in bot.values["description"] and "10:00–20:00" in bot.values["description"]
    assert "СПб, Литейный пр., 10" in bot.values["short_description"]


@pytest.mark.asyncio
async def test_profile_is_not_rewritten_without_changes():
    settings = _settings(demo_mode=True)
    wanted = profile.profile_for(settings)
    bot = ProfileBot(wanted.name, wanted.description, wanted.short_description)
    await profile.sync_profile(bot, settings)
    assert bot.calls == []


@pytest.mark.asyncio
async def test_empty_settings_do_not_wipe_profile_and_never_use_fictional_details():
    bot = ProfileBot()
    await profile.sync_profile(bot, _settings(niche="drycleaning"))
    assert bot.values == {"name": "старое", "description": "старое", "short_description": "старое"}
    assert bot.calls == []


@pytest.mark.asyncio
async def test_profile_error_does_not_stop_the_bot():
    await profile.sync_profile(ProfileBot(fail=True), _settings(demo_mode=True))


def test_profile_texts_fit_telegram_limits():
    p = profile.profile_for(_settings(demo_mode=True))
    assert len(p.name) <= profile.NAME_LIMIT
    assert len(p.description) <= profile.DESCRIPTION_LIMIT
    assert len(p.short_description) <= profile.SHORT_DESCRIPTION_LIMIT


# ---------- 8. Служебные сообщения ----------

@pytest.mark.asyncio
async def test_no_filler_messages_and_keyboards_come_with_meaningful_ones(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, DRY.menu_book)
    sent = h.texts_to(ANNA)
    assert not any(t in ("Секунду…", "Главное меню:") for t in sent)

    summary = next(s for s in h.bot.sent if "Проверьте заявку" in s.text)
    assert isinstance(summary.markup, ReplyKeyboardRemove)
    question = h.bot.sent[h.bot.sent.index(summary) + 1]
    assert question.text == "Всё верно?"

    created = next(s for s in h.bot.sent if "Вы записаны" in s.text)
    assert isinstance(created.markup, ReplyKeyboardMarkup)
    assert created.markup.keyboard[0][0].text == DRY.menu_book


@pytest.mark.asyncio
async def test_cancel_at_summary_returns_the_menu(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.say(DRY.menu_book, ANNA)
    await h.press("cancel", ANNA)
    last = h.last_to(ANNA)
    assert last.text == "Запись отменена." and isinstance(last.markup, ReplyKeyboardMarkup)


# ---------- 9. Без повторов ----------

@pytest.mark.parametrize("device,service,repeated", [
    ("пальто", "Чистка пальто", True),
    ("Пальто", "Чистка пальто", True),
    ("шерстяное пальто", "Чистка пальто", False),
    ("iPhone 13", "Замена экрана телефона", False),
    ("", "Чистка пальто", False),
])
def test_object_repeat_detection(device, service, repeated):
    assert texts._object_implied(device, service) is repeated


@pytest.mark.asyncio
async def test_implied_object_is_not_repeated(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, DRY.menu_book, device="пальто", problem="пятно на рукаве")
    o = await h.db.order(1)
    assert o.device == "пальто"  # в базе остаётся
    summary = next(s.text for s in h.bot.sent if "Проверьте заявку" in s.text)
    assert "Вещь:" not in summary and "Что сделать: пятно на рукаве" in summary
    assert "Вещь:" not in texts.admin_order(o) and "Что сделать: пятно на рукаве" in texts.admin_order(o)
    assert " · пальто" not in texts.order_status_card(o)


def test_field_labels_come_from_preset():
    assert NICHES["repair"].problem_label == "Что случилось"
    assert NICHES["appliance"].problem_label == "Что случилось"
    assert AUTO.problem_label == "Что случилось"
    assert DRY.problem_label == "Что сделать"
    assert NICHES["atelier"].problem_label == "Пожелания"


def test_empty_fields_are_not_shown():
    card = texts.admin_order(_order("drycleaning"))
    assert "—" not in card and "Вещь" not in card and "Что сделать" not in card


# ---------- 10. Компактная карточка ----------

@pytest.mark.parametrize("key", sorted(NICHES))
def test_card_has_next_step_more_and_cancel(key):
    niche = NICHES[key]
    o = _order(key)
    rows = kb.admin_card_kb(o).inline_keyboard
    assert len(rows) == 2
    assert rows[0][0].text == f"▶ {niche.statuses[1].text}"
    assert [b.text for b in rows[1]] == ["Ещё статусы", "❌ Отменить"]


def test_card_after_final_and_cancel_has_no_next_or_cancel():
    for status in ("done", "cancelled"):
        rows = kb.admin_card_kb(_order("drycleaning", status)).inline_keyboard
        assert [[b.text for b in row] for row in rows] == [["Ещё статусы"]]


@pytest.mark.parametrize("key", sorted(NICHES))
def test_compact_buttons_fit_a_phone(key):
    """На ширине 390 px в кнопке помещается около 40 символов, в половинной строке около 18."""
    niche = NICHES[key]
    for status in niche.statuses:
        o = _order(key, status.code, price=8500)
        rows = kb.admin_card_kb(o).inline_keyboard
        assert len(rows) <= 2
        for row in rows:
            assert all(len(b.text) <= (40 if len(row) == 1 else 18) for b in row), [b.text for b in row]


@pytest.mark.asyncio
async def test_more_statuses_expand_and_collapse(tmp_path, monkeypatch):
    h = await auto(tmp_path, monkeypatch)
    await h.press("adm:menu:1", ADMIN)
    expanded = h.markups[-1]
    assert isinstance(expanded, Sent)
    assert expanded.callbacks() == [f"adm:{s.code}:1" for s in AUTO.all_statuses] + ["adm:less:1"]
    assert expanded.buttons()[0][0] == "✓ 📅 Вы записаны"

    await h.press("adm:less:1", ADMIN)
    assert h.markups[-1].callbacks() == ["adm:diagnostics:1", "adm:menu:1", "adm:cancelled:1"]
    assert (await h.db.order(1)).status == "new"


@pytest.mark.asyncio
async def test_next_button_walks_the_chain_in_demo(tmp_path, monkeypatch):
    h = await demo(tmp_path, monkeypatch, key="drycleaning")
    await h.book(ANNA, DRY.menu_book)
    for status in DRY.statuses[1:]:
        step = h.card(ANNA).callbacks()[0]
        assert step == f"adm:{status.code}:1"
        await h.press(step, ANNA)
    assert "Это демо" in h.last_to(ANNA).text
