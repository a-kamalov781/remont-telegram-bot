"""Настройка бота под клиента: печатает готовый .env и шаги для @BotFather. Ничего не записывает и никуда не отправляет.

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

# Лимиты Telegram на профиль бота
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 512
ABOUT_LIMIT = 120


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
    def plain_name(self) -> str:
        return self.name.strip("«»\"' ")

    @property
    def hours(self) -> str:
        return f"{self.start}–{self.end}"


def env_block(c: Client) -> str:
    return "\n".join([
        "BOT_TOKEN=<токен от BotFather>",
        f"ADMIN_IDS={c.admin_ids or '<Telegram ID мастера, узнать у @userinfobot>'}",
        f"NICHE={c.niche.key}",
        "DEMO_MODE=false",
        f"BUSINESS_NAME={c.name}",
        f"BUSINESS_ADDRESS={c.address}",
        f"BUSINESS_PHONE={c.phone}",
        f"WORK_START={c.start}",
        f"WORK_END={c.end}",
    ])


def setname_text(c: Client) -> str:
    return c.plain_name


def setdescription_text(c: Client) -> str:
    lines = [c.plain_name, f"📍 {c.address}", f"🕒 {c.hours}"]
    if c.phone:
        lines.append(f"📞 {c.phone}")
    lines += ["", "Запись, статус заказа и вопрос мастеру прямо в этом чате. Нажмите «Старт»."]
    return "\n".join(lines)


def setabouttext_text(c: Client) -> str:
    return f"{c.address}, {c.hours}"


def problems(c: Client) -> list[str]:
    out = []
    for label, text, limit in (("/setname", setname_text(c), NAME_LIMIT),
                               ("/setdescription", setdescription_text(c), DESCRIPTION_LIMIT),
                               ("/setabouttext", setabouttext_text(c), ABOUT_LIMIT)):
        if len(text) > limit:
            out.append(f"{label}: {len(text)} символов при лимите {limit}, сократите текст")
    return out


def checklist(c: Client) -> str:
    return "\n".join([
        "В @BotFather выберите бота и отправьте команды, чтобы в профиле сразу было видно, чей он:",
        "",
        "1. /setname",
        setname_text(c),
        "",
        "2. /setdescription (адрес и часы, клиент видит это до нажатия «Старт»)",
        setdescription_text(c),
        "",
        "3. /setabouttext",
        setabouttext_text(c),
        "",
        "4. /setuserpic: отправьте логотип клиента, лучше квадратный",
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
