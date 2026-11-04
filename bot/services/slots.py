"""Логика слотов записи. Чистые функции, без БД — покрыты тестами."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


@dataclass(frozen=True)
class ScheduleConfig:
    work_start: time
    work_end: time
    slot_minutes: int
    work_days: tuple[int, ...]  # 0=пн ... 6=вс
    days_ahead: int


def working_dates(cfg: ScheduleConfig, today: date) -> list[date]:
    """Даты для записи: сегодня + days_ahead, только рабочие дни."""
    out: list[date] = []
    for i in range(cfg.days_ahead + 1):
        d = today + timedelta(days=i)
        if d.weekday() in cfg.work_days:
            out.append(d)
    return out


def all_slots(cfg: ScheduleConfig, d: date) -> list[datetime]:
    """Все слоты дня по расписанию (без учёта занятости)."""
    start = datetime.combine(d, cfg.work_start)
    end = datetime.combine(d, cfg.work_end)
    step = timedelta(minutes=cfg.slot_minutes)
    slots: list[datetime] = []
    cur = start
    while cur + step <= end:
        slots.append(cur)
        cur += step
    return slots


def free_slots(
    cfg: ScheduleConfig,
    d: date,
    taken: set[datetime],
    blocked: set[datetime],
    now: datetime,
) -> list[datetime]:
    """Свободные слоты: не занятые, не заблокированные, не в прошлом."""
    return [
        s for s in all_slots(cfg, d)
        if s not in taken and s not in blocked and s > now
    ]


def fmt_date(d: date) -> str:
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    return f"{d.strftime('%d.%m')} ({days[d.weekday()]})"


def fmt_dt(dt: datetime) -> str:
    return f"{fmt_date(dt.date())} {dt.strftime('%H:%M')}"
