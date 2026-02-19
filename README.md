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

## Структура проекта

```text
orderflow-ai/
├── backend/                                  # Django backend
│   ├── manage.py                             # Точка входа management-команд
│   ├── requirements.txt                      # Python-зависимости backend
│   ├── Dockerfile                            # Сборка контейнера web/bot
│   ├── .dockerignore                         # Исключения для Docker build context
│   ├── config/                               # Django project config
│   │   ├── settings.py                       # Настройки приложения + env
│   │   ├── urls.py                           # Корневые URL, docs, dashboard, API
│   │   ├── asgi.py                           # ASGI entrypoint
│   │   └── wsgi.py                           # WSGI entrypoint
│   ├── orders/                               # Домен заказов
│   │   ├── models.py                         # Customer, IntakeMessage, Order и др.
│   │   ├── services.py                       # Бизнес-операции и status transitions
│   │   ├── state_machine.py                  # VALID_TRANSITIONS
│   │   ├── serializers.py                    # DRF сериализаторы заказов
│   │   ├── api_views.py                      # API endpoints заказов
│   │   ├── urls.py                           # Роутинг API orders
│   │   ├── admin.py                          # Django Admin конфигурация
│   │   └── management/commands/check_email.py # Email intake через IMAP
│   ├── ai_parser/                            # AI-парсинг свободного текста
│   │   ├── client.py                         # LLM-клиент (OpenAI/Mock)
│   │   ├── schemas.py                        # Pydantic-схемы извлечения
│   │   ├── validators.py                     # Пост-валидация и missing_fields
│   │   ├── prompts.py                        # Промпты primary parse/slot filling
│   │   └── services.py                       # Pipeline Intake -> Extraction -> Order
│   ├── bot/                                  # Telegram bot (aiogram)
│   │   ├── handlers.py                       # /start, сообщения, callback-кнопки
│   │   ├── keyboards.py                      # Inline клавиатуры
│   │   ├── notifications.py                  # Уведомления по статусам
│   │   └── management/commands/run_bot.py    # Запуск polling-бота
│   ├── dashboard/                            # Manager UI + storefront
│   │   ├── views.py                          # Dashboard/storefront/payment endpoints
│   │   ├── forms.py                          # Формы storefront
│   │   └── urls.py                           # Роутинг dashboard
│   ├── integrations/                         # Внешние интеграции
│   │   ├── bpium.py                          # Bpium API client
│   │   ├── sync.py                           # Sync order -> Bpium (upsert)
│   │   ├── payment.py                        # YooKassa create/get payment
│   │   └── delivery.py                       # Расчет доставки по тарифам
│   ├── templates/dashboard/                  # HTML-шаблоны витрины/дашборда/счета
│   └── tests/                                # Интеграционные и бизнес-тесты
├── docs/
│   └── prompts.md                            # Библиотека промптов проекта
├── scripts/
│   └── seed_data.py                          # Генератор демо-данных
├── docker-compose.yml                        # Оркестрация web/bot/db
├── .env.example                              # Шаблон переменных окружения
├── plan-v2.md                                # Актуальный спринт-план и чек-лист
└── README.md                                 # Документация проекта
```

## LLM провайдеры

AI-парсер переключается через env-переменную `LLM_PROVIDER`:
- `openai` - OpenAI API (по умолчанию при наличии `OPENAI_API_KEY`)
- `vllm` - локальный OpenAI-compatible endpoint (`VLLM_BASE_URL`)
- `yandexgpt` - YandexGPT API
- `gigachat` - GigaChat API
- `mock` - локальный mock-парсер (без внешнего API)

Примеры:

```env
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

```env
LLM_PROVIDER=yandexgpt
YANDEXGPT_API_KEY=...
YANDEXGPT_FOLDER_ID=...
YANDEXGPT_MODEL_NAME=yandexgpt-lite
```

```env
LLM_PROVIDER=gigachat
GIGACHAT_AUTH_KEY=...
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_SCOPE=GIGACHAT_API_PERS
```

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
