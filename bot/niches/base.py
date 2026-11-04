"""Модель пресета ниши. Без зависимостей от остального кода бота."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Status:
    code: str
    text: str  # то, что видит клиент, и подпись кнопки у сотрудника
    holds_slot: bool = False  # пока заявка в этом статусе, её время занято
    approval: bool = False  # /note отправляет клиенту кнопки «Согласен» / «Перезвоните мне»


CANCELLED = Status("cancelled", "❌ Отменено")


@dataclass(frozen=True)
class ServicePreset:
    name: str
    description: str
    price_from: int


@dataclass(frozen=True)
class Niche:
    key: str
    name: str
    emoji: str
    demo_name: str  # название бизнеса в демо и значение по умолчанию
    demo_city: str  # адрес и телефон вымышленные, показываются только в демо
    demo_street: str
    demo_phone: str
    client_of: str  # «клиент химчистки» — для объяснения роли в демо
    staff_name: str  # кто работает с заявками: «мастер», «приёмщик», «мастер-приёмщик»
    services: tuple[ServicePreset, ...]
    statuses: tuple[Status, ...]  # первый — код new, последний — код done
    slot_minutes: int

    menu_book: str  # кнопка записи в меню
    menu_status: str  # кнопка статуса в меню
    book_prompt: str  # вопрос перед списком услуг
    welcome_points: tuple[str, ...]  # что умеет бот, для приветствия
    price_note: str  # примечание под ценами
    updates_text: str  # как клиент будет узнавать о статусах

    object_name: str  # «устройство» / «вещь» / «изделие» / «автомобиль»
    object_emoji: str
    object_prompt: str
    object_missing: str  # «устройство не указано»
    problem_label: str
    problem_prompt: str

    visit_label: str  # «Визит» / «Примерка» / «Выезд»
    reminder_wait: str  # «ждём вас» — в напоминании после времени

    ask_address: bool = False
    address_prompt: str = ""

    def _staff_case(self, ending: str) -> str:
        return "-".join(part + ending for part in self.staff_name.split("-"))

    @property
    def staff_dative(self) -> str:
        """«написать мастеру-приёмщику»"""
        return self._staff_case("у")

    @property
    def staff_genitive(self) -> str:
        """«команды мастера-приёмщика»"""
        return self._staff_case("а")

    @property
    def staff_title(self) -> str:
        return self.staff_name.capitalize()

    @property
    def demo_address(self) -> str:
        return f"{self.demo_city}, {self.demo_street}"

    @property
    def has_price(self) -> bool:
        """В нише согласуют стоимость, поэтому у заявки есть поле price."""
        return any(s.approval for s in self.statuses)

    @property
    def object_label(self) -> str:
        return self.object_name.capitalize()

    @property
    def all_statuses(self) -> tuple[Status, ...]:
        return (*self.statuses, CANCELLED)

    @property
    def final(self) -> Status:
        return self.statuses[-1]

    def next_status(self, code: str) -> Status | None:
        """Следующий шаг цепочки. После финального и отменённого статуса шага нет."""
        codes = [s.code for s in self.statuses]
        if code not in codes or code == self.final.code:
            return None
        return self.statuses[codes.index(code) + 1]

    @property
    def visit_status(self) -> str:
        """Статус заявки после переноса визита: последний из тех, что занимают время."""
        return [s.code for s in self.statuses if s.holds_slot][-1]

    def status(self, code: str) -> Status | None:
        return next((s for s in self.all_statuses if s.code == code), None)

    def status_text(self, code: str) -> str:
        found = self.status(code)
        return found.text if found else code

    def problems(self) -> list[str]:
        """Что не так с пресетом. Пустой список — пресет корректен."""
        out: list[str] = []
        codes = [s.code for s in self.all_statuses]
        if len(codes) != len(set(codes)):
            out.append("коды статусов повторяются")
        texts = [s.text for s in self.all_statuses]
        if len(texts) != len(set(texts)):
            out.append("тексты статусов повторяются")
        if len(self.statuses) < 3:
            out.append("слишком мало статусов")
        else:
            if self.statuses[0].code != "new":
                out.append("первый статус должен иметь код new")
            if self.statuses[-1].code != "done":
                out.append("последний статус должен иметь код done")
            if self.status("ready") is None:
                out.append("нет статуса готовности с кодом ready")
            if not self.statuses[0].holds_slot:
                out.append("новая заявка должна занимать время")
        if not self.services:
            out.append("нет услуг")
        for sv in self.services:
            if not sv.name.strip() or not sv.description.strip() or sv.price_from < 0:
                out.append(f"услуга заполнена неверно: {sv.name!r}")
        if len({sv.name for sv in self.services}) != len(self.services):
            out.append("названия услуг повторяются")
        if self.slot_minutes <= 0:
            out.append("slot_minutes должен быть больше нуля")
        for field in ("key", "name", "emoji", "demo_name", "demo_city", "demo_street", "demo_phone", "client_of",
                      "staff_name", "menu_book", "menu_status", "book_prompt",
                      "price_note", "updates_text", "object_name", "object_emoji", "object_prompt",
                      "object_missing", "problem_label", "problem_prompt", "visit_label",
                      "reminder_wait"):
            if not str(getattr(self, field)).strip():
                out.append(f"пустое поле {field}")
        if not self.welcome_points:
            out.append("нет пунктов приветствия")
        if any(not s.text.strip() for s in self.all_statuses):
            out.append("пустой текст статуса")
        if self.ask_address and not self.address_prompt.strip():
            out.append("нужен текст вопроса об адресе")
        return out
