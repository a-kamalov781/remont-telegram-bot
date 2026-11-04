"""Сумма в рублях: разбор из текста мастера и вывод. Чистые функции, без зависимостей."""
from __future__ import annotations

import re

MAX_PRICE = 9_999_999  # больше этого в тексте скорее телефон или госномер, а не сумма

_NUMBER = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?!\d)|\d+")
_CURRENCY_AFTER = re.compile(r"\s*(?:₽|руб(?:лей|ля|ль)?\b\.?|р\b\.?)", re.IGNORECASE)


def _pick(text: str) -> tuple[int, int, int] | None:
    """Число с ₽/руб/р, а если такого нет — самое большое. Возвращает (сумма, начало, конец вместе с валютой)."""
    found: list[tuple[int, int, int, bool]] = []
    for match in _NUMBER.finditer(text):
        value = int(re.sub(r"\D", "", match.group()))
        if 0 < value <= MAX_PRICE:
            currency = _CURRENCY_AFTER.match(text, match.end())
            found.append((value, match.start(), currency.end() if currency else match.end(), bool(currency)))
    tagged = [item for item in found if item[3]]
    best = tagged[0] if tagged else max(found, key=lambda item: item[0], default=None)
    return best[:3] if best else None


def parse_amount(text: str) -> int | None:
    picked = _pick(text)
    return picked[0] if picked else None


def parse_quote(text: str) -> tuple[int | None, str]:
    """«8 500 ₽, замена колодок» → (8500, «замена колодок»). Нет суммы — (None, весь текст)."""
    picked = _pick(text)
    if not picked:
        return None, text.strip()
    amount, start, end = picked
    comment = re.sub(r"\s+", " ", f"{text[:start]} {text[end:]}").strip(" ,.:;-–—")
    return amount, comment


def format_rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"
