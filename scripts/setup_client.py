"""Настройка бота под клиента: печатает готовый .env и что осталось сделать у @BotFather.
Ничего не записывает и никуда не отправляет.

Пример:
  python scripts/setup_client.py --niche drycleaning --name "«Химчистка на Литейном»" \\
      --address "Санкт-Петербург, Литейный пр., 10" --phone "+7 (812) 000-00-00" --start 10:00 --end 20:00
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.niches import NICHES, Niche  # noqa: E402
from bot.services.profile import (  # noqa: E402
    DESCRIPTION_LIMIT,
    NAME_LIMIT,
    SHORT_DESCRIPTION_LIMIT,
    Profile,
    business_profile,
)

ABOUT_LIMIT = SHORT_DESCRIPTION_LIMIT


@dataclass(frozen=True)
class Client:
    niche: Niche
    name: str
    address: str
    phone: str
    start: str
    end: str
    admin_ids: str = ""

    @property
    def profile(self) -> Profile:
        return business_profile(self.name, self.address, self.phone, self.start, self.end)


def env_block(c: Client) -> str:
    return "\n".join([
        "BOT_TOKEN=<токен от BotFather>",
        f"ADMIN_IDS={c.admin_ids or '<Telegram ID сотрудника, узнать у @userinfobot>'}",
        f"NICHE={c.niche.key}",
        "DEMO_MODE=false",
        f"BUSINESS_NAME={c.name}",
        f"BUSINESS_ADDRESS={c.address}",
        f"BUSINESS_PHONE={c.phone}",
        f"WORK_START={c.start}",
        f"WORK_END={c.end}",
    ])


def setabouttext_text(c: Client) -> str:
    return c.profile.short_description


def problems(c: Client) -> list[str]:
    p = c.profile
    out = []
    for label, text, limit in (("/setname", p.name, NAME_LIMIT),
                               ("/setdescription", p.description, DESCRIPTION_LIMIT),
                               ("/setabouttext", p.short_description, ABOUT_LIMIT)):
        if len(text) > limit:
            out.append(f"{label}: {len(text)} символов при лимите {limit}, бот обрежет текст. Сократите данные в .env")
    return out


def checklist(c: Client) -> str:
    p = c.profile
    return "\n".join([
        "Создайте бота у @BotFather и возьмите токен.",
        "",
        "/setname, /setdescription и /setabouttext вручную не нужны: при каждом запуске бот заполнит профиль",
        "сам из .env, и ручные правки этих полей будут заменены. Вот что он запишет:",
        "",
        "Название:",
        p.name,
        "",
        "Описание, клиент видит его до нажатия «Старт»:",
        p.description,
        "",
        "Короткое описание:",
        p.short_description,
        "",
        "Вручную остаётся один шаг у @BotFather:",
        "/setuserpic: отправьте логотип клиента, лучше квадратный",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Готовый .env и шаги BotFather для нового клиента")
    parser.add_argument("--niche", required=True, choices=sorted(NICHES))
    parser.add_argument("--name", required=True, help="название бизнеса, например «Химчистка на Литейном»")
    parser.add_argument("--address", required=True, help="с городом: по нему строится ссылка на карту")
    parser.add_argument("--phone", default="")
    parser.add_argument("--start", default="10:00")
    parser.add_argument("--end", default="19:00")
    parser.add_argument("--admin-ids", default="")
    args = parser.parse_args(argv)

    client = Client(NICHES[args.niche], args.name, args.address, args.phone, args.start, args.end, args.admin_ids)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("=== .env ===")
    print(env_block(client))
    print("\n=== BotFather ===")
    print(checklist(client))
    print(f"\n=== Услуги и цены ===\nДо первого запуска поправьте их в bot/niches/{client.niche.key}.py")
    found = problems(client)
    for problem in found:
        print(f"⚠️ {problem}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
