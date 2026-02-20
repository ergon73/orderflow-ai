# Plan Исправлений (Refactoring & Fixes)

Цель: закрыть выявленные проблемы по безопасности, корректности, тестам и архитектуре.
Источник: `claude-refactoring.md` + `gemini-refactoring.md`.
Принцип приоритизации: от критичного к улучшениям.

---

## Легенда

- `P0` — критично, исправлять в первую очередь.
- `P1` — важно, снижает риски и техдолг.
- `P2` — улучшение качества/поддерживаемости.
- `P3` — отложенные улучшения (не блокируют текущую сдачу).

---

## P0 — Критичные исправления

- [x] `RF-P0-01` Закрыть доступ к dashboard-эндпоинтам аутентификацией.
Код: `backend/dashboard/views.py`, `backend/dashboard/urls.py`.
Критерий: все manager views кроме `storefront_view` требуют login.

- [x] `RF-P0-02` Закрыть API аутентификацией (`IsAuthenticated` или эквивалент).
Код: `backend/orders/api_views.py`.
Критерий: `/api/orders/`, `/api/orders/<id>/`, `/api/orders/<id>/status/` недоступны анониму.

- [x] `RF-P0-03` Добавить авторизацию владельца заказа в Telegram callbacks.
Код: `backend/bot/handlers.py`.
Критерий: пользователь не может подтвердить/отменить/редактировать чужой заказ.

- [x] `RF-P0-04` Защитить Telegram callbacks от невалидного `callback_data`.
Код: `backend/bot/handlers.py`.
Критерий: нет падений на `ValueError/IndexError` при парсинге `order_id`.

- [x] `RF-P0-05` Убрать небезопасный default `SECRET_KEY`.
Код: `backend/config/settings.py`.
Критерий: в не-dev окружении без `SECRET_KEY` приложение не стартует (fail-fast).

- [x] `RF-P0-06` Поменять default `DEBUG` на безопасный.
Код: `backend/config/settings.py`.
Критерий: по умолчанию `DEBUG=False`, dev-поведение задается явно через env.

- [x] `RF-P0-07` Добавить тесты на P0-блок.
Код: `backend/tests/`.
Критерий: есть тесты на auth/API/callback ownership/invalid callback.

---

## P1 — Важные исправления корректности

- [x] `RF-P1-01` Удалить dead code в `get_default_llm_client`.
Код: `backend/ai_parser/services.py`.
Критерий: недостижимые строки удалены, поведение не изменилось.

- [x] `RF-P1-02` Снизить риск race condition при slot-filling update.
Код: `backend/ai_parser/services.py`.
Критерий: обновление заказа выполняется предсказуемо (`update_fields` и/или `select_for_update`).

- [x] `RF-P1-03` Явно ограничить обновляемые поля `customer.save`.
Код: `backend/ai_parser/services.py`.
Критерий: `customer.save(update_fields=[...])` для частичных обновлений.

- [x] `RF-P1-04` Централизовать env-хелперы (`bool/int/float`) в одном модуле.
Код: `backend/config/` + потребители.
Критерий: убраны дубли `_env_bool/_env_int/_env_float` в нескольких файлах.

- [x] `RF-P1-05` Добавить базовую конфигурацию LOGGING в settings.
Код: `backend/config/settings.py`.
Критерий: контролируемый формат/уровень логов, без утечек секретов.

- [x] `RF-P1-06` Ограничить чувствительные данные в логах интеграций.
Код: `backend/ai_parser/client.py`, `backend/integrations/*.py`.
Критерий: токены/пароли не попадают в лог даже при ошибках.

---

## P1 — Тесты и покрытие рисковых зон

- [x] `RF-P1-T01` Добавить тесты bot handlers (happy path, needs_info, invalid callback, чужой заказ).
Код: `backend/tests/`.
Критерий: минимум 4-6 тестов на критичные ветки callbacks/обработки сообщений.

- [x] `RF-P1-T02` Добавить тесты API endpoints (auth + негативные кейсы).
Код: `backend/tests/`.
Критерий: анонимный доступ запрещен, валидные запросы авторизованного менеджера проходят.

- [x] `RF-P1-T03` Добавить тест `storefront_view` POST.
Код: `backend/tests/`.
Критерий: форма создает intake/order и корректно рендерит success.

- [x] `RF-P1-T04` Добавить негативные тесты dashboard по `order_id`/ошибочным переходам.
Код: `backend/tests/`.
Критерий: корректные 404/400 без падений.

- [x] `RF-P1-T05` Добавить тесты `check_email` management command (через mock IMAP).
Код: `backend/tests/`.
Критерий: idempotency и корректный ingestion подтверждены.

- [x] `RF-P1-T06` Добавить тесты на CSV/invoice/notifications edge-cases.
Код: `backend/tests/`.
Критерий: экспорт содержит ожидаемые колонки, fallback invoice работает, нотификации не падают.

---

## P2 — Архитектурный рефакторинг

- [x] `RF-P2-01` Разбить `ai_parser/client.py` на модули.
Цель: снизить связность и размер god-module.
Критерий: отдельные модули для retry/normalization/providers, без регрессий тестов.

- [x] `RF-P2-02` Разделить ответственности в `ai_parser/services.py`.
Цель: декомпозиция `process_intake_message` на более мелкие шаги.
Критерий: выделены отдельные функции (эскалация, upsert order/customer/items, post-actions).

- [x] `RF-P2-03` Ослабить прямую зависимость AI parser от интеграций.
Код: `backend/ai_parser/services.py`, `backend/orders/services.py` (или новый orchestrator).
Критерий: внешние sync/доставка вынесены в orchestration слой.

- [x] `RF-P2-04` Добавить измерение latency LLM-вызовов в runtime-логах.
Код: `backend/ai_parser/services.py` (или `client.py`).
Критерий: в логах есть latency и модель/провайдер на каждый parse.

---

## P3 — Отложенные улучшения

- [x] `RF-P3-01` Добавить rate limiting для публичных/чувствительных endpoints.
Код: Django middleware/DRF throttling.
Критерий: ограничение частоты запросов на storefront и API.

---

## Порядок выполнения

- [x] `RF-SEQ-01` Сначала закрыть весь блок `P0`.
- [x] `RF-SEQ-02` Затем `P1` (корректность + тесты).
- [x] `RF-SEQ-03` После стабилизации — `P2`.
- [x] `RF-SEQ-04` `P3` выполнять при наличии времени/после защиты.

---

## Критерий завершения плана

- [x] `RF-DOD-01` Все задачи `P0` и `P1` закрыты.
- [x] `RF-DOD-02` Полный тест-ран без регрессий.
- [x] `RF-DOD-03` Документация обновлена по внесенным изменениям.
