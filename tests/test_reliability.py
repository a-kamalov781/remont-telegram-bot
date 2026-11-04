"""Надёжность: повтор запросов к Telegram, мгновенный ответ на нажатие, кнопки на время ввода суммы."""
from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import GetUpdates, SendMessage

from bot import texts
from bot.niches import NICHES
from bot.services.retry import RetryRequests
from tests.harness import ADMIN, SLOT, make, visitor

ANNA = visitor(100)
AUTO = NICHES["autoservice"]
DRY = NICHES["drycleaning"]
SEND = SendMessage(chat_id=1, text="x")
OK = object()


class Flaky:
    def __init__(self, *failures):
        self.failures = list(failures)
        self.calls = 0

    async def __call__(self, bot_, method):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return OK


def network_error():
    return TelegramNetworkError(method=SEND, message="Connection reset by peer")


def retry_after(seconds):
    return TelegramRetryAfter(method=SEND, message="Too Many Requests", retry_after=seconds)


def retrier():
    delays = []

    async def sleep(delay):
        delays.append(delay)

    return RetryRequests(sleep=sleep), delays


@pytest.mark.asyncio
async def test_network_error_is_retried_with_backoff():
    middleware, delays = retrier()
    request = Flaky(network_error(), network_error())
    assert await middleware(request, None, SEND) is OK
    assert request.calls == 3 and delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_gives_up_after_three_attempts():
    middleware, delays = retrier()
    request = Flaky(network_error(), network_error(), network_error(), network_error())
    with pytest.raises(TelegramNetworkError):
        await middleware(request, None, SEND)
    assert request.calls == 3 and len(delays) == 2


@pytest.mark.asyncio
async def test_retry_after_waits_as_long_as_telegram_asks():
    middleware, delays = retrier()
    request = Flaky(retry_after(7))
    assert await middleware(request, None, SEND) is OK
    assert delays == [7]


@pytest.mark.asyncio
async def test_too_long_retry_after_is_not_awaited():
    middleware, delays = retrier()
    request = Flaky(retry_after(3600))
    with pytest.raises(TelegramRetryAfter):
        await middleware(request, None, SEND)
    assert request.calls == 1 and delays == []


@pytest.mark.asyncio
async def test_other_errors_and_polling_are_not_retried():
    middleware, delays = retrier()
    request = Flaky(TelegramBadRequest(method=SEND, message="bad"))
    with pytest.raises(TelegramBadRequest):
        await middleware(request, None, SEND)
    assert request.calls == 1

    request = Flaky(network_error())
    with pytest.raises(TelegramNetworkError):
        await middleware(request, None, GetUpdates())
    assert request.calls == 1 and delays == []


def test_retries_are_installed_on_a_real_session():
    from aiogram import Bot

    real = Bot("1:x")
    real.session.middleware(RetryRequests())
    assert any(isinstance(m, RetryRequests) for m in real.session.middleware)


# ---------- мгновенный ответ на нажатие ----------

async def _answered_first(h, data, user):
    h.events.clear()
    await h.press(data, user)
    assert h.events, data
    assert h.events[0] == "answer", (data, h.events)
    assert h.events.count("answer") == 1, (data, h.events)


@pytest.mark.asyncio
async def test_every_button_answers_before_any_message(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, demo_mode=True)
    await h.say("/start", ANNA)
    await _answered_first(h, "niche:autoservice", ANNA)
    await _answered_first(h, "book", ANNA)
    service = h.last_to(ANNA).callbacks()[0]
    await _answered_first(h, service, ANNA)
    await _answered_first(h, "back:services", ANNA)
    await _answered_first(h, service, ANNA)
    day = f"date:{SLOT.date().isoformat()}"
    await _answered_first(h, day, ANNA)
    await _answered_first(h, "back:dates", ANNA)
    await _answered_first(h, day, ANNA)
    await _answered_first(h, f"slot:{SLOT.isoformat()}", ANNA)
    for text in ("Анна", "8 912 345 67 89", "Kia", "Скрип"):
        await h.say(text, ANNA)
    await _answered_first(h, "confirm", ANNA)
    await _answered_first(h, "adm:menu:1", ANNA)
    await _answered_first(h, "adm:less:1", ANNA)
    await _answered_first(h, "adm:diagnostics:1", ANNA)
    await _answered_first(h, "adm:approval:1", ANNA)
    await _answered_first(h, "qcancel:1", ANNA)
    await _answered_first(h, "adm:approval:1", ANNA)
    await h.say("8500 колодки", ANNA)
    await _answered_first(h, "quote:yes:1", ANNA)
    await _answered_first(h, "adm:ready:1", ANNA)
    await _answered_first(h, "adm:done:1", ANNA)


@pytest.mark.asyncio
async def test_real_bot_status_button_answers_first(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, DRY.menu_book)
    await _answered_first(h, "adm:assessment:1", ADMIN)


@pytest.mark.asyncio
async def test_cancel_booking_answers_first(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.say(DRY.menu_book, ANNA)
    await _answered_first(h, "cancel", ANNA)


@pytest.mark.asyncio
async def test_button_without_handler_is_answered(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    h.events.clear()
    await h.press("нет:такой", ANNA)
    assert h.events == ["answer"]


@pytest.mark.asyncio
async def test_failing_handler_still_answers(tmp_path, monkeypatch):
    h = await make(tmp_path, monkeypatch, niche="drycleaning")
    await h.book(ANNA, DRY.menu_book)

    async def broken(*a, **kw):
        raise RuntimeError("сбой")

    monkeypatch.setattr(h.db, "order", broken)
    h.events.clear()
    with pytest.raises(RuntimeError):
        await h.press("adm:assessment:1", ADMIN)
    assert h.events == ["answer"]


# ---------- устаревшие кнопки при вводе суммы ----------

async def waiting(tmp_path, monkeypatch, demo_mode=False):
    if demo_mode:
        h = await make(tmp_path, monkeypatch, demo_mode=True)
        await h.say("/start", ANNA)
        await h.press("niche:autoservice", ANNA)
        await h.book(ANNA, AUTO.menu_book)
        staff = ANNA
    else:
        h = await make(tmp_path, monkeypatch, niche="autoservice")
        await h.book(ANNA, AUTO.menu_book)
        staff = ADMIN
    await h.press("adm:approval:1", staff)
    return h, staff, h.last_to(staff)


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
async def test_cancel_button_disappears_after_amount(tmp_path, monkeypatch, demo_mode):
    h, staff, prompt = await waiting(tmp_path, monkeypatch, demo_mode)
    assert prompt.callbacks() == ["qcancel:1"]
    await h.say("8500 колодки", staff)
    assert prompt.buttons() == []
    assert "Введите сумму" in prompt.text


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
@pytest.mark.parametrize("data", ["adm:diagnostics:1", "adm:approval:1", "adm:menu:1", "adm:cancelled:1"])
async def test_status_buttons_are_inactive_while_waiting(tmp_path, monkeypatch, demo_mode, data):
    h, staff, _ = await waiting(tmp_path, monkeypatch, demo_mode)
    client_before = len(h.texts_to(ANNA))
    h.alerts.clear()
    await h.press(data, staff)
    assert h.alerts == ["Сначала введите сумму или нажмите Отмена"]
    assert (await h.db.order(1)).status == "new"
    assert len(h.texts_to(ANNA)) == client_before

    # Ожидание не сбилось
    await h.say("8500 колодки", staff)
    assert (await h.db.order(1)).price == 8500


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
async def test_buttons_work_again_after_amount(tmp_path, monkeypatch, demo_mode):
    h, staff, _ = await waiting(tmp_path, monkeypatch, demo_mode)
    await h.say("8500 колодки", staff)
    h.alerts.clear()
    await h.press("adm:waiting_parts:1", staff)
    assert texts.QUOTE_WAIT_FIRST not in h.alerts
    assert (await h.db.order(1)).status == "waiting_parts"


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_mode", [False, True])
async def test_buttons_work_again_after_cancel(tmp_path, monkeypatch, demo_mode):
    h, staff, prompt = await waiting(tmp_path, monkeypatch, demo_mode)
    await h.press("qcancel:1", staff)
    assert prompt.buttons() == [] and "Кнопки статусов снова работают" in prompt.text
    await h.press("adm:diagnostics:1", staff)
    assert (await h.db.order(1)).status == "diagnostics"


@pytest.mark.asyncio
async def test_retry_moves_cancel_button_to_the_new_question(tmp_path, monkeypatch):
    h, staff, prompt = await waiting(tmp_path, monkeypatch)
    await h.say("без суммы", staff)
    retry = h.last_to(staff)
    assert prompt.buttons() == [] and retry.callbacks() == ["qcancel:1"]
    await h.say("9000 колодки", staff)
    assert retry.buttons() == []
    assert (await h.db.order(1)).price == 9000


@pytest.mark.asyncio
async def test_note_and_price_close_input_and_remove_cancel(tmp_path, monkeypatch):
    h, staff, prompt = await waiting(tmp_path, monkeypatch)
    await h.say("/note 1 8 500 ₽ колодки", staff)
    assert prompt.buttons() == []

    await h.press("adm:approval:1", staff)
    second = h.last_to(staff)
    await h.say("/price 1 7000", staff)
    assert second.buttons() == []
    await h.press("adm:diagnostics:1", staff)
    assert (await h.db.order(1)).status == "diagnostics"


@pytest.mark.asyncio
async def test_stale_cancel_button_removes_itself(tmp_path, monkeypatch):
    h, staff, prompt = await waiting(tmp_path, monkeypatch)
    await h.say("/start", staff)  # /start закрывает ввод, кнопка осталась у вопроса
    await h.press("qcancel:1", staff)
    assert "Этот ввод уже закрыт" in h.alerts
    assert prompt.buttons() == []


# ---------- объяснение роли ----------

@pytest.mark.parametrize("key,staff", [
    ("drycleaning", "приёмщик"), ("atelier", "приёмщик"), ("autoservice", "мастер-приёмщик"),
    ("repair", "мастер"), ("appliance", "мастер"),
])
def test_role_explanation_speaks_to_the_owner(key, staff):
    assert f"как заявку получаете вы — владелец (или ваш {staff})" in texts.demo_intro(NICHES[key])
