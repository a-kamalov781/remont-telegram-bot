from __future__ import annotations

import re
from datetime import date
from html import escape
from urllib.parse import quote

from bot.config import Settings
from bot.db import Order
from bot.niches import NICHES, Niche
from bot.services.price import format_rub
from bot.services.slots import fmt_date, fmt_dt


def _e(value: str) -> str:
    """Всё, что ввёл человек, экранируется: сообщения уходят с parse_mode=HTML."""
    return escape(value, quote=False)


def biz_name(s: Settings, niche: Niche) -> str:
    if s.demo_mode:
        return niche.demo_name
    return s.business_name or niche.demo_name


def biz_address(s: Settings, niche: Niche) -> str:
    """Вне демо только настоящий адрес из настроек: вымышленный клиенту показывать нельзя."""
    return niche.demo_address if s.demo_mode else s.business_address


def biz_phone(s: Settings, niche: Niche) -> str:
    return niche.demo_phone if s.demo_mode else s.business_phone


def map_url(address: str) -> str:
    return "https://yandex.ru/maps/?text=" + quote(address, safe="")


def map_link(address: str) -> str:
    return f'<a href="{map_url(address)}">📍 Открыть на карте</a>'


def _visit_place(o: Order, s: Settings) -> str:
    """Куда идти клиенту или куда едет мастер."""
    return o.address or biz_address(s, o.preset)


def business_card(s: Settings, niche: Niche) -> str:
    address, phone = biz_address(s, niche), biz_phone(s, niche)
    lines = [f"<b>{_e(biz_name(s, niche))}</b>"]
    if address:
        lines.append(f"📍 {_e(address)}")
    lines.append(f"🕒 {s.work_start.strftime('%H:%M')}–{s.work_end.strftime('%H:%M')}")
    if phone:
        lines.append(f"📞 {_e(phone)}")
    if address:
        lines.append(map_link(address))
    return "\n".join(lines)


def booking_header(s: Settings, niche: Niche, service: str, day: date | None = None) -> str:
    """Заголовок шагов выбора даты и времени: клиент видит, куда записывается."""
    lines = [f"Запись в <b>{_e(biz_name(s, niche))}</b>"]
    if service:
        lines.append(f"{niche.emoji} {service}")
    if day:
        lines.append(f"📅 {fmt_date(day)}")
    return "\n".join(lines)


def _button_name(button: str) -> str:
    """Подпись без эмодзи в начале."""
    return button.split(" ", 1)[1]


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


def _object_implied(device: str, service: str) -> bool:
    """«пальто» при услуге «Чистка пальто» повторять незачем."""
    words = _words(device)
    return bool(words) and words <= _words(service)


def _object_line(niche: Niche, device: str, service: str) -> str:
    if not device.strip() or _object_implied(device, service):
        return ""
    return f"{niche.object_emoji} {niche.object_label}: {_e(device)}\n"


def _problem_line(niche: Niche, problem: str) -> str:
    return f"📝 {niche.problem_label}: {_e(problem)}\n" if problem.strip() else ""


def welcome(s: Settings, niche: Niche) -> str:
    points = "\n".join(f"• {p}," for p in niche.welcome_points)
    return (
        f"Здравствуйте! Это бот <b>{_e(biz_name(s, niche))}</b>.\n\n"
        "Здесь можно:\n"
        f"{points}\n"
        "• посмотреть цены и адрес,\n"
        f"• написать {niche.staff_dative} прямо в этот чат.\n\n"
        "Выберите действие в меню ниже."
    )


def contacts(s: Settings, niche: Niche) -> str:
    card = business_card(s, niche)
    if s.demo_mode:
        return f"{card}\n\n<i>Это пример. В вашем боте здесь будут ваши адрес, телефон и часы работы.</i>"
    return card


def prices(services, niche: Niche) -> str:
    lines = ["<b>Цены</b>\n"]
    for sv in services:
        price = f"от {format_rub(sv['price_from'])}" if sv["price_from"] else "бесплатно"
        lines.append(f"• <b>{sv['name']}</b> — {price}\n  <i>{sv['description']}</i>")
    lines.append(f"\n{niche.price_note} Нажмите «Записаться», чтобы выбрать время.")
    return "\n".join(lines)


def no_orders(niche: Niche) -> str:
    return f"У вас пока нет заявок. Нажмите «{_button_name(niche.menu_book)}»."


def order_summary(niche: Niche, name: str, phone: str, service_name: str, device: str, problem: str,
                  slot, address: str = "") -> str:
    place = f"🏠 Адрес: {_e(address)}\n" if address else ""
    return (
        "<b>Проверьте заявку</b>\n\n"
        f"👤 {_e(name)}\n📱 {phone}\n"
        f"{niche.emoji} {service_name}\n"
        f"{_object_line(niche, device, service_name)}"
        f"{_problem_line(niche, problem)}"
        f"{place}"
        f"🕒 {niche.visit_label}: <b>{fmt_dt(slot)}</b>"
    )


def order_created(o: Order, s: Settings) -> str:
    niche = o.preset
    name = _e(biz_name(s, niche))
    place = _visit_place(o, s)
    if o.address:
        where = (f"Вы записаны в <b>{name}</b>: {niche.staff_name} приедет по адресу {_e(o.address)}, "
                 f"<b>{fmt_dt(o.slot)}</b>.")
    elif place:
        where = f"Вы записаны в <b>{name}</b>, {_e(place)}, <b>{fmt_dt(o.slot)}</b>."
    else:
        where = f"Вы записаны в <b>{name}</b>, <b>{fmt_dt(o.slot)}</b>."
    link = f"\n{map_link(place)}" if place else ""
    return (
        f"✅ Заявка <b>№{o.id}</b> принята.\n"
        f"{where}{link}\n\n"
        f"{niche.updates_text} "
        f"Проверить вручную — кнопка «{_button_name(niche.menu_status)}».\n"
        f"Есть вопрос — просто напишите сюда, {niche.staff_name} ответит в этом чате."
    )


def _price_line(o: Order) -> str:
    return f"\n💰 Стоимость: <b>{format_rub(o.price)}</b>" if o.price else ""


def _note_line(o: Order, prefix: str) -> str:
    return f"\n💬 {prefix}{_e(o.admin_note)}" if o.admin_note else ""


def order_status_card(o: Order) -> str:
    niche = o.preset
    place = f"\n🏠 {_e(o.address)}" if o.address else ""
    shown = o.device.strip() and not _object_implied(o.device, o.service_name)
    device = f" · {_e(o.device)}" if shown else ""
    return (
        f"<b>Заявка №{o.id}</b> — {o.status_text}\n"
        f"{niche.emoji} {o.service_name}{device}\n"
        f"🕒 {niche.visit_label}: {fmt_dt(o.slot)}{place}{_price_line(o)}"
        f"{_note_line(o, f'{niche.staff_title}: ')}"
    )


def status_changed(o: Order) -> str:
    status = o.preset.status(o.status)
    price = _price_line(o) if status and status.approval else ""
    question = "\n\nСогласны с этой стоимостью?" if o.awaits_quote_answer else ""
    return f"🔔 Заявка №{o.id}: <b>{o.status_text}</b>{price}{_note_line(o, '')}{question}"


def reminder(o: Order, s: Settings) -> str:
    niche = o.preset
    address = _visit_place(o, s)
    place = ", ".join(part for part in (biz_name(s, niche), address) if part)
    link = f"{map_link(address)}\n" if address else ""
    return (
        f"⏰ Напоминаем: сегодня в <b>{o.slot.strftime('%H:%M')}</b> {niche.reminder_wait}.\n"
        f"{_e(place)}\n"
        f"{link}"
        "Если не получается — ответьте на это сообщение, перенесём."
    )


def _card_title(o: Order) -> str:
    if o.status == "new":
        return f"🆕 <b>Новая заявка №{o.id}</b>"
    return f"<b>Заявка №{o.id} · {_button_name(o.status_text)}</b>"


def admin_order(o: Order) -> str:
    """Карточка заявки у сотрудника. Статус виден в заголовке."""
    niche = o.preset
    tg = f"@{o.username}" if o.username else f"id {o.user_id}"
    place = f"🏠 {_e(o.address)}\n" if o.address else ""
    return (
        f"{_card_title(o)}\n\n"
        f"👤 {_e(o.name)} · {o.phone} · {tg}\n"
        f"{niche.emoji} {o.service_name}\n"
        f"{_object_line(niche, o.device, o.service_name)}"
        f"{_problem_line(niche, o.problem)}"
        f"{place}"
        f"🕒 <b>{fmt_dt(o.slot)}</b>"
        f"{_price_line(o)}"
    )


def admin_order_line(o: Order) -> str:
    return f"{o.slot.strftime('%H:%M')} №{o.id} {_e(o.name)} · {o.phone} · {o.service_name} — {o.status_text}"


# ---------- стоимость ----------

def quote_prompt(o: Order) -> str:
    return f"Заявка №{o.id}. Введите сумму и что делаем (например: 8500 замена колодок)"


def quote_retry() -> str:
    return "Не нашёл сумму. Напишите, например: 8500 замена колодок"


QUOTE_WAIT_FIRST = "Сначала введите сумму или нажмите Отмена"


def quote_cancelled() -> str:
    return "Ввод суммы отменён, клиенту ничего не отправлено. Кнопки статусов снова работают."


def quote_sent(o: Order) -> str:
    return (f"💰 Заявка №{o.id}: стоимость <b>{format_rub(o.price)}</b> записана и отправлена клиенту. "
            "Его ответ придёт сюда.")


def price_saved(o: Order) -> str:
    return (f"💰 Заявка №{o.id}: стоимость <b>{format_rub(o.price)}</b> записана. "
            "Клиент увидит её в статусе готовности.")


def price_format_error() -> str:
    return "Формат: /price 12 8500"


def price_wrong_niche() -> str:
    return "Команда /price работает только в автосервисе."


def note_sent(o: Order, had_amount: bool) -> str:
    text = f"Комментарий к №{o.id} отправлен клиенту."
    if had_amount:
        return f"{text}\n💰 Стоимость записана: <b>{format_rub(o.price)}</b>. Исправить: /price {o.id} сумма"
    status = o.preset.status(o.status)
    if status and status.approval:
        return f"{text}\n⚠️ Сумму в тексте не нашёл. Укажите её: /price {o.id} сумма"
    return text


QUOTE_YES = "yes"
QUOTE_CALL = "call"
QUOTE_ANSWERS = (QUOTE_YES, QUOTE_CALL)


def quote_client_ack(answer: str, niche: Niche) -> str:
    if answer == QUOTE_YES:
        return f"✅ Спасибо! Передали {niche.staff_dative}, что вы согласны."
    return f"📞 Передали {niche.staff_dative}, вам перезвонят."


def quote_master_answer(o: Order, answer: str) -> str:
    verdict = "✅ Клиент согласен" if answer == QUOTE_YES else "📞 Клиент просит перезвонить"
    return f"<b>{verdict}</b> — заявка №{o.id}\n👤 {_e(o.name)} · {o.phone}{_price_line(o)}{_note_line(o, '')}"


# ---------- переписка клиента с сотрудником ----------

REPLY_HINT = "Чтобы ответить клиенту, ответьте на это сообщение (Reply)."


def _demo_reply_hint(niche: Niche) -> str:
    return (f"👆 Так {niche.staff_name} видит сообщение клиента. Ответьте на него через Reply, "
            "и ответ придёт клиенту в этот же чат.")


def relay_to_master(user, o: Order | None, body: str | None, demo: bool, niche: Niche) -> str:
    """Сообщение сотруднику. Если body пуст, само сообщение клиента идёт следом копией (фото, файл, длинный текст)."""
    who = _e(user.full_name) + (f" · @{user.username}" if user.username else "")
    context = f"\n📋 Заявка №{o.id} · {_e(o.name)} · {o.phone} · {o.service_name} — {o.status_text}" if o else ""
    text = f"\n\n{_e(body)}" if body else ""
    hint = _demo_reply_hint(niche) if demo else f"<i>{REPLY_HINT}</i>"
    return f"💬 <b>Сообщение от клиента</b>\n👤 {who}{context}{text}\n\n{hint}"


def relay_ack(niche: Niche) -> str:
    return f"✉️ Передали {niche.staff_dative}, ответ придёт в этот чат."


def relay_too_many(niche: Niche) -> str:
    return f"Слишком много сообщений, {niche.staff_name} ответит на предыдущие"


def relay_failed() -> str:
    return "⚠️ Не получилось передать сообщение. Попробуйте позже или позвоните нам."


def master_answer(body: str, demo: bool, niche: Niche) -> str:
    text = f"💬 <b>{niche.staff_title}:</b> {_e(body)}"
    return f"👤 <i>Клиент получил:</i>\n\n{text}" if demo else text


def master_answer_sent() -> str:
    return "✅ Отправлено клиенту."


def master_answer_failed() -> str:
    return "⚠️ Не удалось доставить: возможно, клиент заблокировал бота. Свяжитесь с ним по телефону."


def admin_relay_hint() -> str:
    return "Это чат с ботом. Чтобы ответить клиенту, нажмите Reply на его сообщении."


def admin_help(niche: Niche) -> str:
    return (
        f"<b>Команды {niche.staff_genitive}</b>\n"
        "/today — записи на сегодня\n"
        "/tomorrow — записи на завтра\n"
        "/open — все незакрытые заявки\n"
        "/order 12 — карточка заявки №12 с кнопками статусов\n"
        "/note 12 текст — комментарий клиенту (действует до следующей смены статуса)\n"
        "/price 12 8500 — стоимость заявки (автосервис), сохраняется при смене статусов\n"
        "/move 12 2026-11-05 14:00 — перенести визит\n"
        "/block 2026-11-05 14:00 — закрыть слот\n"
        "/unblock 2026-11-05 14:00 — открыть слот\n"
        "/stats — счётчики по статусам\n\n"
        "Сообщения клиентов приходят сюда. Чтобы ответить, нажмите Reply на сообщении клиента."
    )


# ---------- демо ----------

def demo_pick() -> str:
    return (
        "Это демо бота для записи и статусов заказа.\n\n"
        "<b>Какой у вас бизнес?</b> Покажу бота именно для него."
    )


def demo_intro(niche: Niche) -> str:
    return (
        f"{niche.emoji} <b>{niche.name}</b>\n\n"
        f"Представьте, что вы клиент {niche.client_of} {niche.demo_name} ({niche.demo_street}). "
        f"Сейчас вы пройдёте путь клиента, а потом увидите, как заявку получаете вы — владелец (или ваш {niche.staff_name}).\n\n"
        f"Напишите в чат любой вопрос — увидите, как он придёт {niche.staff_dative} и как {niche.staff_name} ответит.\n\n"
        "<i>Название, адрес и телефон в демо вымышленные.</i>\n"
        "Сменить бизнес — /niche"
    )


def demo_phone_note() -> str:
    return "\n\nЭто демо: подойдёт любой номер, заявка удалится через 7 дней."


def demo_new_card(o: Order) -> str:
    return (f"{admin_order(o)}\n\n"
            f"👆 Так заявку видит {o.preset.staff_name}. Нажмите статус — и посмотрите, что получит клиент.")


def demo_client_view(o: Order) -> str:
    return f"👤 <i>Клиент получил:</i>\n\n{status_changed(o)}"


def demo_master_card(o: Order) -> str:
    status = o.preset.status(o.status)
    if status and status.approval and not o.price:
        hint = f"Сумма не указана. Нажмите «{_button_name(status.text)}» ещё раз и введите её."
    elif o.awaits_quote_answer:
        hint = "Ждём ответ клиента на сумму."
    elif status and status.approval:
        hint = "Клиент ответил. Нажмите следующий статус."
    elif o.status == "ready":
        hint = f"Клиент узнал о готовности без звонка. Нажмите «{_button_name(o.preset.final.text)}», чтобы завершить сценарий."
    else:
        hint = "Клиент уже получил это сообщение, без звонков и вопросов «ну что там?». Нажмите следующий статус."
    return f"{admin_order(o)}\n\n{hint}"


def demo_quote_hint(o: Order) -> str:
    saved = f"\n\n💰 Стоимость {format_rub(o.price)} записана в заявку и сохранится при смене статусов." if o.price else ""
    return f"👆 Клиент получил сумму и кнопки. Нажмите за клиента «Согласен» или «Перезвоните мне».{saved}"


def _remind_period(minutes: int) -> str:
    if minutes % 60:
        return f"{minutes} минут"
    hours = minutes // 60
    word = "час" if hours % 10 == 1 and hours % 100 != 11 else "часа" if 2 <= hours % 10 <= 4 and not 12 <= hours % 100 <= 14 else "часов"
    return "час" if hours == 1 else f"{hours} {word}"


def demo_reminder_preview(o: Order, s: Settings) -> str:
    return (f"⏰ <b>Так выглядит напоминание за {_remind_period(s.remind_before_minutes)} до визита</b>\n\n"
            f"{reminder(o, s)}")


def demo_quote_answer(o: Order, answer: str) -> str:
    return f"{quote_master_answer(o, answer)}\n\n👆 Так {o.preset.staff_dative} приходит ответ клиента."


def demo_finish(s: Settings) -> str:
    contact = f" Написать разработчику: {_e(s.demo_contact)}" if s.demo_contact else ""
    return (
        f"Это демо. Такой бот под ваш бизнес — 2 дня, ваше название, услуги и цены.{contact}\n\n"
        "Посмотреть бота для другого бизнеса — /niche"
    )


def demo_cancelled() -> str:
    return "Заявка отменена, время снова свободно. Записаться ещё раз можно кнопкой в меню."


def demo_stats(st: dict) -> str:
    lines = [
        "<b>Демо</b> (без ADMIN_IDS)",
        f"Зашли: <b>{st['visitors']}</b>",
        f"Выбрали нишу: <b>{st['chose']}</b>",
        f"Записались: <b>{st['booked']}</b>",
        f"Дошли до конца: <b>{st['finished']}</b>",
    ]
    if st["by_niche"]:
        lines.append("\n<b>По нишам</b> (выбрали / записались / до конца)")
        for key, niche in NICHES.items():
            row = st["by_niche"].get(key)
            if row:
                lines.append(f"{niche.emoji} {niche.name}: {row.get('niche', 0)} / "
                             f"{row.get('booked', 0)} / {row.get('finished', 0)}")
    return "\n".join(lines)
