"""Выгрузка заявок в Google Sheets. Необязательна: если ключи не заданы — no-op."""
from __future__ import annotations

import asyncio
import logging

from bot.db import Order
from bot.niches import DEFAULT_NICHE, Niche, get_niche

log = logging.getLogger(__name__)


def header(niche: Niche) -> list[str]:
    columns = ["ID", "Создана", niche.visit_label, "Статус", "Имя", "Телефон", "Услуга", niche.object_label,
               niche.problem_label, "Telegram", "Комментарий мастера"]
    return [*columns, "Адрес"] if niche.ask_address else columns


class SheetsExporter:
    def __init__(self, credentials_file: str, sheet_id: str, niche: Niche | None = None):
        self.enabled = bool(credentials_file and sheet_id)
        self.niche = niche or get_niche(DEFAULT_NICHE)
        self._ws = None
        if not self.enabled:
            return
        try:
            import gspread
            gc = gspread.service_account(filename=credentials_file)
            sh = gc.open_by_key(sheet_id)
            self._ws = sh.sheet1
            if not self._ws.row_values(1):
                self._ws.append_row(header(self.niche))
        except Exception as e:  # noqa: BLE001
            log.warning("Google Sheets недоступен, выгрузка отключена: %s", e)
            self.enabled = False

    def _row(self, o: Order, status_text: str) -> list[str]:
        row = [
            str(o.id), o.created_at.strftime("%d.%m.%Y %H:%M"), o.slot.strftime("%d.%m.%Y %H:%M"),
            status_text, o.name, o.phone, o.service_name, o.device, o.problem,
            f"@{o.username}" if o.username else str(o.user_id), o.admin_note,
        ]
        return [*row, o.address] if self.niche.ask_address else row

    async def upsert(self, o: Order) -> None:
        """Обновляет строку по ID или добавляет новую. В отдельном потоке, чтобы не блокировать бота.
        Демо-заявки в таблицу не попадают."""
        if not self.enabled or self._ws is None or o.demo:
            return
        try:
            await asyncio.to_thread(self._upsert_sync, o)
        except Exception as e:  # noqa: BLE001
            log.warning("Sheets upsert failed for order %s: %s", o.id, e)

    def _upsert_sync(self, o: Order) -> None:
        ids = self._ws.col_values(1)
        row = self._row(o, o.status_text)
        last_column = chr(ord("A") + len(row) - 1)
        try:
            idx = ids.index(str(o.id)) + 1
            self._ws.update(f"A{idx}:{last_column}{idx}", [row])
        except ValueError:
            self._ws.append_row(row)
