"""Сумма в рублях: разбор из текста мастера и вывод. Чистые функции, без зависимостей."""
from __future__ import annotations

import re

MAX_PRICE = 9_999_999  # больше этого в тексте скорее телефон или госномер, а не сумма

_NUMBER = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?!\d)|\d+")
_CURRENCY_AFTER = re.compile(r"\s*(?:₽|руб|р\b)", re.IGNORECASE)


def parse_amount(text: str) -> int | None:
    """Сумма из текста: число с ₽/руб/р, а если такого нет — самое большое число. Нет суммы — None."""
    found: list[tuple[int, bool]] = []
    for match in _NUMBER.finditer(text):
        value = int(re.sub(r"\D", "", match.group()))
        if 0 < value <= MAX_PRICE:
            found.append((value, bool(_CURRENCY_AFTER.match(text, match.end()))))
    with_currency = [value for value, tagged in found if tagged]
    if with_currency:
        return with_currency[0]
    return max((value for value, _ in found), default=None)


def format_rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"
