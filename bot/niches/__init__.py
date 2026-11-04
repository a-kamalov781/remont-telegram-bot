"""Реестр пресетов ниш. Новая ниша — новый файл рядом и строка в NICHES."""
from __future__ import annotations

from bot.niches import appliance, atelier, autoservice, drycleaning, repair
from bot.niches.base import CANCELLED, Niche, ServicePreset, Status

NICHES: dict[str, Niche] = {
    p.key: p
    for p in (repair.PRESET, drycleaning.PRESET, atelier.PRESET, autoservice.PRESET, appliance.PRESET)
}
DEFAULT_NICHE = repair.PRESET.key

# Кнопки всех ниш: у посетителя демо может остаться клавиатура прежней ниши
BOOK_BUTTONS = frozenset(n.menu_book for n in NICHES.values())
STATUS_BUTTONS = frozenset(n.menu_status for n in NICHES.values())

# Статусы, в которых заявка занимает время. Порядок важен только для читаемости
ACTIVE_STATUSES: tuple[str, ...] = tuple(dict.fromkeys(
    s.code for n in NICHES.values() for s in n.statuses if s.holds_slot
))


def get_niche(key: str) -> Niche:
    """Пресет по ключу. Неизвестный ключ (старая строка в базе) — пресет по умолчанию."""
    return NICHES.get(key, NICHES[DEFAULT_NICHE])


def status_label(code: str, prefer: Niche | None = None) -> str:
    """Текст статуса для сводок, где заявки могут быть из разных ниш."""
    for niche in (prefer, *NICHES.values()):
        if niche is not None and niche.status(code):
            return niche.status_text(code)
    return code


__all__ = ["ACTIVE_STATUSES", "BOOK_BUTTONS", "CANCELLED", "DEFAULT_NICHE", "NICHES", "STATUS_BUTTONS",
           "Niche", "ServicePreset", "Status", "get_niche", "status_label"]
