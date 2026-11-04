from datetime import time

from bot.config import Settings


def test_settings_parse_comma_lists_from_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT_TOKEN=123456:ABC-DEF\n"
        "ADMIN_IDS=111,222\n"
        "WORK_START=10:00\n"
        "WORK_END=20:00\n"
        "WORK_DAYS=0,1,2,3,4,5,6\n",
        encoding="utf-8",
    )
    for name in ("BOT_TOKEN", "ADMIN_IDS", "WORK_START", "WORK_END", "WORK_DAYS"):
        monkeypatch.delenv(name, raising=False)

    s = Settings(_env_file=env_file)

    assert s.admin_ids == [111, 222]
    assert s.work_days == [0, 1, 2, 3, 4, 5, 6]
    assert s.work_end == time(20, 0)


def test_settings_parse_single_admin_id(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN=123456:ABC-DEF\nADMIN_IDS=111\n", encoding="utf-8")
    for name in ("BOT_TOKEN", "ADMIN_IDS"):
        monkeypatch.delenv(name, raising=False)

    assert Settings(_env_file=env_file).admin_ids == [111]
