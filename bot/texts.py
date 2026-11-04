from __future__ import annotations

from html import escape

from bot.config import Settings
from bot.db import Order
from bot.niches import NICHES, Niche
from bot.services.slots import fmt_dt


def _e(value: str) -> str:
    """Всё, что ввёл человек, экранируется: сообщения уходят с parse_mode=HTML."""
    return escape(value, quote=False)


def biz_name(s: Settings, niche: Niche) -> str:
    if s.demo_mode:
        return niche.demo_name
    return s.business_name or niche.demo_name


def _button_name(button: str) -> str:
    """Подпись кнопки без эмодзи в начале."""
    return button.split(" ", 1)[1]


def welcome(s: Settings, niche: Niche) -> str:
    points = "\n".join(f"• {p}," for p in niche.welcome_points)
    return (
        f"Здравствуйте! Это бот <b>{biz_name(s, niche)}</b>.\n\n"
        "Здесь можно:\n"
        f"{points}\n"
        "• посмотреть цены и адрес,\n"
        "• написать мастеру прямо в этот чат.\n\n"
        "Выберите действие в меню ниже."
    )


def contacts(s: Settings, niche: Niche) -> str:
    lines = [f"<b>{biz_name(s, niche)}</b>"]
    if s.business_address:
        lines.append(f"📍 {s.business_address}")
    if s.business_phone:
        lines.append(f"📞 {s.business_phone}")
    lines.append(f"🕒 Режим работы: {s.work_start.strftime('%H:%M')}–{s.work_end.strftime('%H:%M')}")
    if s.demo_mode:
        lines.append("\n<i>Это пример. В вашем боте здесь будут ваши адрес, телефон и часы работы.</i>")
    return "\n".join(lines)


def prices(services, niche: Niche) -> str:
    lines = ["<b>Цены</b>\n"]
    for sv in services:
        price = f"от {sv['price_from']} ₽" if sv["price_from"] else "бесплатно"
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
        f"{niche.object_emoji} {niche.object_label}: {_e(device) or '—'}\n"
        f"📝 {niche.problem_label}: {_e(problem) or '—'}\n"
        f"{place}"
        f"🕒 {niche.visit_label}: <b>{fmt_dt(slot)}</b>"
    )


def order_created(o: Order, s: Settings) -> str:
    niche = o.preset
    place = o.address or s.business_address
    return (
        f"✅ Заявка <b>№{o.id}</b> принята.\n"
        f"{niche.visit_wait} <b>{fmt_dt(o.slot)}</b>.\n"
        f"{('📍 ' + _e(place)) if place else ''}\n\n"
        f"{niche.updates_text} "
        f"Проверить вручную — кнопка «{_button_name(niche.menu_status)}».\n"
        "Есть вопрос — просто напишите сюда, мастер ответит в этом чате."
    )


def _note_line(o: Order, prefix: str) -> str:
    return f"\n💬 {prefix}{_e(o.admin_note)}" if o.admin_note else ""


def order_status_card(o: Order) -> str:
    niche = o.preset
    place = f"\n🏠 {_e(o.address)}" if o.address else ""
    return (
        f"<b>Заявка №{o.id}</b> — {o.status_text}\n"
        f"{niche.emoji} {o.service_name} · {_e(o.device) or niche.object_missing}\n"
        f"🕒 {niche.visit_label}: {fmt_dt(o.slot)}{place}{_note_line(o, 'Мастер: ')}"
    )


def status_changed(o: Order) -> str:
    question = "\n\nСогласны с этой стоимостью?" if o.awaits_quote_answer else ""
    return f"🔔 Заявка №{o.id}: <b>{o.status_text}</b>{_note_line(o, '')}{question}"


def reminder(o: Order, s: Settings) -> str:
    niche = o.preset
    place = ", ".join(part for part in (biz_name(s, niche), o.address or s.business_address) if part)
    return (
        f"⏰ Напоминаем: сегодня в <b>{o.slot.strftime('%H:%M')}</b> {niche.reminder_wait}.\n"
        f"{_e(place)}\n"
        "Если не получается — ответьте на это сообщение, перенесём."
    )


def admin_order(o: Order) -> str:
    niche = o.preset
    tg = f"@{o.username}" if o.username else f"id {o.user_id}"
    place = f"🏠 {_e(o.address)}\n" if o.address else ""
    return (
        f"🆕 <b>Новая заявка №{o.id}</b>\n\n"
        f"👤 {_e(o.name)} · {o.phone} · {tg}\n"
        f"{niche.emoji} {o.service_name}\n"
        f"{niche.object_emoji} {_e(o.device) or '—'}\n"
        f"📝 {_e(o.problem) or '—'}\n"
        f"{place}"
        f"🕒 <b>{fmt_dt(o.slot)}</b>"
    )


def admin_order_with_status(o: Order) -> str:
    return f"{admin_order(o)}\n\nСтатус: <b>{o.status_text}</b>"


def admin_order_line(o: Order) -> str:
    return f"{o.slot.strftime('%H:%M')} №{o.id} {_e(o.name)} · {o.phone} · {o.service_name} — {o.status_text}"


def quote_hint(o: Order) -> str:
    return (f"Укажите сумму — клиент получит кнопки «Согласен» и «Перезвоните мне»:\n"
            f"<code>/note {o.id} 8 500 ₽, замена колодок</code>")


QUOTE_YES = "yes"
QUOTE_CALL = "call"
QUOTE_ANSWERS = (QUOTE_YES, QUOTE_CALL)


def quote_client_ack(answer: str) -> str:
    if answer == QUOTE_YES:
        return "✅ Спасибо! Передали мастеру, что вы согласны."
    return "📞 Передали мастеру, он вам перезвонит."


def quote_master_answer(o: Order, answer: str) -> str:
    verdict = "✅ Клиент согласен" if answer == QUOTE_YES else "📞 Клиент просит перезвонить"
    return f"<b>{verdict}</b> — заявка №{o.id}\n👤 {_e(o.name)} · {o.phone}\n💬 {_e(o.admin_note)}"


# ---------- переписка клиента с мастером ----------

REPLY_HINT = "Чтобы ответить клиенту, ответьте на это сообщение (Reply)."
DEMO_REPLY_HINT = ("👆 Так мастер видит сообщение клиента. Ответьте на него через Reply, "
                   "и ответ придёт клиенту в этот же чат.")


def relay_to_master(user, o: Order | None, body: str | None, demo: bool) -> str:
    """Сообщение мастеру. Если body пуст, само сообщение клиента идёт следом копией (фото, файл, длинный текст)."""
    who = _e(user.full_name) + (f" · @{user.username}" if user.username else "")
    context = f"\n📋 Заявка №{o.id} · {_e(o.name)} · {o.phone} · {o.service_name} — {o.status_text}" if o else ""
    text = f"\n\n{_e(body)}" if body else ""
    hint = DEMO_REPLY_HINT if demo else f"<i>{REPLY_HINT}</i>"
    return f"💬 <b>Сообщение от клиента</b>\n👤 {who}{context}{text}\n\n{hint}"


def relay_ack() -> str:
    return "✉️ Передали мастеру, он ответит в этом чате."


def relay_failed() -> str:
    return "⚠️ Не получилось передать сообщение. Попробуйте позже или позвоните нам."


def master_answer(body: str, demo: bool) -> str:
    text = f"💬 <b>Мастер:</b> {_e(body)}"
    return f"👤 <i>Клиент получил:</i>\n\n{text}" if demo else text


def master_answer_sent() -> str:
    return "✅ Отправлено клиенту."


def master_answer_failed() -> str:
    return "⚠️ Не удалось доставить: возможно, клиент заблокировал бота. Свяжитесь с ним по телефону."


def admin_relay_hint() -> str:
    return "Это чат с ботом. Чтобы ответить клиенту, нажмите Reply на его сообщении."


def admin_help() -> str:
    return (
        "<b>Команды мастера</b>\n"
        "/today — записи на сегодня\n"
        "/tomorrow — записи на завтра\n"
        "/open — все незакрытые заявки\n"
        "/order 12 — карточка заявки №12 с кнопками статусов\n"
        "/note 12 текст — комментарий клиенту (действует до следующей смены статуса)\n"
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
        "В демо вы одновременно клиент и мастер: запишитесь как клиент, и вам придёт карточка мастера. "
        "Меняйте в ней статусы и смотрите, что получает клиент.\n\n"
        "Напишите в чат любой вопрос — увидите, как он придёт мастеру и как мастер ответит.\n\n"
        "Сменить бизнес — /niche"
    )


def demo_phone_note() -> str:
    return "\n\nЭто демо: подойдёт любой номер, заявка удалится через 7 дней."


def demo_new_card(o: Order) -> str:
    return (f"{admin_order(o)}\n\nСтатус: <b>{o.status_text}</b>\n\n"
            "👆 Так заявку видит мастер. Нажмите статус — и посмотрите, что получит клиент.")


def demo_client_view(o: Order) -> str:
    return f"👤 <i>Клиент получил:</i>\n\n{status_changed(o)}"


def demo_master_card(o: Order) -> str:
    status = o.preset.status(o.status)
    if status and status.approval and not o.admin_note:
        hint = quote_hint(o)
    elif o.status == "ready":
        hint = f"Клиент узнал о готовности без звонка. Нажмите «{o.preset.final.text}», чтобы завершить сценарий."
    else:
        hint = "👆 Это уже у клиента, без звонков и вопросов «ну что там?». Нажмите следующий статус."
    return f"🛠 <b>Карточка мастера</b>, заявка №{o.id}\nСтатус: <b>{o.status_text}</b>\n\n{hint}"


def demo_quote_hint() -> str:
    return "👆 Клиент получил сумму и кнопки. Нажмите за клиента «Согласен» или «Перезвоните мне»."


def demo_quote_card(o: Order, answer: str) -> str:
    return (f"{quote_master_answer(o, answer)}\n\n"
            "👆 Так мастеру приходит ответ клиента. Нажмите следующий статус.")


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
