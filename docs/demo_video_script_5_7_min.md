# Сценарий демо-видео 5-7 минут (S10-11)

Цель: показать A/B/C/D без ручных фиксов и подтвердить DoD.

## Подготовка перед записью (30-60 сек)

1. Запустить проект:
   - `docker compose up -d --build`
2. Проверить здоровье:
   - `docker compose ps`
3. Открыть вкладки:
   - `http://127.0.0.1:8001/storefront/`
   - `http://127.0.0.1:8001/dashboard/orders/`
   - `http://127.0.0.1:8001/admin/`
   - `http://127.0.0.1:8001/api/docs/`

## Тайминг записи

### 0:00-0:40 - Архитектура и запуск

- Показать `docker compose ps` и что `web/db/bot/nginx` в `healthy`.
- Коротко: 3 канала intake, AI parsing, дашборд, Bpium, YooKassa, ApiShip.

### 0:40-1:40 - Scenario A (happy path)

- В `storefront` отправить полный заказ.
- Показать успешную страницу и созданный `order_id`.
- Перейти в `dashboard/orders`, открыть карточку заказа, показать `confirmed`.

### 1:40-2:50 - Scenario B (needs_info + slot filling)

- Показать заказ со статусом `needs_info` и `missing_fields`.
- Показать, что после уточнения (в Telegram/web тесте) заказ переходит в `confirmed`.
- Подчеркнуть: обновляется тот же `order_id`.

### 2:50-3:40 - Scenario C (anti-loop + manual review)

- Показать пример заказа с `needs_manual_review=True`.
- Кратко объяснить лимит попыток (`>3`) и остановку авто-цикла.

### 3:40-5:10 - Scenario D (интеграции)

- В карточке заказа показать поля доставки:
  - `shipping_provider`, `shipping_external_id`, `track_number`, `tracking_url`, `shipping_status_raw`.
- Показать оплату:
  - создание payment link / ручная отметка `Оплачено`.
- Показать наличие `bpium_record_id` и факт sync.

### 5:10-6:00 - API и админка

- Открыть `api/docs` (Swagger), показать endpoints.
- Открыть `admin/orders/order/`, показать управляемость из Admin.

### 6:00-6:30 - Закрытие

- Кратко перечислить DoD: 3 канала, A/B/C/D, accuracy, интеграции, docker-start.

## Чек-лист качества записи

- Горизонтальный формат, 1080p.
- В кадре видны URL и статусы.
- Нет ручных правок кода во время демо.
- Длительность: 5-7 минут.
