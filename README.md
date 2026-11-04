# Бот для сервисного центра: запись + статус ремонта в Telegram

Клиент записывается на ремонт за 30 секунд и получает статус ремонта в Telegram — без звонков «готово ли?». Мастер управляет заявками кнопками прямо в чате.

**Демо-бот:** [@RemontPlusDemoBot](https://t.me/RemontPlusDemoBot)

## Что умеет

**Клиент**
- `📝 Записаться на ремонт` — услуга → день → свободное время → имя → телефон (кнопкой или вручную) → устройство → проблема → подтверждение
- `🔎 Статус моего ремонта` — последние заявки и их текущий статус
- `💰 Цены`, `📍 Адрес и контакты`
- автоматическое напоминание за N минут до визита
- уведомление при каждой смене статуса: принято → диагностика → ждём запчасти → в работе → **готово, забирайте**

**Мастер** (только из `ADMIN_IDS`)
- новая заявка приходит в личку с кнопками «Подтвердить / Отменить / Все статусы»
- `/today`, `/tomorrow`, `/open` — списки записей
- `/order 12` — карточка с кнопками всех статусов
- `/note 12 текст` — комментарий клиенту («нужна замена платы, 3 дня»)
- `/move 12 2026-11-05 14:00` — перенос визита, клиент уведомлён
- `/block` / `/unblock 2026-11-05 14:00` — закрыть слот (обед, выезд)
- `/stats` — счётчики

**Защита от ошибок**: слот нельзя занять дважды (проверка в момент выбора и в момент подтверждения), один телефон — одна запись на слот, прошедшие слоты не показываются, заблокированные — тоже.

**Google Sheets** (необязательно): каждая заявка и смена статуса дублируются в таблицу.

## Запуск за 3 команды

```bash
cp .env.example .env        # вписать BOT_TOKEN и ADMIN_IDS
pip install -r requirements.txt
python -m bot.main
```

Токен — у [@BotFather](https://t.me/BotFather). Свой Telegram ID — у [@userinfobot](https://t.me/userinfobot).

## Настройка под клиента — только .env

```
BUSINESS_NAME=«Ремонт Плюс»
BUSINESS_ADDRESS=Санкт-Петербург, Невский пр., 1
BUSINESS_PHONE=+7 (812) 000-00-00
WORK_START=10:00
WORK_END=19:00
SLOT_MINUTES=60
WORK_DAYS=0,1,2,3,4,5      # пн–сб
DAYS_AHEAD=7
REMIND_BEFORE_MINUTES=120
```

Услуги и цены — в таблице `services` базы (`data/bot.db`). Стартовый список задаётся в `bot/db.py` → `DEFAULT_SERVICES`; поменять до первого запуска или через любой SQLite-редактор.

## Деплой

### Docker (рекомендуется)
```bash
docker compose up -d --build
docker compose logs -f
```
База — в `./data`, переживает перезапуски.

### VPS без Docker (Ubuntu 22.04/24.04, 1 ГБ RAM хватает)
```bash
sudo useradd -r -m bot
sudo mkdir -p /opt/remont-bot && sudo chown bot:bot /opt/remont-bot
sudo -u bot bash -c 'cd /opt/remont-bot && git clone <repo> . && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cp .env.example .env'
# отредактировать /opt/remont-bot/.env
sudo cp deploy/remont-bot.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now remont-bot
sudo journalctl -u remont-bot -f
```

## Google Sheets (по желанию)
1. Google Cloud → создать сервисный аккаунт → скачать JSON в `credentials/service.json`.
2. Создать таблицу, дать доступ «Редактор» на email сервисного аккаунта.
3. В `.env`: `GOOGLE_CREDENTIALS_FILE=credentials/service.json`, `GOOGLE_SHEET_ID=<id из URL>`.

Если ключи не заданы — бот работает без таблицы.

## Тесты
```bash
pytest -q
```
22 теста: логика слотов, нормализация телефонов, БД (антидубль, блокировки, напоминания), чтение настроек из `.env`, полный сценарий записи через Dispatcher без сети.

## Структура
```
bot/
  main.py        — запуск, планировщик напоминаний
  config.py      — настройки из .env
  db.py          — SQLite, статусы, заявки, слоты
  keyboards.py   — кнопки
  texts.py       — все тексты в одном месте
  handlers/
    client.py    — сценарий клиента (FSM)
    admin.py     — команды и кнопки мастера
  services/
    slots.py     — расчёт свободных слотов (чистые функции)
    notify.py    — уведомления клиенту и мастеру
    sheets.py    — выгрузка в Google Sheets
tests/           — pytest
deploy/          — systemd unit
```

## Ограничения
- Состояние диалога (FSM) в памяти: при перезапуске бота незавершённая запись сбрасывается, заявки в базе не теряются.
- Один бот = одна точка. Для сети сервисов нужна таблица филиалов (доработка на 1–2 часа).
- Напоминания проверяются раз в 5 минут.
