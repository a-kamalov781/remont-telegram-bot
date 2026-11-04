from datetime import date, datetime, time

from bot.services.slots import ScheduleConfig, all_slots, free_slots, working_dates

CFG = ScheduleConfig(work_start=time(10, 0), work_end=time(19, 0), slot_minutes=60,
                     work_days=(0, 1, 2, 3, 4, 5), days_ahead=7)


def test_all_slots_count_and_bounds():
    s = all_slots(CFG, date(2026, 11, 4))
    assert len(s) == 9
    assert s[0].time() == time(10, 0)
    assert s[-1].time() == time(18, 0)  # последний слот 18:00–19:00


def test_half_hour_slots():
    cfg = ScheduleConfig(time(9, 0), time(12, 0), 30, (0,), 1)
    assert len(all_slots(cfg, date(2026, 11, 2))) == 6


def test_working_dates_skips_sunday():
    # 2026-11-01 — воскресенье
    ds = working_dates(CFG, date(2026, 11, 1))
    assert date(2026, 11, 1) not in ds
    assert date(2026, 11, 2) in ds
    assert all(d.weekday() != 6 for d in ds)
    assert len(ds) == 6  # окно 1–8 ноября = 8 дней, два воскресенья (1 и 8) выпадают


def test_free_slots_excludes_taken_blocked_and_past():
    d = date(2026, 11, 4)
    now = datetime(2026, 11, 4, 12, 30)
    taken = {datetime(2026, 11, 4, 14, 0)}
    blocked = {datetime(2026, 11, 4, 15, 0)}
    s = free_slots(CFG, d, taken, blocked, now)
    times = [x.time() for x in s]
    assert time(10, 0) not in times and time(12, 0) not in times  # прошлое
    assert time(13, 0) in times
    assert time(14, 0) not in times  # занят
    assert time(15, 0) not in times  # закрыт
    assert time(18, 0) in times


def test_free_slots_other_day_not_affected_by_now():
    d = date(2026, 11, 5)
    now = datetime(2026, 11, 4, 18, 59)
    assert len(free_slots(CFG, d, set(), set(), now)) == 9
