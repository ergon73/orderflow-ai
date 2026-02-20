# Plan Реализации OrderFlow AI (v2.1)

Этот файл одновременно является:
- поэтапным планом реализации;
- рабочим TODO-листом;
- чек-листом контрольных проверок.

Профиль проекта для `v2.1`:
- расширенный MVP: 3 канала (`Telegram`, `web`, `email`);
- CRM-интеграция: `Bpium` (вместо Google Sheets);
- тестовая оплата: `YooKassa sandbox` + fallback;
- расчёт доставки: локальная таблица тарифов;
- AI-контур: мульти-провайдерный (`openai`, `vllm`, `yandexgpt`, `gigachat`, `mock`) с возможностью РФ/локального режима;
- статусы: 8 (`new`, `needs_info`, `confirmed`, `in_progress`, `shipped`, `delivered`, `cancelled`, `returned`).

Правила работы с планом:
- отмечать выполненные пункты `[x]`;
- выполнять спринты строго по порядку;
- переходить к следующему спринту только после прохождения проверок текущего.

---

## Ключевые архитектурные решения (зафиксировано)

- [x] `ARCH-01` `Order` создаётся сразу после первого парсинга intake (даже если данных не хватает).
- [x] `ARCH-02` Неполные данные -> статус `needs_info`; подтверждение клиента переводит в `confirmed`.
- [x] `ARCH-03` Для ручной эскалации используется флаг `needs_manual_review`, а не новый статус.
- [x] `ARCH-04` Slot filling всегда привязан к конкретному `order_id`/`intake_id`, не к "последнему заказу клиента".
- [x] `ARCH-05` PostgreSQL остаётся primary storage; Bpium используется как CRM-синхронизация.

---

## Глобальные гейты проекта

- [x] `GATE-1` (конец Спринта 4): сквозной поток `Telegram -> AI -> Order в БД/Admin` работает стабильно.
- [x] `GATE-2` (конец Спринта 7): сценарий `NEEDS_INFO + Slot Filling` закрыт без потери данных.
- [x] `GATE-3` (конец Спринта 10): проект готов к сдаче по DoD.

Точка переключения на резерв (PyDocFlow): если `GATE-1` не закрыт к концу дня 4.

---

## Спринт 0. Подготовка и фиксация рамок (День 0)

Цель: подготовить окружение и зафиксировать расширенный scope.

### TODO
- [x] `S0-01` Зафиксировать scope расширенного MVP: Telegram + веб-витрина + email, Bpium, YooKassa sandbox, тарифная доставка.
- [x] `S0-02` Зафиксировать единую state machine (8 статусов + `VALID_TRANSITIONS`).
- [x] `S0-03` Создать структуру репозитория: `backend`, `docs`, `scripts`, `nginx`.
- [x] `S0-04` Подготовить `.env.example`:
`OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `SECRET_KEY`, `BPIUM_BASE_URL`, `BPIUM_LOGIN`, `BPIUM_PASSWORD`, `BPIUM_CATALOG_ID`, `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET`, `EMAIL_IMAP_HOST`, `EMAIL_IMAP_PORT`, `EMAIL_LOGIN`, `EMAIL_PASSWORD`.
- [x] `S0-05` Подготовить `.gitignore` (Python, Docker, env, IDE, cache).
- [x] `S0-06` Подготовить `.cursorrules` (Django conventions, структура apps, стиль кода, запрет лишних зависимостей).
- [x] `S0-07` Проверить доступ к ключам/токенам и внешним сервисам.
- [x] `S0-08` Для `GigaChat` скачать и установить сертификат Минцифры (`.cer`) в доверенные сертификаты ОС/контейнера, зафиксировать шаги установки в документации окружения.

### Проверки
- [x] `S0-C1` `docker --version` и `docker compose version` выполняются без ошибок.
- [x] `S0-C2` Пробный скрипт с `instructor`, `openai`, `pydantic` запускается.
- [x] `S0-C3` Создан каркас каталогов и базовые конфиги.
- [x] `S0-C4` `.env.example` покрывает все интеграции расширенного MVP.
- [x] `S0-C5` Тестовый TLS-запрос к `GigaChat` (OAuth/API) проходит с включенной проверкой сертификата (`GIGACHAT_VERIFY_SSL=true`).

Критерий завершения: инфраструктурные и интеграционные предпосылки готовы.

---

## Спринт 1. Фундамент проекта и инфраструктура (День 1)

Цель: поднять Django + PostgreSQL в Docker без интеграционного перегруза.

### TODO
- [x] `S1-01` Инициализировать Django-проект в `backend/`.
- [x] `S1-02` Подключить PostgreSQL в settings через env.
- [x] `S1-03` Добавить `docker-compose.yml` (`web`, `db`), healthcheck для `db`.
- [x] `S1-04` Добавить `backend/Dockerfile`.
- [x] `S1-05` Подключить минимальные зависимости ядра: `Django`, `djangorestframework`, `psycopg2-binary`, `python-dotenv`.
- [x] `S1-06` Настроить базовые URL + health endpoint.
- [x] `S1-07` Создать superuser и проверить Admin.

### Проверки
- [x] `S1-C1` `docker compose up --build` стартует без ошибок.
- [x] `S1-C2` Миграции применяются.
- [x] `S1-C3` Admin доступен.

Критерий завершения: базовая платформа запускается одной командой.

---

## Спринт 2. Доменная модель и админка (День 2)

Цель: реализовать согласованную модель данных под расширенный MVP.

### TODO
- [x] `S2-01` Создать app `orders`.
- [x] `S2-02` Реализовать модели: `Customer`, `IntakeMessage`, `ExtractionAttempt`, `Order`, `OrderItem`, `OrderStatusHistory`.
- [x] `S2-03` В `Order` добавить поля: `delivery_cost`, `is_paid`, `paid_at`, `track_number`, `needs_manual_review`, `bpium_record_id`.
- [x] `S2-04` Зафиксировать 8 статусов в `Order.Status` и `VALID_TRANSITIONS` (без `requires_manual_review` как статуса).
- [x] `S2-05` `idempotency_key` (unique) для всех каналов:
`tg_{chat_id}_{message_id}`, `web_{uuid4}`, `email_{mailbox}_{uidvalidity}_{uid}`.
- [x] `S2-06` Поддержать каналы: `telegram`, `web`, `email`.
- [x] `S2-07` Добавить индексы:
`Order(status, created_at)`, `Order(customer_id, created_at)`, `IntakeMessage(customer_id, created_at)`.
- [x] `S2-08` Настроить Admin: `list_display`, `list_filter`, `search_fields`, статус и флаг ручной проверки.
- [x] `S2-09` Создать и применить миграции.

### Проверки
- [x] `S2-C1` Все модели доступны в Admin.
- [x] `S2-C2` Уникальность `idempotency_key` подтверждена.
- [x] `S2-C3` В статусах доступны все 8 состояний.
- [x] `S2-C4` `needs_manual_review` и `bpium_record_id` доступны в модели и админке.

Критерий завершения: модель данных согласована с жизненным циклом и интеграциями.

---

## Спринт 3. AI-парсинг и пост-валидация (День 3)

Цель: стабильный и детерминированный pipeline извлечения данных.

### TODO
- [x] `S3-01` Создать app `ai_parser`.
- [x] `S3-02` Описать Pydantic-схемы:
`OrderExtract` (включая `chain_of_thought`, `confidence`, `missing_fields`, `clarifying_questions`), `OrderItem`, `CustomerInfo`, `DeliveryInfo`.
- [x] `S3-03` Добавить валидаторы (`qty >= 1`, `0 <= confidence <= 1`).
- [x] `S3-04` Реализовать `LLMClient` (ABC), `InstructorOpenAIClient`, `MockLLMClient`.
- [x] `S3-05` Добавить prompt для первичного извлечения и prompt для slot filling с guardrail на сохранение уже распознанных данных.
- [x] `S3-06` Реализовать `validators.py`: телефон (E.164), минимальная валидность address/items, заполнение `missing_fields`.
- [x] `S3-07` Реализовать сервис:
`IntakeMessage -> LLM -> пост-валидация -> ExtractionAttempt -> (создать/обновить Order)`.
- [x] `S3-08` Логика гейта: решение `needs_info/confirmed` принимается по `missing_fields` после пост-валидации.
- [x] `S3-09` Добавить unit-тесты парсера (>=10 кейсов).
- [x] `S3-10` Добавить мульти-провайдерный LLM-режим (`openai`, `vllm`, `yandexgpt`, `gigachat`, `mock`) через `LLM_PROVIDER`.
- [x] `S3-11` Прокинуть env-конфигурацию провайдеров в `.env.example` и `docker-compose.yml`.
- [x] `S3-12` Добавить unit-тесты выбора провайдера и fallback-логики инициализации.
- [x] `S3-13` Добавить РФ/локальный AI-контур: единый интерфейс для `vllm` (локально), `yandexgpt`, `gigachat` без изменения бизнес-логики заказа.
- [x] `S3-14` Отразить в документации и env-профилях как переключиться с OpenAI на локальный/RU-провайдер.
- [x] `S3-15` Зафиксировать правило парности классов для RU-LLM: использовать согласованные профили (`max/max` или `lite/lite`) для `YandexGPT` и `GigaChat`, без mixed-пары.
- [x] `S3-16` Для `GigaChat` внедрить structured extraction через `functions` (function calling) и tolerant fallback-парсер для нестабильного JSON-ответа.
- [x] `S3-17` Добавить safety-net извлечения из raw текста (phone/email/address) перед пост-валидацией, чтобы частично пустые ответы LLM не роняли intake.
- [x] `S3-18` Добавить ускоренный режим тестов `LLM_MULTI_EVAL`: один intake -> параллельные shadow-прогоны через несколько провайдеров (`gigachat`/`yandexgpt`/`vllm`) без влияния на основной pipeline.
- [x] `S3-19` Добавить автоэскалацию `YandexGPT` в сложных/рискованных кейсах: `yandexgpt-lite -> yandexgpt`, включая fallback при ошибке базовой модели.
- [x] `S3-20` Провести сравнительный benchmark RU-моделей на проектном датасете intake: `yandexgpt-lite`, `yandexgpt`, `gigachat-pro`, `gigachat-max` (метрики: parse_success_rate, missing_fields_rate, стоимость/1000 токенов, p95 latency).
- [x] `S3-21` Зафиксировать итоговую `default`-модель и fallback-матрицу в `.env.example` и `README` на основе benchmark (отдельно для `dev` и `demo/prod` профилей).
- [x] `S3-22` Подготовить fallback-решение, если Yandex-профиль не проходит quality-gate: переключение `LLM_PROVIDER` на `gigachat` без изменения бизнес-логики.
- [x] `S3-23` Зафиксировать временный default до завершения benchmark: `GigaChat-2-Pro` как baseline + `GigaChat-2-Max` как escalation; `YandexGPT` использовать в shadow/сравнительном режиме.
- [x] `S3-24` Для локального `vllm` добавить fallback-режим парсинга без function/tool-calling (raw JSON), чтобы pipeline работал даже без `--tool-call-parser`.
- [x] `S3-25` Нормализовать `missing_fields` к каноническому набору слотов (`items`, `delivery.address`, `customer.phone`, `customer.email`) перед расчётом quality-gate и benchmark, чтобы убрать шум от LLM-списков.
- [x] `S3-26` Пересчитать benchmark-метрики с учетом ожидаемых пропусков (`expected_missing`) и добавить `adjusted_success_rate`, чтобы ожидаемый `missing` не считался ошибкой модели.
- [x] `S3-27` Добавить единый retry-политики для облачных LLM (`openai`, `yandexgpt`, `gigachat`) с backoff и retry по транзиентным HTTP/network-ошибкам; вынести настройки в `.env`.

### Проверки
- [x] `S3-C1` Парсер возвращает валидный объект на тестовом наборе.
- [x] `S3-C2` Неполные данные попадают в `missing_fields`.
- [x] `S3-C3` Телефоны корректно нормализуются или помечаются как отсутствующие.
- [x] `S3-C4` Невалидные `qty/confidence` отлавливаются валидаторами.
- [x] `S3-C5` Тесты парсера проходят стабильно.
- [x] `S3-C6` Переключение LLM-провайдера через env работает без изменений бизнес-логики.
- [x] `S3-C7` Выполнен живой smoke-тест intake без OpenAI (через `vllm` или `yandexgpt`/`gigachat`) в текущем окружении.
- [x] `S3-C8` Проверен запуск обоих RU-профилей конфигурации: `quality (max/max)` и `speed` (для GigaChat в текущем аккаунте использована доступная speed-модель `GigaChat-2`, т.к. `GigaChat-2-Lite` не возвращается в `/models`).
- [x] `S3-C9` Выполнен живой smoke-тест `GigaChat` с function calling (OAuth + chat completion + разбор в `OrderExtract`).
- [x] `S3-C10` Shadow-attempts не влияют на базовую логику: не участвуют в slot-filling контексте и не ускоряют триггер `manual_review`.
- [x] `S3-C11` Unit-тестами подтверждён fallback/эскалация для `YandexGPT`: переход с `lite` на `full` по сложности и при ошибке парсинга.
- [x] `S3-C12` По итогам benchmark выбран и зафиксирован дефолтный runtime-профиль модели (`baseline + escalation`) с аргументацией по цене/качеству.
- [x] `S3-C13` Выполнен live smoke-тест локальной модели `vllm` (`Qwen/Qwen2.5-VL-7B-Instruct-AWQ`): intake успешно переходит в `confirmed` с заполненными items/phone/email/address.
- [x] `S3-C14` Сформирован benchmark-отчёт и артефакты (`docs/benchmark_ru_models_report.md`, `docs/benchmark_ru_models_report.json`).
- [x] `S3-C15` В benchmark-отчёте явно разделены `strict success` и `adjusted success`; ожидаемые пропуски из исходного текста не учитываются как ошибка качества модели.
- [x] `S3-C16` Retry для облачных LLM подтверждён тестами: транзиентные сетевые/HTTP ошибки переживаются и запрос успешно повторяется.

Критерий завершения: качество извлечения достаточно для запуска боевого intake.

---

## Спринт 4. Telegram-бот и первый вертикальный срез (День 4)

Цель: закрыть обязательный поток от сообщения к заказу.

### TODO
- [x] `S4-01` Создать app `bot` + management command `run_bot`.
- [x] `S4-02` Реализовать `/start` и обработку текстовых сообщений.
- [x] `S4-03` Добавить inline-кнопки: `Подтвердить`, `Исправить`, `Отменить`.
- [x] `S4-04` В `callback_data` передавать `order_id`, чтобы не путать параллельные заказы.
- [x] `S4-05` Реализовать `orders/services.py` с `@transaction.atomic`.
- [x] `S4-06` Убедиться, что `Order` создаётся сразу после первого parse; подтверждение меняет статус, но не создаёт второй заказ.
- [x] `S4-07` Реализовать idempotency для Telegram (`tg_{chat_id}_{message_id}`).
- [x] `S4-08` Добавить `bot`-сервис в docker-compose (`depends_on: db`).
- [x] `S4-09` Логировать этапы: intake, extract, create_order, confirm, status_change.

### Проверки
- [x] `S4-C1` Сообщение в боте создаёт записи `IntakeMessage`, `ExtractionAttempt`, `Order`.
- [x] `S4-C2` Повтор webhook не создаёт дубль.
- [x] `S4-C3` Подтверждение/отмена работают по правильному `order_id`.
- [x] `S4-C4` `docker compose up` поднимает `web` и `bot`.

Критерий завершения: `GATE-1` закрыт.

---

## Спринт 5. Веб-витрина, email-канал и API-документация (Дни 5-6)

Цель: закрыть полный intake по 3 каналам и базовую API-документацию.

### TODO
- [x] `S5-01` Реализовать веб-витрину (`storefront`) с карточками товаров + свободный текст.
- [x] `S5-02` Добавить валидацию формы (клиент/сервер).
- [x] `S5-03` Подключить единый pipeline (`Intake -> Extraction -> Order`) для `channel='web'`.
- [x] `S5-04` Реализовать idempotency для веб-формы (`web_{uuid4}`).
- [x] `S5-05` Реализовать email ingestion: management command `check_email` (IMAP -> IntakeMessage).
- [x] `S5-06` Реализовать idempotency для email (`email_{mailbox}_{uidvalidity}_{uid}`).
- [x] `S5-07` Подключить `drf-spectacular`, добавить `/api/docs/`.
- [x] `S5-08` Добавить smoke-тесты для Telegram/web/email intake.

### Проверки
- [x] `S5-C1` Заказ из веб-витрины создаётся корректно.
- [x] `S5-C2` Заказ из email создаётся корректно.
- [x] `S5-C3` По всем каналам одинаковые правила парсинга и статусов.
- [x] `S5-C4` Swagger доступен и отражает основные endpoints.

Критерий завершения: intake полностью омниканальный (3 канала).

---

## Спринт 6. Дашборд менеджера v1 (Дни 7-8)

Цель: дать менеджеру рабочий UI для операционной работы.

### TODO
- [x] `S6-01` Таблица заказов, фильтры (статус/дата/канал), поиск.
- [x] `S6-02` Карточка заказа: детали, исходный текст, история статусов, флаг ручной проверки.
- [x] `S6-03` Inline-смена статуса через HTMX.
- [x] `S6-04` Валидация переходов только через `VALID_TRANSITIONS`.
- [x] `S6-05` Оптимизация ORM: `select_related/prefetch_related` для списка и карточки.
- [x] `S6-06` Добавить кнопку "Оплачено вручную" как fallback-операцию менеджера.

### Проверки
- [x] `S6-C1` Фильтры и поиск дают корректный результат.
- [x] `S6-C2` Невалидные переходы блокируются.
- [x] `S6-C3` Каждое изменение статуса пишется в `OrderStatusHistory`.
- [x] `S6-C4` Интерфейс остаётся отзывчивым (<2 секунд визуально на демо-данных).

Критерий завершения: менеджер может полноценно вести заказы через UI.

---

## Спринт 7. NEEDS_INFO, Slot Filling и антизацикливание (День 9)

Цель: закрыть сложный диалоговый сценарий без потери контекста.

### TODO
- [x] `S7-01` При `missing_fields` -> `needs_info`, заказ остаётся тем же.
- [x] `S7-02` Slot filling выполняется строго по `order_id` (из callback/контекста диалога).
- [x] `S7-03` Каждая итерация сохраняется как новый `ExtractionAttempt`.
- [x] `S7-04` Кнопка `Исправить` обновляет уже заполненные поля только по явной просьбе клиента.
- [x] `S7-05` Лимит попыток: >3 неудачных attempts -> `needs_manual_review=True`, бот завершает цикл и сообщает о ручной обработке.
- [x] `S7-06` Уведомления в Telegram о смене статуса заказа.
- [x] `S7-07` Тесты: неполный заказ, правка заказа, два параллельных заказа одного клиента.

### Проверки
- [x] `S7-C1` Сценарий slot filling проходит end-to-end.
- [x] `S7-C2` Товары/адрес не "забываются" между итерациями.
- [x] `S7-C3` Параллельные заказы не смешивают контекст.
- [x] `S7-C4` После лимита попыток выставляется `needs_manual_review`, цикл останавливается.

Критерий завершения: `GATE-2` закрыт.

---

## Спринт 8. Аналитика и документы (День 10)

Цель: реализовать визуализацию и документы для демонстрации.

### TODO
- [x] `S8-01` Статистика по заказам (по дням/статусам/каналам).
- [x] `S8-02` Графики Chart.js.
- [x] `S8-03` Генерация PDF-счёта.
- [x] `S8-04` Fallback для PDF: при проблемах WeasyPrint использовать `reportlab` или HTML-счёт.
- [x] `S8-05` Экспорт CSV.

### Проверки
- [x] `S8-C1` Графики отображаются корректно.
- [x] `S8-C2` Счёт скачивается и содержит ключевые поля.
- [x] `S8-C3` CSV открывается без ошибок.

Критерий завершения: аналитика и документы готовы для защиты.

---

## Спринт 9. Интеграции: Bpium, оплата, доставка (День 11)

Цель: закрыть расширенный MVP по внешним интеграциям.

### TODO
- [x] `S9-01` Реализовать `integrations/bpium.py` (REST client + auth + retry/backoff).
- [x] `S9-02` Настроить upsert в Bpium по `external_id=order_id` и сохранять `bpium_record_id` в `Order`.
- [x] `S9-02A` Усилить upsert: если `bpium_record_id` пуст, сначала искать запись в Bpium по `external_id`, затем делать `update` вместо blind `create`.
- [x] `S9-02B` Синхронизировать Bpium при смене статуса из Telegram callback (`Подтвердить/Отменить`), чтобы CRM-статус не расходился с БД.
- [x] `S9-02C` Исключить лишний Bpium sync при no-op переходе статуса в Telegram (`confirmed->confirmed`, `cancelled->cancelled`) для чистых логов и меньшей нагрузки API.
- [x] `S9-03` Определить map полей в Bpium:
`order_id`, `created_at`, `channel`, `customer_name`, `phone`, `items_summary`, `delivery_address`, `status`, `delivery_cost`, `total_amount`, `is_paid`, `paid_at`, `track_number`, `updated_at`.
- [x] `S9-04` Триггер синхронизации: при `confirmed` и при важных изменениях статуса.
- [x] `S9-05` Реализовать `integrations/delivery.py`: тарифы по городу -> `delivery_cost`.
- [x] `S9-06` Реализовать `integrations/payment.py`: YooKassa sandbox (`payment_url`, проверка статуса, запись `is_paid/paid_at`).
- [x] `S9-07` Fallback-поведение:
ошибка Bpium/YooKassa не ломает основной pipeline; ошибка логируется, заказ остаётся операбельным.
- [x] `S9-08` Добавить тесты/смоук-проверки интеграций с моками.

### Проверки
- [x] `S9-C1` При `confirmed` запись появляется/обновляется в Bpium.
- [x] `S9-C2` Тариф доставки рассчитывается и пишется в `delivery_cost`.
- [x] `S9-C3A` YooKassa API доступна: тестовый платёж создаётся (`pending`) и читается по `payment_id`.
- [x] `S9-C3` Тестовая оплата проходит по официальному сценарию YooKassa sandbox.
- [x] `S9-C4` При недоступности внешних сервисов заказный pipeline не падает.

Критерий завершения: расширенный MVP по интеграциям закрыт.

---

## Спринт 9A. Этап 5: API службы доставки (ApiShip, тестовый контур)

Цель: закрыть часть задания "Интегрировать API службы доставки" с получением статусов и трек-номера.

### TODO
- [x] `S9A-01` Добавить `integrations/apiship.py`: auth + базовый REST client для тестовой среды ApiShip.
- [x] `S9A-02` Расширить модель/схему заказа техполями доставки:
`shipping_provider`, `shipping_external_id`, `tracking_url`, `shipping_status_raw`, `shipping_synced_at`.
- [x] `S9A-03` Реализовать расчёт доставки через ApiShip (`calculator`) с fallback на локальные тарифы `integrations/delivery.py`.
- [x] `S9A-04` Реализовать создание тестовой отправки в ApiShip после подтверждения заказа (и/или после оплаты, флагом).
- [x] `S9A-05` Реализовать запись `track_number` из ответа провайдера (`providerNumber`/`barcode`).
- [x] `S9A-06` Реализовать обновление статусов доставки по `clientNumber` (management command + ручной запуск).
- [x] `S9A-07` Добавить map статусов ApiShip -> `Order.Status` через `VALID_TRANSITIONS` (без нелегальных переходов).
- [x] `S9A-08` Расширить sync в Bpium полями доставки (номер отслеживания, статус, ссылка на трек).
- [x] `S9A-09` Добавить unit/smoke-тесты с моками ApiShip: calculator/create/status.

### Проверки
- [x] `S9A-C1` Для тестового заказа успешно считается стоимость через ApiShip или корректно срабатывает fallback.
- [x] `S9A-C2` Тестовая отправка создаётся, `track_number` сохраняется в `Order` и виден в дашборде.
- [x] `S9A-C3` Статус доставки подтягивается из ApiShip и не ломает state machine.
- [x] `S9A-C4` При ошибках ApiShip pipeline заказа остаётся рабочим.

Критерий завершения: внешняя доставка (тестовый контур) демонстрируется end-to-end.

---

## Спринт 10. Тестирование, стабилизация и сдача (Дни 12-14)

Цель: довести качество, документацию и материалы защиты до DoD.

### TODO
- [x] `S10-01` Подготовить набор из 50 тестовых заказов (`docs/datasets/ai_accuracy_50.json`).
- [x] `S10-02` Прогнать 50 кейсов и замерить accuracy AI-парсинга (`docs/ai_accuracy_50_report.md`).
- [x] `S10-03` Довести accuracy до `>=85%` (факт: `100%` strict/adjusted на `GigaChat-2-Pro`).
- [x] `S10-04` Добавить тесты: state machine, idempotency, slot filling, manual review, интеграции (моки).
- [x] `S10-05` Довести покрытие ключевой бизнес-логики до `>=50%` (факт: `81%`, `docs/coverage_report.txt`).
- [x] `S10-06` Финализировать `docker-compose.yml`: `web + db + bot + nginx`, healthchecks.
- [x] `S10-07` Подготовить `scripts/seed_data.py` (>=20 заказов).
- [x] `S10-08` Оформить `README.md`: запуск, архитектура, ограничения, privacy-note, roadmap.
- [x] `S10-09` Подготовить `docs/prompts.md`.
- [x] `S10-10` Подготовить 12+ скриншотов:
бот (happy + slot filling), витрина, дашборд (таблица/карточка/статистика), Admin, Swagger, Bpium, email.
- [x] `S10-11` Записать демо 5-7 минут по сценариям A/B/C/D.
- [x] `S10-12` Подготовить режим "РФ/локальный AI по умолчанию" для демо: профиль `.env` с `LLM_PROVIDER=vllm` (или `yandexgpt`/`gigachat`) без OpenAI (`.env.demo.ru.example`).
- [x] `S10-13` Обновить privacy-note: зафиксировать контур ПДн и выбранный AI-провайдер на защите (локальный или РФ-облако).

### Проверки
- [x] `S10-C1` `docker compose up` поднимает проект в чистом окружении.
- [x] `S10-C2` Сценарии A/B/C/D воспроизводятся без ручных фиксов (см. `docs/demo_scenarios_abcd.md` + автотесты).
- [x] `S10-C3` Все артефакты сдачи готовы.
- [x] `S10-C4` Внутренний DoD закрыт.

Критерий завершения: `GATE-3` закрыт.

---

## Спринт 10B. Post-Audit Hardening и финальная верификация (День 15)

Цель: закрыть замечания повторного аудита (v2), усилить production-baseline и синхронизировать артефакты качества.

### TODO
- [x] `S10B-01` Перевести контейнер `web` с `runserver` на `gunicorn` (`backend/Dockerfile`, `docker-compose.yml`, зависимости).
- [x] `S10B-02` Вынести внешние HTTP side effects из `@transaction.atomic` в `transaction.on_commit()` в AI pipeline.
- [x] `S10B-03` Добавить недостающие тесты по bot/dashboard:
`foreign cancel callback`, duplicate/error paths в message handler, payment-link/payment-refresh с mock YooKassa.
- [x] `S10B-04` Выполнить полный прогон тестов + coverage, зафиксировать фактические метрики (`99` тестов, `81%` coverage).
- [x] `S10B-05` Актуализировать документацию по итогам прогона:
`README.md`, `docs/coverage_report.txt`, при необходимости дополнительные notes по runtime-профилю.
- [x] `S10B-06` Зафиксировать результаты в `plan-v2.md`, подготовить и выполнить push итоговых изменений.

### Проверки
- [x] `S10B-C1` `python manage.py test` проходит без регрессий.
- [x] `S10B-C2` Coverage не ниже предыдущего значения и отражён в `docs/coverage_report.txt`.
- [x] `S10B-C3` Docker web runtime запускается через `gunicorn`, не `runserver`.
- [x] `S10B-C4` Side effects после парсинга выполняются через `on_commit`, транзакции не держат внешние HTTP.
- [x] `S10B-C5` GitHub содержит актуальные код и документы, рабочее дерево чистое.

Критерий завершения: закрыт пакет hardening-задач после v2-аудита без функциональных регрессий.

---

## Финальный DoD-чеклист

- [x] `DOD-01` Публичный GitHub-репозиторий оформлен.
- [x] `DOD-02` Работают 4 сквозных сценария: A/B/C/D.
- [x] `DOD-03` Работают 3 канала приёма: Telegram, web, email.
- [x] `DOD-04` Достигнута accuracy `>=85%` на 50 заказах.
- [x] `DOD-05` CRM-синхронизация в Bpium работает.
- [x] `DOD-06` API-документация доступна через `/api/docs/`.
- [x] `DOD-07` `docker compose up` поднимает всё приложение.
- [x] `DOD-08` Подготовлены 12+ скриншотов и видео 5-7 минут.
- [x] `DOD-09` Подготовлена библиотека промптов.
- [x] `DOD-10` README содержит архитектуру, запуск, ограничения, privacy-note и roadmap.
- [x] `DOD-11` Внешняя интеграция службы доставки (тестовый контур) демонстрирует создание отправки, трек-номер и обновление статуса.
- [x] `DOD-12` На демо показан intake без OpenAI: локальный (`vllm`) или российский (`yandexgpt`/`gigachat`) провайдер.

---

## Журнал прогресса

- [x] `LOG-01` Зафиксирована дата старта.
- [x] `LOG-02` После каждого дня обновлены чекбоксы и статус спринта.
- [x] `LOG-03` Все блокеры зафиксированы с решением или обходным планом.
- [x] `LOG-04` Все сработавшие fallback-сценарии задокументированы (что сломалось и как обошли) (`docs/fallbacks_log.md`).

## Техдолг (открытый)

- [x] `TD-01` Закрыть live-проверки `ApiShip` (`S9A-C1`, `S9A-C2`, `S9A-C3`) после получения тестовых credentials и `providerKey`.
- [x] `TD-02` Зафиксировать в `README` фактически использованный сценарий доставки для демо (fallback-only или live ApiShip) после закрытия `S9A-C1..C3`.

## Текущие блокеры

- [x] `BLOCK-01` Docker daemon был не запущен локально; после запуска Docker Desktop `docker compose up --build` проходит.
- [x] `BLOCK-02` Были отсутствующие IMAP credentials; после заполнения `.env` и прогона `check_email` живая проверка закрыта.
- [x] `BLOCK-03` Были отсутствующие credentials YooKassa sandbox; после получения `shop_id/secret` и live-теста оплата подтверждена, блокер закрыт.
- [x] `BLOCK-04` Сбой монтирования Docker Desktop (`/run/desktop/mnt/host/c ... mkdir ... file exists`) при `restart/up`; решено через `docker compose down`, `wsl --shutdown`, перезапуск Docker Desktop и повторный `docker compose up -d --build`.
- [x] `BLOCK-05` Для production-подключения YooKassa потребуется завершить шаги онбординга (минимальный сайт + страница контактов/реквизитов); для sandbox-live проверки `S9-C3` блокер не критичен и закрыт.
- [x] `BLOCK-06` Внешняя доставка закрыта на уровне кода: добавлен контур `ApiShip` (calculator/create/status sync + fallback), см. `Спринт 9A`.
- [x] `BLOCK-07` Для стабильной работы `GigaChat` в режиме `verify_ssl=true` требуется установка сертификата Минцифры (`.cer`) в доверенные; закрыто через установку сертификата и настройку `GIGACHAT_CERT_PATH`.
- [x] `BLOCK-08` Бот мог "молчать" при падении LLM-провайдера (неперехваченное исключение в message handler); закрыто переключением runtime на `gigachat` и добавлением безопасного ответа пользователю при ошибке обработки.
- [x] `BLOCK-09` В Docker-контейнеры не пробрасывался `BPIUM_FIELD_MAP`, из-за чего синхронизация в Bpium падала `400 field not found`; закрыто добавлением env в `docker-compose.yml` и повторной проверкой sync.
- [x] `BLOCK-10` Live-проверка `ApiShip` закрыта: включён тестовый профиль (`api.dev` + `test/test`), подтверждены calculator/create/status sync в рабочем окружении.

---

## Post-MVP: Roadmap приёмки в production (отдельный трек)

Важно: блок ниже не влияет на закрытый `GATE-3` и фиксирует следующий этап зрелости.

- [ ] `PRD-01` HTTPS + реальный сертификат (Let's Encrypt/корпоративный CA), `HTTP -> HTTPS`, HSTS.
- [ ] `PRD-02` Hardening production-конфига (`secure cookies`, `SECURE_SSL_REDIRECT`, proxy SSL headers, RBAC/MFA для админов).
- [ ] `PRD-03` Управление секретами через Vault/Secrets Manager + ротация ключей.
- [ ] `PRD-04` Централизованный мониторинг и алертинг (логи, метрики, error tracking, runbooks).
- [ ] `PRD-05` Backup/DR-контур: автоматические бэкапы, offsite-хранение, шифрование, регулярные тесты восстановления.
- [ ] `PRD-06` Зафиксировать и согласовать целевые `RPO/RTO`, подтвердить на drills.
- [ ] `PRD-07` Формализовать требования к внешним провайдерам (оплата/доставка/email): SLA, поддержка, incident-каналы, failover-план.
- [ ] `PRD-08` Провести pre-pentest -> внешний pentest -> remediation -> re-test, запрет релиза при открытых Critical/High.
- [ ] `PRD-09` Пройти финальный Go-Live Readiness Review (business + tech + security).
- [ ] `PRD-10` Утвердить операционную модель техподдержки (внутренняя/аутсорс/гибрид) и матрицу компетенций L1/L2/L3.
- [ ] `PRD-11` Зафиксировать SLA/OLA поддержки по приоритетам P1/P2/P3, процесс эскалаций и on-call модель.
- [ ] `PRD-12` Для аутсорса формализовать обязательные требования: NDA, least-privilege доступы, аудит действий, резерв смен.
- [ ] `PRD-13` Ввести регулярные drills поддержки и восстановления (ежеквартально) с проверкой фактических RPO/RTO.
- [ ] `PRD-14` CRM evolution track: формализовать интеграционный blueprint `OrderFlow/Bpium <-> amoCRM` (no-code/direct API, mapping, idempotency, SLA).

Подробный чеклист и критерии:
- `docs/production_readiness_roadmap.md`

---

## Post-MVP: UX/UI & CX Improvement (отдельный трек)

Фокус: улучшение пользовательского опыта в Telegram-боте и storefront с измеримым влиянием на бизнес-метрики.

- [ ] `UX-01` Провести UX-аудит (бот + storefront), собрать top pain points и CJM.
- [ ] `UX-02` Зафиксировать baseline KPI:
`conversion_to_order`, `drop_off_rate`, `needs_info_rate`, `time_to_confirm`.
- [ ] `UX-03` Улучшить conversational UX бота:
подсказки, быстрые действия, понятные ошибки и статусные сообщения.
- [ ] `UX-04` Улучшить UX storefront:
упрощение формы, валидация, микрокопирайтинг, мобильная адаптация.
- [ ] `UX-05` Ввести accessibility baseline (контраст, фокус, keyboard navigation, readable errors).
- [ ] `UX-06` Провести A/B тесты по ключевым UX-гипотезам и подтвердить эффект метриками.
- [ ] `UX-GATE-01` Принять UX/CX трек после достижения целевых KPI и успешного usability-smoke.

Подробный план:
- `docs/ux_cx_roadmap.md`
