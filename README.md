# OrderFlow AI

OrderFlow AI - омниканальная система обработки заказов для e-commerce.
Проект принимает заказы из Telegram, веб-витрины и email, извлекает структуру заказа из свободного текста, ведет заказ через state machine, синхронизирует данные с Bpium, поддерживает тестовую оплату через YooKassa sandbox и тестовый контур доставки через ApiShip.

## Текущий статус

- Спринты 0-10 реализованы на уровне кода, post-audit hardening (`Sprint 10B`) выполнен.
- Live-проверки интеграций выполнены: IMAP, Telegram bot, Bpium, YooKassa sandbox.
- Локальные тесты: `99` passing.
- Подтверждена accuracy на 50 кейсах: `100%` (GigaChat Pro), см. `docs/ai_accuracy_50_report.md`.
- Покрытие тестами: `81%` (coverage report), см. `docs/coverage_report.txt`.

## Навигация по документации

- Портфельный обзор репозитория: `PORTFOLIO_OVERVIEW.md`.
- Единый индекс документации: `docs/DOCUMENTATION_INDEX.md`.
- Пакет артефактов для куратора: `docs/curator_submission_checklist.md`.
- Reverse-engineered ТЗ: `docs/technical_assignment_mvp.md`.

## Стек

- Backend: Django 5, DRF, drf-spectacular
- AI parsing: OpenAI + Instructor + Pydantic + phonenumbers
- Bot: aiogram 3
- DB: PostgreSQL
- Frontend: Django templates + HTMX + Chart.js
- Integrations: Bpium API, YooKassa API, ApiShip API, IMAP

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
│   │   ├── client.py                         # Совместимый фасад LLM-клиентов
│   │   ├── llm/                              # Модули retry/normalization/providers
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
│   │   ├── apiship.py                        # ApiShip client + calculator/create/status sync
│   │   └── delivery.py                       # Расчет доставки (ApiShip + fallback тарифы)
│   ├── templates/dashboard/                  # HTML-шаблоны витрины/дашборда/счета
│   └── tests/                                # Интеграционные и бизнес-тесты
├── docs/
│   ├── prompts.md                            # Библиотека промптов проекта
│   ├── ai_accuracy_50_report.md              # Отчет accuracy на 50 кейсах
│   ├── coverage_report.txt                   # Отчет покрытия тестами
│   ├── fallbacks_log.md                      # Журнал сработавших fallback-сценариев
│   ├── demo_scenarios_abcd.md                # Сценарии A/B/C/D для защиты
│   ├── screenshots_manifest.md               # Манифест скриншотов для сдачи
│   ├── demo_video_script_5_7_min.md          # Сценарий записи демо 5-7 минут
│   ├── screenshots/                          # Скриншоты артефактов защиты
│   ├── demo_video/                           # Записанное демо-видео
│   ├── technical_assignment_mvp.md           # Уточненное ТЗ (reverse engineering)
│   └── datasets/ai_accuracy_50.json          # Набор из 50 тестовых заказов
├── scripts/
│   ├── seed_data.py                          # Генератор демо-данных
│   ├── benchmark_ru_models.py                # Бенчмарк/accuracy LLM
│   ├── capture_screenshots.mjs               # Автосъёмка скриншотов защиты
│   └── record_demo_video.mjs                 # Автозапись демо-видео (webm)
├── docker-compose.yml                        # Оркестрация web/bot/db/nginx
├── .env.demo.ru.example                      # Демо-профиль без OpenAI (RF cloud)
├── .env.example                              # Шаблон переменных окружения
├── PORTFOLIO_OVERVIEW.md                     # Быстрый гид по проекту для портфолио
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

Для `gigachat` используется `function calling` (`functions`) для structured extraction;
дополнительно включен safety-net: phone/email/address добираются regex из raw-текста, если модель вернула их пустыми.
Зафиксированный default-профиль по benchmark (S3-C12): локальный `vllm` (`Qwen/Qwen2.5-VL-7B-Instruct-AWQ`).
Резервный профиль: `gigachat` с baseline `GigaChat-2-Pro` и автоэскалацией в `GigaChat-2-Max`.

Quality-gateway и fallback-цепочка:
- Ответ модели проходит через строгую схему `OrderExtract` (Pydantic).
- Если ответ частично неконсистентный, применяется tolerant parsing (починка JSON + алиасы полей).
- Затем выполняется пост-валидация (`missing_fields`, нормализация телефона, проверка адреса/email).
- `missing_fields` пересчитывается по каноническим слотам (`items`, `delivery.address`, `customer.phone`, `customer.email`) и не принимает шумные произвольные ключи модели.
- Статус заказа определяется по качеству извлечения: при `missing_fields` -> `needs_info`, иначе `confirmed`.
- Для `gigachat` включена автоэскалация: `GigaChat-2-Pro` -> `GigaChat-2-Max` для сложных/рискованных случаев.
- Для `yandexgpt` включена автоэскалация: `yandexgpt-lite` -> `yandexgpt` для сложных/рискованных случаев.
- Для облачных провайдеров (`openai`, `yandexgpt`, `gigachat`) включены HTTP-retry с backoff по транзиентным ошибкам (429/5xx/timeout/connection reset).
- При сбоях внешних интеграций основной pipeline не падает (fallback-поведение).

Режим ускоренных сравнительных тестов (без изменения бизнес-логики):
- Можно включить shadow-eval и прогонять каждый intake сразу через несколько провайдеров.
- Основной провайдер формирует `Order`/статус как обычно; дополнительные результаты сохраняются только как `ExtractionAttempt` с префиксом `shadow:`.
- Shadow-attempts не участвуют в slot-filling контексте и не влияют на счётчик manual-review.

Примеры:

```env
LLM_PROVIDER=vllm
VLLM_BASE_URL=http://127.0.0.1:8000/v1
VLLM_API_KEY=EMPTY
VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ
```

```env
LLM_PROVIDER=yandexgpt
YANDEXGPT_API_KEY=...
YANDEXGPT_FOLDER_ID=...
YANDEXGPT_MODEL_NAME=yandexgpt-lite
# Обычно оставляется пустым, тогда URI строится автоматически:
# gpt://<YANDEXGPT_FOLDER_ID>/<YANDEXGPT_MODEL_NAME>/latest
# Для RC-канала можно явно задать .../rc
YANDEXGPT_MODEL_URI=
# Опционально: эскалация lite -> full
YANDEXGPT_ESCALATION_ENABLED=true
YANDEXGPT_ESCALATION_MODEL_NAME=yandexgpt
# Опционально: явный URI эскалации, например gpt://<FOLDER_ID>/yandexgpt/latest или .../rc
YANDEXGPT_ESCALATION_MODEL_URI=
YANDEXGPT_ESCALATION_TEXT_LEN=260
YANDEXGPT_ESCALATION_MISSING_FIELDS=2
```

```env
LLM_PROVIDER=gigachat
GIGACHAT_AUTH_KEY=...
GIGACHAT_MODEL=GigaChat-2-Pro
GIGACHAT_SCOPE=GIGACHAT_API_PERS
# Опционально: путь к .cer (если не установлен в trust store)
GIGACHAT_CERT_PATH=russian_trusted_root_ca.cer
# Опционально: эскалация сложных кейсов на Max
GIGACHAT_ESCALATION_ENABLED=true
GIGACHAT_ESCALATION_MODEL=GigaChat-2-Max
GIGACHAT_ESCALATION_TEXT_LEN=260
GIGACHAT_ESCALATION_MISSING_FIELDS=2
# Опционально: параллельный сравнительный прогон (shadow)
LLM_MULTI_EVAL_ENABLED=true
LLM_MULTI_EVAL_PROVIDERS=gigachat,yandexgpt,vllm
LLM_MULTI_EVAL_PARALLEL=true
LLM_MULTI_EVAL_MAX_WORKERS=3
# Shared retry policy for cloud providers
LLM_HTTP_MAX_RETRIES=2
LLM_HTTP_RETRY_BACKOFF_BASE=0.5
LLM_HTTP_RETRY_BACKOFF_MAX=4.0
LLM_HTTP_RETRY_STATUS_CODES=408,409,425,429,500,502,503,504
```

Где получить доступы GigaChat:
- Кабинет разработчика: `https://developers.sber.ru/studio/login`
- Для этого проекта нужен `GIGACHAT_AUTH_KEY` (credentials-token для заголовка `Authorization: Basic ...`).
- Поддерживаемые scope:
`GIGACHAT_API_PERS` (физлица), `GIGACHAT_API_B2B` (ИП/юрлица, платные пакеты), `GIGACHAT_API_CORP` (ИП/юрлица, pay-as-you-go).
- Для b2b-продукта в production обычно выбирают `GIGACHAT_API_B2B` или `GIGACHAT_API_CORP`.
- Для TLS можно либо установить сертификат Минцифры в trust store, либо указать `GIGACHAT_CERT_PATH`.
- Если в старом проекте были переменные `GIGACHAT_CLIENT_ID`/`GIGACHAT_CLIENT_SECRET`, в текущем коде они не используются напрямую.

Рекомендуемые парные профили (без смешивания классов):
- `quality`: `YANDEXGPT_MODEL_NAME=yandexgpt` + `GIGACHAT_MODEL=GigaChat-2-Max`
- `speed`: `YANDEXGPT_MODEL_NAME=yandexgpt-lite` + `GIGACHAT_MODEL=GigaChat-2`  
  (если `GigaChat-2-Lite` доступна в вашем аккаунте, используйте её)

Выбранный runtime-профиль (после benchmark `docs/benchmark_ru_models_report.md`):
- `default` (`dev/demo`): `LLM_PROVIDER=vllm`, `VLLM_MODEL=Qwen/Qwen2.5-VL-7B-Instruct-AWQ`
- `fallback` (операционный): переключить `LLM_PROVIDER=gigachat`,
`GIGACHAT_MODEL=GigaChat-2-Pro`, `GIGACHAT_ESCALATION_MODEL=GigaChat-2-Max`
- `shadow/резерв`: `yandexgpt-lite -> yandexgpt` (для параллельной оценки и сравнения)

Профиль для защиты без OpenAI:
- готовый шаблон: `.env.demo.ru.example`
- целевой режим: `LLM_PROVIDER=gigachat` (`GigaChat-2-Pro -> GigaChat-2-Max`)
- `OPENAI_API_KEY` оставляется пустым
- альтернатива для локального стенда: переключить на `LLM_PROVIDER=vllm`

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
- `nginx` (reverse proxy, внешний вход на `:8001`)
- `web` (Django + gunicorn, внутренний сервис)
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
- В MVP Bpium используется как внешний CRM-регистр (`CRM-sync`), а не как полнофункциональная CRM-платформа.
- Используется fallback: ошибки Bpium не ломают order pipeline.

### YooKassa (sandbox)

- В дашборде доступно создание ссылки на оплату.
- Есть ручной fallback: "Отметить как оплачено вручную".

### ApiShip (test delivery)

- При включении `APISHIP_ENABLED=true` расчет доставки идет через ApiShip `calculator`; при ошибках используется локальный fallback по тарифам.
- Для тестового контура используйте:
`APISHIP_BASE_URL=http://api.dev.apiship.ru/v1`,
`APISHIP_AUTH_PATH=/users/login`,
`APISHIP_AUTH_PREFIX=` (пусто),
`APISHIP_FROM_CITY` и `APISHIP_FROM_ADDRESS` (обязательны).
- Создание отправки отправляет `OrderRequest` на `APISHIP_ORDERS_PATH` (по умолчанию `/orders/sync`), автоматически подбирая `providerKey/tariffId` из `calculator`, если они не заданы через `APISHIP_PROVIDER_KEY` + `APISHIP_TARIFF_ID`.
- Калькулятору нужны габариты; по умолчанию используются `APISHIP_PLACE_LENGTH_CM=10`, `APISHIP_PLACE_WIDTH_CM=10`, `APISHIP_PLACE_HEIGHT_CM=10`.
- Если в заказе у позиции нет `price`, для оценки отправки подставляется `APISHIP_DEFAULT_ITEM_COST` (по умолчанию `1.00`).
- Поддержано создание тестовой отправки и сохранение полей доставки в `Order`: `shipping_provider`, `shipping_external_id`, `track_number`, `tracking_url`, `shipping_status_raw`, `shipping_synced_at`.
- Доступна команда синхронизации статусов:
`python manage.py sync_shipping_statuses --limit 50`

## Тесты

- `cd backend`
- `python manage.py test`
- Coverage:
  - `coverage run manage.py test --keepdb --noinput`
  - `coverage report`
  - последний отчёт: `docs/coverage_report.txt`

Покрыты:
- parser + validators
- state transitions
- idempotency
- multi-channel intake
- dashboard endpoints
- integration fallbacks

## Benchmark RU моделей

Скрипт сравнения RU/локальных моделей на едином наборе intake:

- `python scripts/benchmark_ru_models.py --include-vllm`
- Выбор конкретных таргетов: `--targets gigachat-pro` (или список через запятую)

Артефакты:
- `docs/benchmark_ru_models_report.md`
- `docs/benchmark_ru_models_report.json`
- Набор для Sprint 10 (50 заказов): `docs/datasets/ai_accuracy_50.json`
- Отчёт accuracy на 50 заказах: `docs/ai_accuracy_50_report.md` / `docs/ai_accuracy_50_report.json`

Метрики в отчете:
- `parse_success_rate` (`strict success`) - без ошибок и без `missing_fields` вообще
- `adjusted_success_rate` - без ошибок и без неожиданных пропусков; ожидаемый `missing` (когда поле реально отсутствует в исходном тексте) не считается ошибкой модели
- `missing_fields_rate` - доля кейсов с любыми пропусками
- `unexpected_missing_rate` - доля кейсов с пропусками, которых не должно было быть по исходному тексту
- `p95 latency`
- справочные `RUB/1000 токенов` (если заданы)

## Seed-данные

- `python scripts/seed_data.py`

Скрипт создает демо-заказы для витрины/дашборда.

## Ограничения текущей версии

- Для production-подключения YooKassa остаются организационные шаги онбординга (сайт/реквизиты).
- PDF формируется через WeasyPrint, при отсутствии зависимости используется HTML fallback.
- Для production нужны HTTPS, секреты в vault/CI secrets, и расширенная observability.

## Privacy-note

Проект хранит персональные данные клиентов (имя, телефон, email, адрес доставки) в PostgreSQL.
На защите используется профиль без OpenAI (`.env.demo.ru.example`):
- основной провайдер: `gigachat` (`GigaChat-2-Pro` + эскалация в `GigaChat-2-Max`);
- резервный локальный контур: `vllm` (без отправки данных во внешнее облако);
- `OPENAI_API_KEY` пустой в демо-профиле.

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
- Production-readiness трек (security/observability/backup+restore/RPO-RTO/pentest/vendor-SLA/support model):
`docs/production_readiness_roadmap.md`.
- UX/UI & CX трек (бот + storefront, KPI-driven улучшения):
`docs/ux_cx_roadmap.md`.

## Repository Standards

- `LICENSE`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `CODE_OF_CONDUCT.md`
- `SUPPORT.md`
- `CHANGELOG.md`

## Документы сдачи

- Уточненное техническое задание (reverse engineering):
`docs/technical_assignment_mvp.md`.
