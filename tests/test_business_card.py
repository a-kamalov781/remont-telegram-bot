"""Клиент всегда понимает, куда записывается: карточка бизнеса, ссылка на карту, заголовки шагов, роль в демо."""
from __future__ import annotations

import pytest

from bot import texts
from bot.niches import NICHES
from scripts.setup_client import ABOUT_LIMIT, Client, checklist, env_block, main, problems, setabouttext_text
from tests.harness import SLOT, make, visitor

ANNA = visitor()
ADDRESS = "Санкт-Петербург, Литейный пр., 10"
MAP_URL = ("https://yandex.ru/maps/?text=%D0%A1%D0%B0%D0%BD%D0%BA%D1%82-%D0%9F%D0%B5%D1%82%D0%B5%D1%80%D0%B1%D1%83%D1%80%D0%B3"
           "%2C%20%D0%9B%D0%B8%D1%82%D0%B5%D0%B9%D0%BD%D1%8B%D0%B9%20%D0%BF%D1%80.%2C%2010")
LINK = f'<a href="{MAP_URL}">📍 Открыть на карте</a>'


async def client_bot(tmp_path, monkeypatch, niche="drycleaning"):
    h = await make(tmp_path, monkeypatch, niche=niche)
    h.settings.business_name = "«Химчистка на Литейном»"
    h.settings.business_address = ADDRESS
    h.settings.business_phone = "+7 (812) 123-45-67"
    return h


def test_map_url_is_encoded():
    assert texts.map_url(ADDRESS) == MAP_URL
    assert "&" not in texts.map_url("Москва, ул. А&Б, 1")


def test_link_previews_are_off_so_the_map_link_stays_small():
    from bot.main import bot_defaults

    assert bot_defaults().link_preview.is_disabled is True


@pytest.mark.asyncio
async def test_start_shows_business_card_with_book_button(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    await h.say("/start", ANNA)
    card = h.last_to(ANNA)
    for part in ("«Химчистка на Литейном»", ADDRESS, "00:00–23:59", "+7 (812) 123-45-67", LINK):
        assert part in card.text
    assert card.buttons() == [("🧺 Сдать вещь в чистку", "book")]
    # Обычное меню остаётся
    assert h.bot.sent[-2].markup.keyboard[0][0].text == "🧺 Сдать вещь в чистку"


@pytest.mark.asyncio
async def test_book_button_under_card_starts_booking(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    await h.press("book", ANNA)
    assert h.last_to(ANNA).text == NICHES["drycleaning"].book_prompt
    assert any("Чистка пальто" in text for text, _ in h.last_to(ANNA).buttons())


@pytest.mark.asyncio
async def test_real_bot_never_shows_a_fictional_address_or_phone(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.say("/start", ANNA)
    await h.say("📍 Адрес и контакты", ANNA)
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    preset = NICHES["drycleaning"]
    sent = "\n".join(h.texts_to(ANNA))
    assert preset.demo_street not in sent and preset.demo_phone not in sent
    assert "Открыть на карте" not in sent
    assert "Вы записаны в <b>«Белый Лист»</b>, <b>" in sent


@pytest.mark.asyncio
async def test_contacts_button_shows_same_card(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    await h.say("📍 Адрес и контакты", ANNA)
    assert h.last_to(ANNA).text == texts.business_card(h.settings, NICHES["drycleaning"])


@pytest.mark.asyncio
async def test_date_and_time_steps_say_where_you_book(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    await h.say(NICHES["drycleaning"].menu_book, ANNA)
    await h.press(h.last_to(ANNA).callbacks()[0], ANNA)
    day = h.last_to(ANNA).text
    assert day.startswith("Запись в <b>«Химчистка на Литейном»</b>\n") and "Выберите день:" in day

    await h.press(f"date:{SLOT.date().isoformat()}", ANNA)
    time_step = h.last_to(ANNA).text
    assert time_step.startswith("Запись в <b>«Химчистка на Литейном»</b>\n") and "Выберите время:" in time_step
    assert "Чистка пальто" in time_step

    await h.press("back:dates", ANNA)
    assert h.last_to(ANNA).text.startswith("Запись в <b>«Химчистка на Литейном»</b>\n")


@pytest.mark.asyncio
async def test_confirmation_and_reminder_say_where_with_map_link(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    await h.book(ANNA, NICHES["drycleaning"].menu_book)
    o = await h.db.order(1)
    created = texts.order_created(o, h.settings)
    assert f"Вы записаны в <b>«Химчистка на Литейном»</b>, {ADDRESS}, <b>{texts.fmt_dt(SLOT)}</b>." in created
    assert LINK in created
    assert created in h.texts_to(ANNA)

    reminder = texts.reminder(o, h.settings)
    assert "«Химчистка на Литейном»" in reminder and ADDRESS in reminder and LINK in reminder


@pytest.mark.asyncio
async def test_home_visit_points_to_client_address(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch, niche="appliance")
    client_address = "Москва, Тверская ул., 7, кв. 5"
    await h.book(ANNA, NICHES["appliance"].menu_book, address=client_address)
    o = await h.db.order(1)
    for text in (texts.order_created(o, h.settings), texts.reminder(o, h.settings)):
        assert client_address in text and texts.map_url(client_address) in text
        assert ADDRESS not in text
    assert "мастер приедет по адресу" in texts.order_created(o, h.settings)


@pytest.mark.asyncio
async def test_address_is_escaped(tmp_path, monkeypatch):
    h = await client_bot(tmp_path, monkeypatch)
    h.settings.business_address = "Москва, ТЦ А&Б"
    assert "ТЦ А&amp;Б" in texts.business_card(h.settings, NICHES["drycleaning"])


# ---------- демо ----------

@pytest.mark.asyncio
async def test_demo_explains_the_role_after_choosing_niche(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    await h.say("/start", ANNA)
    await h.press("niche:drycleaning", ANNA)
    sent = h.texts_to(ANNA)
    assert any(
        "Представьте, что вы клиент химчистки «Белый Лист» (Лиговский пр., 50). "
        "Сейчас вы пройдёте путь клиента, а потом увидите, как заявку получаете вы — владелец (или ваш приёмщик)" in t
        for t in sent
    )
    card = h.last_to(ANNA)
    assert "Санкт-Петербург, Лиговский пр., 50" in card.text and "Открыть на карте" in card.text
    assert card.buttons() == [("🧺 Сдать вещь в чистку", "book")]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(NICHES))
async def test_demo_uses_preset_details_not_env(tmp_path, monkeypatch, key):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    h.settings.business_address = "Адрес из настроек"
    h.settings.business_phone = "+7 (000) 000-00-00"
    card = texts.business_card(h.settings, NICHES[key])
    assert NICHES[key].demo_address in card and NICHES[key].demo_phone in card
    assert "Адрес из настроек" not in card


def test_demo_addresses_and_phones_are_unique():
    assert len({n.demo_address for n in NICHES.values()}) == len(NICHES)
    assert len({n.demo_phone for n in NICHES.values()}) == len(NICHES)
    assert all("000-00" in n.demo_phone for n in NICHES.values())  # несуществующие номера


@pytest.mark.asyncio
async def test_demo_card_button_needs_a_chosen_niche(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    await h.press("book", ANNA)
    assert "Сначала выберите бизнес: /niche" in h.alerts


# ---------- настройка под клиента ----------

def _client(**kw) -> Client:
    data = dict(niche=NICHES["drycleaning"], name="«Химчистка на Литейном»", address=ADDRESS,
                phone="+7 (812) 123-45-67", start="10:00", end="20:00")
    return Client(**{**data, **kw})


def test_setup_checklist_has_all_botfather_steps():
    text = checklist(_client())
    for step in ("/setname", "/setdescription", "/setabouttext", "/setuserpic"):
        assert step in text
    assert ADDRESS in text and "10:00–20:00" in text and "Химчистка на Литейном" in text


def test_setup_env_block_matches_settings():
    block = env_block(_client())
    assert "NICHE=drycleaning" in block and f"BUSINESS_ADDRESS={ADDRESS}" in block and "DEMO_MODE=false" in block
    assert "WORK_END=20:00" in block


def test_setup_warns_about_telegram_limits():
    assert problems(_client()) == []
    long_address = "Санкт-Петербург, " + "очень длинная улица " * 10
    assert len(setabouttext_text(_client(address=long_address))) > ABOUT_LIMIT
    assert any("/setabouttext" in p for p in problems(_client(address=long_address)))


def test_setup_script_runs_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main(["--niche", "atelier", "--name", "«Игла»", "--address", ADDRESS])
    assert code == 0
    assert "NICHE=atelier" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
