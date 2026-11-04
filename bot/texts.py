from __future__ import annotations

from bot.config import Settings
from bot.db import Order
from bot.services.slots import fmt_dt


def welcome(s: Settings) -> str:
    return (
        f"Здравствуйте! Это бот <b>{s.business_name}</b>.\n\n"
        "Здесь можно:\n"
        "• записаться на ремонт в удобное время,\n"
        "• узнать статус ремонта без звонка,\n"
        "• посмотреть цены и адрес.\n\n"
        "Выберите действие в меню ниже."
    )


def contacts(s: Settings) -> str:
    lines = [f"<b>{s.business_name}</b>"]
    if s.business_address:
        lines.append(f"📍 {s.business_address}")
    if s.business_phone:
        lines.append(f"📞 {s.business_phone}")
    lines.append(f"🕒 Режим работы: {s.work_start.strftime('%H:%M')}–{s.work_end.strftime('%H:%M')}")
    return "\n".join(lines)


def prices(services) -> str:
    lines = ["<b>Цены</b>\n"]
    for sv in services:
        price = f"от {sv['price_from']} ₽" if sv["price_from"] else "бесплатно"
        lines.append(f"• <b>{sv['name']}</b> — {price}\n  <i>{sv['description']}</i>")
    lines.append("\nТочная стоимость — после диагностики. Нажмите «Записаться», чтобы выбрать время.")
    return "\n".join(lines)


def order_summary(name: str, phone: str, service_name: str, device: str, problem: str, slot) -> str:
    return (
        "<b>Проверьте заявку</b>\n\n"
        f"👤 {name}\n📱 {phone}\n"
        f"🔧 {service_name}\n"
        f"💻 Устройство: {device or '—'}\n"
        f"📝 Проблема: {problem or '—'}\n"
        f"🕒 Визит: <b>{fmt_dt(slot)}</b>"
    )


def order_created(o: Order, s: Settings) -> str:
    return (
        f"✅ Заявка <b>№{o.id}</b> принята.\n"
        f"Ждём вас <b>{fmt_dt(o.slot)}</b>.\n"
        f"{('📍 ' + s.business_address) if s.business_address else ''}\n\n"
        "Статус ремонта будет приходить сюда автоматически. "
        "Проверить вручную — кнопка «Статус моего ремонта»."
    )


def order_status_card(o: Order) -> str:
    note = f"\n💬 Мастер: {o.admin_note}" if o.admin_note else ""
    return (
        f"<b>Заявка №{o.id}</b> — {o.status_text}\n"
        f"🔧 {o.service_name} · {o.device or 'устройство не указано'}\n"
        f"🕒 Визит: {fmt_dt(o.slot)}{note}"
    )


def status_changed(o: Order) -> str:
    note = f"\n💬 {o.admin_note}" if o.admin_note else ""
    return f"🔔 Заявка №{o.id}: <b>{o.status_text}</b>{note}"


def reminder(o: Order, s: Settings) -> str:
    place = ", ".join(part for part in (s.business_name, s.business_address) if part)
    return (
        f"⏰ Напоминаем: сегодня в <b>{o.slot.strftime('%H:%M')}</b> ждём вас.\n"
        f"{place}\n"
        "Если не получается прийти — ответьте на это сообщение, перенесём."
    )


def admin_new_order(o: Order) -> str:
    tg = f"@{o.username}" if o.username else f"id {o.user_id}"
    return (
        f"🆕 <b>Новая заявка №{o.id}</b>\n\n"
        f"👤 {o.name} · {o.phone} · {tg}\n"
        f"🔧 {o.service_name}\n"
        f"💻 {o.device or '—'}\n"
        f"📝 {o.problem or '—'}\n"
        f"🕒 <b>{fmt_dt(o.slot)}</b>"
    )


def admin_order_line(o: Order) -> str:
    return f"{o.slot.strftime('%H:%M')} №{o.id} {o.name} · {o.phone} · {o.service_name} — {o.status_text}"


def admin_help() -> str:
    return (
        "<b>Команды мастера</b>\n"
        "/today — записи на сегодня\n"
        "/tomorrow — записи на завтра\n"
        "/open — все незакрытые заявки\n"
        "/order 12 — карточка заявки №12 с кнопками статусов\n"
        "/note 12 текст — комментарий клиенту (придёт вместе со статусом)\n"
        "/move 12 2026-11-05 14:00 — перенести визит\n"
        "/block 2026-11-05 14:00 — закрыть слот\n"
        "/unblock 2026-11-05 14:00 — открыть слот\n"
        "/stats — счётчики по статусам"
    )
