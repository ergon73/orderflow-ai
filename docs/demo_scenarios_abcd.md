# Demo Scenarios A/B/C/D

Сценарии для защиты и их покрытие автотестами.

## Scenario A: Happy Path (Telegram -> AI -> confirmed)
- Клиент отправляет полный заказ в Telegram.
- Система создает `IntakeMessage`, `ExtractionAttempt`, `Order`.
- Заказ сразу получает статус `confirmed`.
- Покрытие тестами:
  - `tests.test_ai_parser.ParserServiceTests.test_process_intake_creates_confirmed_order`
  - `tests.test_intake_channels.IntakeChannelTests.test_telegram_idempotency`

## Scenario B: NEEDS_INFO + Slot Filling
- Первый intake неполный (например, без телефона) -> `needs_info`.
- Клиент досылает недостающие данные.
- Обновляется тот же `order_id`, статус -> `confirmed`.
- Покрытие тестами:
  - `tests.test_ai_parser.ParserServiceTests.test_process_intake_creates_needs_info_order`
  - `tests.test_ai_parser.ParserServiceTests.test_slot_filling_updates_existing_order`
  - `tests.test_ai_parser.ParserServiceTests.test_parallel_orders_do_not_mix_when_order_is_explicit`

## Scenario C: Anti-loop + Manual Review
- После >3 неуспешных попыток slot filling включается ручная эскалация.
- `needs_manual_review=True`, цикл с ботом прекращается.
- Покрытие тестами:
  - `tests.test_ai_parser.ParserServiceTests.test_manual_review_enabled_after_repeated_failures`

## Scenario D: Integrations (CRM + Payment + Delivery)
- При подтвержденном заказе выполняются интеграционные операции:
  - sync в Bpium,
  - расчет/создание доставки (ApiShip + fallback),
  - обработка оплаты (YooKassa + fallback).
- Покрытие тестами:
  - `tests.test_integrations.IntegrationTests.test_bpium_sync_updates_record_id`
  - `tests.test_integrations.IntegrationTests.test_mark_paid_if_succeeded`
  - `tests.test_integrations.IntegrationTests.test_apiship_create_shipment_sets_tracking_fields`
  - `tests.test_integrations.IntegrationTests.test_apiship_status_sync_updates_order`

## Fast Check

```bash
cd backend
python manage.py test tests.test_ai_parser tests.test_integrations tests.test_intake_channels -v 1 --keepdb --noinput
```
