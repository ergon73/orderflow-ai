# OrderFlow AI

OrderFlow AI - омниканальная система обработки заказов для e-commerce.
Проект принимает заказы из Telegram, веб-витрины и email, извлекает структуру заказа из свободного текста, ведет заказ через state machine, синхронизирует данные с Bpium и поддерживает тестовую оплату через YooKassa sandbox.

## Текущий статус

- Спринты 0-9 реализованы на уровне кода, часть задач спринта 10 закрыта.
- Live-проверки интеграций выполнены: IMAP, Telegram bot, Bpium, YooKassa sandbox.
- Локальные тесты: `30` passing.

## Стек

- Backend: Django 5, DRF, drf-spectacular
- AI parsing: OpenAI + Instructor + Pydantic + phonenumbers
- Bot: aiogram 3
- DB: PostgreSQL
- Frontend: Django templates + HTMX + Chart.js
- Integrations: Bpium API, YooKassa API, IMAP

## Архитектура (кратко)

- `IntakeMessage` хранит сырой входящий текст.
- `ExtractionAttempt` хранит попытки AI-парсинга.
- `Order` создается сразу после первого парсинга.
- `missing_fields` управляют переходом в `needs_info`.
- Slot filling работает поверх текущего `OrderExtract`.
- Все переходы статусов валидируются через `VALID_TRANSITIONS`.

## Запуск локально

1. Создать и активировать `.venv`.
2. Установить зависимости:
   - `pip install -r backend/requirements.txt`
3. Заполнить `.env` (можно начать с `.env.example`).
4. Применить миграции:
   - `cd backend`
   - `python manage.py migrate`
5. Создать superuser (опционально):
   - `python manage.py createsuperuser`
6. Запустить сервер:
   - `python manage.py runserver`

Полезные URL:
- `/health/`
- `/storefront/`
- `/dashboard/orders/`
- `/dashboard/stats/`
- `/api/docs/`
- `/admin/`

## Запуск в Docker

Требуется запущенный Docker Desktop.

- `docker compose up --build`

Приложение доступно на `http://127.0.0.1:8001/` (внешний порт `8001`).

Сервисы:
- `web` (Django)
- `bot` (aiogram polling)
- `db` (PostgreSQL)

## Telegram bot

Запуск без Docker:
- `cd backend`
- `python manage.py run_bot`

Обязателен `TELEGRAM_BOT_TOKEN`.
Если токен не задан, контейнер `bot` запускается в idle-режиме (без polling), чтобы общий стек не падал.

## Email intake

Команда:
- `cd backend`
- `python manage.py check_email`

Обязательны:
- `EMAIL_IMAP_HOST`
- `EMAIL_IMAP_PORT`
- `EMAIL_IMAP_MAILBOX`
- `EMAIL_LOGIN`
- `EMAIL_PASSWORD`

## Интеграции

### Bpium

- Синхронизация запускается при `confirmed` и важных сменах статуса.
- Primary storage остается PostgreSQL.
- Используется fallback: ошибки Bpium не ломают order pipeline.

### YooKassa (sandbox)

- В дашборде доступно создание ссылки на оплату.
- Есть ручной fallback: "Отметить как оплачено вручную".

## Тесты

- `cd backend`
- `python manage.py test`

Покрыты:
- parser + validators
- state transitions
- idempotency
- multi-channel intake
- dashboard endpoints
- integration fallbacks

## Seed-данные

- `python scripts/seed_data.py`

Скрипт создает демо-заказы для витрины/дашборда.

## Ограничения текущей версии

- Для production-подключения YooKassa остаются организационные шаги онбординга (сайт/реквизиты).
- PDF формируется через WeasyPrint, при отсутствии зависимости используется HTML fallback.
- Для production нужны HTTPS, секреты в vault/CI secrets, и расширенная observability.

## Privacy-note

Проект хранит персональные данные клиентов (имя, телефон, email, адрес доставки) в PostgreSQL.
Перед использованием в реальной среде нужно:
- иметь правовые основания обработки ПДн;
- ограничить доступ к данным;
- организовать хранение и ротацию секретов;
- настроить аудит и удаление данных по регламенту.

## Roadmap (post-MVP)

- Celery/Redis для асинхронного AI-парсинга.
- Полная интеграция callback/webhook для YooKassa.
- Ролевая модель менеджеров.
- Улучшенный мониторинг и алерты.
- Расширенные отчеты и SLA-метрики.
