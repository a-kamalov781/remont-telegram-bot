from __future__ import annotations

from datetime import datetime, time
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from bot.niches import DEFAULT_NICHE, NICHES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    # NoDecode: значения в .env — «1,2,3», а не JSON, разбирает _split_ints
    admin_ids: Annotated[list[int], NoDecode]

    niche: str = DEFAULT_NICHE
    demo_mode: bool = False
    demo_contact: str = ""

    # Пусто — название из пресета ниши
    business_name: str = ""
    business_address: str = ""
    business_phone: str = ""

    work_start: time = time(10, 0)
    work_end: time = time(19, 0)
    # Пусто — шаг из пресета ниши. В демо всегда берётся шаг выбранной ниши
    slot_minutes: int | None = None
    work_days: Annotated[list[int], NoDecode] = [0, 1, 2, 3, 4, 5]
    days_ahead: int = 7

    remind_before_minutes: int = 120

    google_credentials_file: str = ""
    google_sheet_id: str = ""

    db_path: str = "data/bot.db"
    tz: str = "Europe/Moscow"

    @field_validator("niche")
    @classmethod
    def _known_niche(cls, v: str) -> str:
        if v not in NICHES:
            raise ValueError(f"неизвестная ниша {v!r}, допустимо: {', '.join(NICHES)}")
        return v

    @field_validator("slot_minutes", mode="before")
    @classmethod
    def _empty_slot_minutes(cls, v):
        return None if v == "" else v

    @field_validator("admin_ids", "work_days", mode="before")
    @classmethod
    def _split_ints(cls, v):
        if isinstance(v, str):
            return [int(x) for x in v.replace(";", ",").split(",") if x.strip()]
        return v

    @field_validator("work_start", "work_end", mode="before")
    @classmethod
    def _parse_time(cls, v):
        if isinstance(v, str):
            h, m = v.split(":")
            return time(int(h), int(m))
        return v

    def now(self) -> datetime:
        """Текущее время в часовом поясе бизнеса, без tzinfo — как хранится в базе."""
        return datetime.now(ZoneInfo(self.tz)).replace(tzinfo=None)

    @property
    def sheets_enabled(self) -> bool:
        return bool(self.google_credentials_file and self.google_sheet_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
