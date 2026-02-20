# Claude Refactoring Report — OrderFlow AI

Дата анализа: 2025-02-20
Анализатор: Claude (Anthropic)
Проанализировано: весь исходный код проекта, тесты, конфигурации, Docker, документация.

---

## 1. Общая оценка проекта

Проект **OrderFlow AI** — качественная дипломная работа уровня расширенного MVP. Архитектура продуманная, код читаемый, покрытие тестами 77% — выше среднего для студенческого проекта. Мульти-провайдерный AI-контур с эскалацией, safety-net и shadow-eval — это production-grade решения, редко встречающиеся в учебных проектах.

**Сильные стороны:**
- Чистая доменная модель с event sourcing через таблицы (IntakeMessage → ExtractionAttempt → Order)
- Формализованная state machine с валидацией переходов
- Идемпотентность по всем каналам
- Tolerant parsing с fallback-цепочкой для нестабильных LLM-ответов
- Fallback-поведение при сбоях внешних интеграций
- 63 теста, 77% coverage — солидно для MVP

**Области для улучшения:** безопасность эндпоинтов, устранение dead code, снижение связности `ai_parser/services.py`, усиление тестов граничных случаев.

---

## 2. Security — Безопасность

### 2.1 CRITICAL: Отсутствует аутентификация на dashboard и API

**Проблема:** Все dashboard endpoints (`/dashboard/orders/`, `/dashboard/stats/`, `/dashboard/export/csv/`, status update, mark-paid, payment-link, payment-refresh) и API endpoints (`/api/orders/`, `/api/orders/<pk>/status/`) **не требуют аутентификации**. Любой пользователь с доступом к URL может:
- Видеть все заказы и персональные данные клиентов
- Менять статусы заказов
- Отмечать заказы как оплаченные
- Создавать платёжные ссылки YooKassa
- Экспортировать все данные в CSV

**Файлы:** `dashboard/views.py`, `orders/api_views.py`, `dashboard/urls.py`, `orders/urls.py`

**Fix (quick win):**
```python
# dashboard/views.py — добавить на все view-функции менеджера:
from django.contrib.auth.decorators import login_required

@login_required
def order_list_view(request):
    ...

# orders/api_views.py — добавить permission class:
from rest_framework.permissions import IsAuthenticated

class OrderListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    ...
```

**Приоритет:** P0 (критический). Для демо/защиты можно обосновать отсутствие auth, но для любого развёртывания это обязательно.

### 2.2 HIGH: SECRET_KEY по умолчанию `change-me`

**Файл:** `config/settings.py:40`
```python
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
```

Если `.env` не заполнен, Django работает с предсказуемым SECRET_KEY. Это позволяет подделать сессии и CSRF-токены.

**Fix:**
```python
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "insecure-dev-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured("SECRET_KEY must be set in production")
```

### 2.3 HIGH: DEBUG=True по умолчанию в production-контексте

**Файл:** `config/settings.py:41`
```python
DEBUG = env_bool("DEBUG", True)
```

При отсутствии переменной DEBUG включён, что в Docker-деплое раскрывает stack traces, SQL-запросы и конфигурацию.

**Fix:** Заменить default на `False`.

### 2.4 MEDIUM: Отсутствует CSRF-защита для storefront POST

**Файл:** `dashboard/views.py:48` — `storefront_view` принимает POST, но шаблон должен содержать `{% csrf_token %}`. Проверил: Django middleware CSRF включён, но нет явной проверки, что шаблон содержит токен. Учитывая, что CSRF middleware активен — это скорее предупреждение для будущих API-эндпоинтов.

### 2.5 MEDIUM: Telegram callback_data парсится через `int(callback.data.split(":")[-1])`

**Файл:** `bot/handlers.py:152, 186, 211`

Если злонамеренный пользователь отправит callback с нечисловым order_id, произойдёт неперехваченный `ValueError`. Это не SQL-инъекция (Django ORM безопасен), но может привести к необработанному исключению.

**Fix:**
```python
try:
    order_id = int(callback.data.split(":")[-1])
except (ValueError, IndexError):
    await callback.answer("Некорректные данные", show_alert=True)
    return
```

### 2.6 LOW: Нет rate limiting

Отсутствует ограничение частоты запросов на storefront и API. Для MVP допустимо, но в production злоумышленник может генерировать тысячи заказов, расходуя LLM-токены.

### 2.7 INFO: SQLi — не обнаружено

Django ORM используется корректно повсеместно. Нет raw SQL, нет `cursor.execute()`, нет f-string в SQL-контексте. Поиск по `Q` объектам в `order_list_view` безопасен.

### 2.8 INFO: Secrets в `.gitignore` — корректно

`.env` и `.env.*` правильно исключены из Git (за исключением `.env.example` и `.env.demo.ru.example`). API-ключи не обнаружены в исходном коде.

---

## 3. Архитектура и SOLID

### 3.1 GOOD: Single Responsibility — в целом соблюдается

- `orders/models.py` — только модели, без бизнес-логики
- `orders/state_machine.py` — только матрица переходов
- `orders/services.py` — операции над заказами
- `ai_parser/schemas.py` — только Pydantic-схемы
- `ai_parser/validators.py` — только валидация
- `ai_parser/prompts.py` — только промпты

### 3.2 ISSUE: `ai_parser/client.py` — God Module (998 строк)

Файл содержит:
- Retry-инфраструктуру (~100 строк)
- JSON-нормализацию и tolerant parsing (~350 строк)
- 5 LLM-клиентов (OpenAI, YandexGPT, GigaChat, Mock, + базовый ABC)
- Множество утилит: `_coerce_int`, `_normalize_item_title`, `_coerce_items`, `_extract_chain_of_thought_fallback`, `_merge_canonical_aliases`, `_normalize_order_extract_payload`

**Рекомендация:** Разделить на 3-4 модуля:
- `ai_parser/retry.py` — retry/backoff логика
- `ai_parser/normalizers.py` — tolerant parsing, alias resolution, JSON cleanup
- `ai_parser/client.py` — только ABC + клиенты (OpenAI, vLLM)
- `ai_parser/clients/` — по файлу на провайдера (`gigachat.py`, `yandexgpt.py`)

### 3.3 ISSUE: `ai_parser/services.py` — слишком высокая связность (661 строк)

Функция `process_intake_message()` (строки 480-661) выполняет 12+ ответственностей:
1. Инициализация LLM
2. Загрузка предыдущей extraction
3. Определение пути эскалации
4. Парсинг + валидация
5. Эскалация при ошибке
6. Эскалация по сложности
7. Создание/обновление Order
8. Обновление Customer
9. Синхронизация items
10. Создание ExtractionAttempt
11. Shadow evaluation
12. Manual review check
13. Bpium sync

**Рекомендация:** Извлечь:
- `_resolve_escalation_path()` — определение и выполнение эскалации
- `_upsert_order_from_extract()` — создание/обновление Order + items + customer
- `_check_manual_review_threshold()` — проверка лимита попыток

### 3.4 GOOD: Open/Closed Principle — LLMClient ABC

Абстрактный `LLMClient` с конкретными реализациями — правильный подход. Добавление нового провайдера не требует изменения существующих клиентов.

### 3.5 ISSUE: Dependency Inversion нарушается в `ai_parser/services.py`

```python
from integrations.apiship import apiship_auto_create_on_confirmed, create_shipment_for_order_safe
from integrations.delivery import apply_delivery_cost
from integrations.sync import sync_order_to_bpium_safe
```

AI-парсер напрямую зависит от интеграций (Bpium, ApiShip, delivery). Парсер не должен знать о доставке и CRM. Это должно быть в слое оркестрации (services/orchestrator).

**Рекомендация:** Переместить вызовы интеграций в отдельный orchestrator или в хуки/сигналы Django.

### 3.6 MINOR: Дублирование `_env_bool`, `_env_int`, `_env_float`

Одинаковые утилиты определены в:
- `config/settings.py` (`env_bool`)
- `ai_parser/client.py` (`_env_int`, `_env_float`)
- `ai_parser/services.py` (`_env_bool`)
- `integrations/apiship.py` (`_env_bool`, `_env_int`, `_env_float`)

**Fix:** Вынести в `config/env_utils.py` и импортировать.

---

## 4. Баги и потенциальные проблемы

### 4.1 BUG: Dead code в `get_default_llm_client()`

**Файл:** `ai_parser/services.py:435-449`
```python
def get_default_llm_client() -> LLMClient:
    provider = _resolve_default_provider()
    try:
        return _build_llm_client_for_provider(provider)
    except Exception as exc:
        logger.warning(...)
        return MockLLMClient()

    logger.warning("unknown_llm_provider provider=%s fallback=mock", provider)  # DEAD CODE
    return MockLLMClient()  # DEAD CODE
```

Строки 448-449 **никогда не выполняются** — функция уже вернула результат из `try` или `except`. Это мёртвый код — остаток рефакторинга.

**Fix:** Удалить строки 448-449.

### 4.2 BUG: `ACTIVE_ORDER_CONTEXT` — in-memory dict, не переживает перезапуск

**Файл:** `bot/handlers.py:25`
```python
ACTIVE_ORDER_CONTEXT: dict[int, int] = {}
```

Контекст активного заказа хранится в памяти бота. При перезапуске контейнера `bot` все pending-контексты теряются. В MVP это допустимо (fallback через `get_active_needs_info_order`), но стоит задокументировать.

### 4.3 BUG: Отсутствует проверка принадлежности заказа пользователю в Telegram callbacks

**Файл:** `bot/handlers.py:152-177`

При нажатии кнопки "Подтвердить"/"Отменить" проверяется только существование заказа, но не принадлежность заказа текущему пользователю. Теоретически пользователь A может нажать кнопку из forwarded сообщения и подтвердить заказ пользователя B.

**Fix:**
```python
order = await _load_order(order_id)
if order.customer.telegram_id != callback.from_user.id:
    await callback.answer("Это не ваш заказ", show_alert=True)
    return
```

### 4.4 POTENTIAL: Race condition при параллельных update в `process_intake_message`

**Файл:** `ai_parser/services.py:580-586`

При slot filling `order.save()` вызывается без `update_fields`, что перезаписывает все поля. Если два запроса одновременно обрабатывают один заказ, возможна потеря данных.

**Fix:** Использовать `select_for_update()` при загрузке order, либо `order.save(update_fields=[...])`.

### 4.5 MINOR: `order.save()` без `update_fields` в нескольких местах

**Файл:** `ai_parser/services.py:586`
```python
order.save()  # перезаписывает ВСЕ поля
```

Лучше явно указывать `update_fields` для предсказуемости и производительности.

### 4.6 MINOR: `customer.save()` без `update_fields` в `process_intake_message`

**Файл:** `ai_parser/services.py:609`
```python
if customer_updated:
    customer.save()
```

**Fix:** `customer.save(update_fields=["name", "phone", "email", "updated_at"])`

---

## 5. Тесты

### 5.1 Покрытие: 77% — хорошо для MVP

63 теста в 5 файлах покрывают:
- Парсер + валидаторы (28 тестов)
- State machine и intake (12 тестов)
- Dashboard endpoints (7 тестов)
- Интеграции с моками (13 тестов)
- LLM provider selection (5 тестов)

### 5.2 Отсутствующие тесты (quick wins)

| Что не покрыто | Риск | Сложность |
|---|---|---|
| `bot/handlers.py` — ни одного теста | HIGH | Medium (нужен aiogram test client) |
| `bot/notifications.py` — нет теста | LOW | Easy (mock requests.post) |
| `check_email.py` — management command | MEDIUM | Medium (mock imaplib) |
| Negative cases в dashboard (несуществующий order_id) | LOW | Easy |
| `request_order_edit` — нет теста в services | LOW | Easy |
| CSV export содержимое — проверка полноты полей | LOW | Easy |
| Invoice PDF/HTML fallback детально | LOW | Easy |
| `storefront_view` POST — нет integration test | MEDIUM | Easy |
| API endpoints (`/api/orders/`, `/api/orders/<pk>/status/`) | MEDIUM | Easy |

### 5.3 Рекомендации по тестам

- Добавить `test_bot.py` с mock aiogram (хотя бы 3-5 тестов на happy path, slot filling, error handling)
- Добавить negative test: callback с чужим order_id
- Добавить test для `create_payment_link_view` с mock YooKassa
- Проверить, что `export_orders_csv` содержит все 18 колонок

---

## 6. Python Best Practices

### 6.1 GOOD: Использование type hints

Type hints используются последовательно: `-> Order`, `-> tuple[Order, ExtractionAttempt]`, `| None`. Это хороший стиль для Python 3.11+.

### 6.2 GOOD: `@transaction.atomic` в критических местах

Транзакционность обеспечена в `services.py`, `process_intake_message` — атомарные операции с Order/ExtractionAttempt/History.

### 6.3 ISSUE: `time.sleep()` в LLM retry блокирует Django thread

**Файл:** `ai_parser/client.py:103`

`_retry_sleep()` вызывает `time.sleep()`, блокируя рабочий поток Django. При синхронном вызове в `process_intake_message` это может замедлить обработку при массовых retry.

**Для MVP допустимо.** В roadmap уже есть Celery — это правильный путь.

### 6.4 ISSUE: Отсутствует `asgiref.sync.sync_to_async` для DB-операций в notifications

**Файл:** `bot/notifications.py` — `send_order_status_notification` обращается к `order.customer.telegram_id` (lazy FK), но может вызываться из async-контекста бота. В текущем коде это вызывается из dashboard (sync), так что проблемы нет, но при вызове из бота может быть `SynchronousOnlyOperation`.

### 6.5 MINOR: `requests` библиотека вместо `httpx`

Проект использует `requests` для всех HTTP-вызовов (YooKassa, Bpium, ApiShip, Telegram notifications). Для production рекомендуется `httpx` с async support, но для MVP `requests` — нормальный выбор.

### 6.6 MINOR: Отсутствует `logging` configuration в settings.py

Django `LOGGING` dict не настроен в `settings.py`. Логирование работает через `basicConfig` и дефолтные Django-логгеры, но нет контроля над уровнями, форматом, ротацией.

**Quick fix:**
```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
```

---

## 7. ML / AI Best Practices

### 7.1 GOOD: Pydantic constrained extraction через Instructor

Использование `instructor` + `response_model=OrderExtract` — best practice для structured LLM output. Auto-retry при ошибках схемы.

### 7.2 GOOD: Tolerant parsing с fallback-цепочкой

`_normalize_order_extract_payload` + `_merge_canonical_aliases` + `_extract_chain_of_thought_fallback` — robust решение для нестабильных LLM-ответов. Обрабатывает:
- Unquoted JSON keys
- Вложенные объекты вместо строк в chain_of_thought
- Алиасы полей (name→title, quantity→qty)
- Маппинг EN→RU (cup→кружка)

### 7.3 GOOD: Safety-net извлечение из raw text

`_enrich_extract_from_raw_text()` добирает phone/email/address regex'ами, если LLM их пропустил. Это критично для моделей с нестабильным extraction.

### 7.4 GOOD: Каноническая нормализация missing_fields

`apply_post_validation()` пересчитывает `missing_fields` по каноническим слотам (`items`, `delivery.address`, `customer.phone`, `customer.email`), игнорируя шумные LLM-ключи. Это решает реальную проблему, когда модели возвращают `["quantity.item", "address.new_address"]` вместо ожидаемых ключей.

### 7.5 GOOD: Shadow evaluation для A/B тестирования моделей

`_run_shadow_evaluations()` — элегантное решение для параллельного сравнения провайдеров без влияния на production pipeline.

### 7.6 ISSUE: Temperature=0 не гарантирует детерминизм

`temperature=0` задан корректно во всех клиентах, но стоит учитывать, что:
- GigaChat и YandexGPT могут игнорировать temperature
- Даже OpenAI с temperature=0 не 100% детерминистичен

Это задокументировано в ТЗ — достаточно для MVP.

### 7.7 MINOR: Нет логирования latency LLM-вызовов

Нет метрик времени ответа LLM. Для benchmark это измеряется отдельным скриптом, но в production pipeline полезно логировать latency каждого вызова.

**Quick fix:** Добавить `time.monotonic()` вокруг `llm.parse()` в `_parse_and_validate()`.

---

## 8. Docker и DevOps

### 8.1 ISSUE: `runserver` в production Dockerfile

**Файл:** `Dockerfile:15`
```dockerfile
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
```

`runserver` — development server, не подходит для production. Нужен gunicorn/uvicorn.

**Fix:**
```dockerfile
RUN pip install gunicorn
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
```

### 8.2 ISSUE: Volumes mount `./backend:/app` в docker-compose

**Файл:** `docker-compose.yml:109-110`

Source mount перезаписывает содержимое контейнера. Для dev удобно, но для production нужно убрать.

### 8.3 GOOD: Healthchecks настроены для всех сервисов

DB, web, bot, nginx — все имеют healthcheck'и с `depends_on: condition: service_healthy`.

### 8.4 MINOR: Нет multi-stage build

Dockerfile копирует все файлы включая тесты, `.coverage`, `db.sqlite3`. Multi-stage build уменьшит размер образа.

---

## 9. Quick Wins — можно сделать за 1-2 часа

| # | Что сделать | Файл | Effort | Impact |
|---|---|---|---|---|
| 1 | Удалить dead code (строки 448-449 в services.py) | `ai_parser/services.py` | 1 мин | Чистота |
| 2 | Добавить `@login_required` на dashboard views | `dashboard/views.py` | 10 мин | Security P0 |
| 3 | Добавить `IsAuthenticated` на API views | `orders/api_views.py` | 5 мин | Security P0 |
| 4 | Добавить try/except на `int()` в bot callbacks | `bot/handlers.py` | 5 мин | Robustness |
| 5 | Проверка принадлежности заказа в bot callbacks | `bot/handlers.py` | 10 мин | Security |
| 6 | `order.save(update_fields=[...])` в process_intake | `ai_parser/services.py` | 10 мин | Correctness |
| 7 | `customer.save(update_fields=[...])` в process_intake | `ai_parser/services.py` | 5 мин | Correctness |
| 8 | Вынести `_env_bool/_env_int/_env_float` в общий модуль | `config/env_utils.py` | 15 мин | DRY |
| 9 | Добавить `LOGGING` dict в settings.py | `config/settings.py` | 5 мин | Observability |
| 10 | Заменить `runserver` на `gunicorn` в Dockerfile | `Dockerfile` | 10 мин | Production-readiness |

---

## 10. Рефакторинг средней сложности (полдня-день)

| # | Что сделать | Impact |
|---|---|---|
| 1 | Разбить `ai_parser/client.py` (998 строк) на модули | Maintainability |
| 2 | Извлечь интеграции из `process_intake_message` в orchestrator | SOLID (DI) |
| 3 | Добавить тесты для `bot/handlers.py` | Test coverage +5-8% |
| 4 | Добавить тесты для storefront POST и API endpoints | Test coverage +3-5% |
| 5 | Добавить latency logging для LLM calls | Observability |

---

## 11. Итоговая оценка по категориям

| Категория | Оценка | Комментарий |
|---|---|---|
| **Security** | 6/10 | Нет auth на endpoints (критично), secrets management корректен, нет SQLi |
| **Architecture (SOLID)** | 7/10 | Хорошая доменная модель, ABC для LLM, но God Module и нарушение DI |
| **Code Quality** | 8/10 | Чистый код, type hints, транзакции, один dead code |
| **Tests** | 7/10 | 77% coverage, хорошие бизнес-тесты, нет тестов бота и API |
| **ML/AI Practices** | 9/10 | Tolerant parsing, safety-net, shadow eval, canonical slots — отлично |
| **DevOps** | 7/10 | Docker + healthchecks, но runserver в prod, нет gunicorn |
| **Documentation** | 9/10 | README, plan, prompts, privacy-note, fallbacks log — исчерпывающе |
| **Общая** | **7.5/10** | Сильный MVP, требует auth и рефакторинга client.py для production |

---

## 12. Заключение

Проект демонстрирует зрелый инженерный подход к MVP: event sourcing через таблицы, формализованная state machine, мульти-провайдерный AI с эскалацией, tolerant parsing, idempotency, fallback-поведение. Основные рекомендации:

1. **Немедленно:** добавить аутентификацию на dashboard/API
2. **Quick win:** удалить dead code, добавить `update_fields`, fix bot callbacks
3. **Среднесрочно:** разбить God Module `client.py`, вынести интеграции из парсера
4. **Долгосрочно:** gunicorn, Celery, rate limiting, HTTPS enforcement
