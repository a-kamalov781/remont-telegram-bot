"""Команды мастера. Доступны только ADMIN_IDS."""
from __future__ import annotations

from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from bot.config import Settings
from bot.db import DEMO_EVENT_FINISHED, Database
from bot.niches import get_niche, status_label
from bot.services.notify import Notifier

router = Router(name="admin")


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        return event.from_user is not None and event.from_user.id in settings.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


def _parse_dt(args: str) -> datetime | None:
    try:
        return datetime.strptime(args.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None


@router.message(Command("admin", "help"))
async def admin_help(m: Message):
    await m.answer(texts.admin_help())


async def _day(m: Message, db: Database, day: datetime, title: str):
    orders = await db.orders_for_day(day.date().isoformat())
    if not orders:
        await m.answer(f"{title}: записей нет.")
        return
    await m.answer(f"<b>{title}</b>\n" + "\n".join(texts.admin_order_line(o) for o in orders))


@router.message(Command("today"))
async def today(m: Message, db: Database):
    await _day(m, db, datetime.now(), "Сегодня")


@router.message(Command("tomorrow"))
async def tomorrow(m: Message, db: Database):
    await _day(m, db, datetime.now() + timedelta(days=1), "Завтра")


@router.message(Command("open"))
async def open_orders(m: Message, db: Database):
    orders = await db.open_orders()
    if not orders:
        await m.answer("Открытых заявок нет.")
        return
    lines = [f"{o.slot.strftime('%d.%m %H:%M')} №{o.id} {o.name} · {o.service_name} — {o.status_text}" for o in orders]
    await m.answer("<b>Открытые заявки</b>\n" + "\n".join(lines))


@router.message(Command("order"))
async def order_card(m: Message, command: CommandObject, db: Database):
    if not command.args or not command.args.strip().isdigit():
        await m.answer("Формат: /order 12")
        return
    o = await db.order(int(command.args))
    if not o:
        await m.answer("Заявка не найдена.")
        return
    await m.answer(texts.admin_order(o) + f"\n\nСтатус: {o.status_text}",
                   reply_markup=kb.admin_status_kb(o.preset, o.id, current=o.status if o.demo else None))


@router.message(Command("note"))
async def note(m: Message, command: CommandObject, db: Database, notifier: Notifier):
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await m.answer("Формат: /note 12 Нужна замена платы, срок 3 дня")
        return
    oid, text = int(parts[0]), parts[1].strip()
    o = await db.order(oid)
    if not o:
        await m.answer("Заявка не найдена.")
        return
    await db.set_status(oid, o.status, note=text)
    # Новая сумма — новый вопрос клиенту, прежний ответ больше не действует
    await db.set_quote_answer(oid, "")
    o = await db.order(oid)
    await notifier.status_changed(o)
    if not o.demo:
        await m.answer(f"Комментарий к №{oid} отправлен клиенту.")


@router.message(Command("move"))
async def move(m: Message, command: CommandObject, db: Database, notifier: Notifier):
    parts = (command.args or "").split(maxsplit=1)
    dt = _parse_dt(parts[1]) if len(parts) == 2 else None
    if not dt or not parts[0].isdigit():
        await m.answer("Формат: /move 12 2026-11-05 14:00")
        return
    oid = int(parts[0])
    o = await db.order(oid)
    if not o:
        await m.answer("Заявка не найдена.")
        return
    if not await db.slot_is_free(dt, o.user_id if o.demo else None):
        await m.answer("Этот слот занят или закрыт.")
        return
    await db.set_slot(oid, dt, status=o.preset.visit_status)
    await notifier.slot_moved(await db.order(oid))
    await m.answer(f"№{oid} перенесена на {dt.strftime('%d.%m %H:%M')}, клиент уведомлён.")


@router.message(Command("block"))
async def block(m: Message, command: CommandObject, db: Database):
    dt = _parse_dt(command.args or "")
    if not dt:
        await m.answer("Формат: /block 2026-11-05 14:00")
        return
    await db.block_slot(dt)
    await m.answer(f"Слот {dt.strftime('%d.%m %H:%M')} закрыт.")


@router.message(Command("unblock"))
async def unblock(m: Message, command: CommandObject, db: Database):
    dt = _parse_dt(command.args or "")
    if not dt:
        await m.answer("Формат: /unblock 2026-11-05 14:00")
        return
    await db.unblock_slot(dt)
    await m.answer(f"Слот {dt.strftime('%d.%m %H:%M')} открыт.")


@router.message(Command("stats"))
async def stats(m: Message, db: Database, settings: Settings):
    niche = get_niche(settings.niche)
    if settings.demo_mode:
        report = texts.demo_stats(await db.demo_stats(settings.admin_ids))
        real = await db.stats(demo=False)
        if real:
            lines = "\n".join(f"{status_label(k, niche)}: <b>{v}</b>" for k, v in real.items())
            report += f"\n\n<b>Заявки не из демо</b>\n{lines}"
        await m.answer(report)
        return
    st = await db.stats()
    if not st:
        await m.answer("Заявок ещё нет.")
        return
    await m.answer("\n".join(f"{status_label(k, niche)}: <b>{v}</b>" for k, v in st.items()))


@router.callback_query(F.data.startswith("adm:"))
async def admin_action(c: CallbackQuery, db: Database, notifier: Notifier, settings: Settings):
    _, action, oid_s = c.data.split(":")
    oid = int(oid_s)
    o = await db.order(oid)
    if not o:
        await c.answer("Заявка не найдена", show_alert=True)
        return
    niche = o.preset
    if action == "menu":
        await c.message.edit_reply_markup(reply_markup=kb.admin_status_kb(niche, oid))
        await c.answer()
        return
    status = niche.status(action)
    if status is None:
        await c.answer("Неизвестный статус", show_alert=True)
        return
    if action == o.status:
        await c.answer(f"Статус уже такой: {o.status_text}")
        return
    await db.set_status(oid, action)
    if status.approval:
        # Новое согласование начинается с чистого листа: сумма придёт через /note
        await db.set_quote_answer(oid, "")
    o = await db.order(oid)
    if o.demo:
        # Старая карточка гаснет, новая придёт внизу чата вместе с сообщением клиента
        await c.message.edit_text(texts.admin_order_with_status(o), reply_markup=None)
        if action == niche.final.code:
            await db.demo_event(o.user_id, niche.key, DEMO_EVENT_FINISHED, settings.now())
    await notifier.status_changed(o)
    if not o.demo:
        hint = f"\n\n{texts.quote_hint(o)}" if status.approval else ""
        await c.message.edit_text(texts.admin_order_with_status(o) + hint,
                                  reply_markup=kb.admin_status_kb(niche, oid))
    await c.answer(f"Клиенту отправлено: {o.status_text}")
