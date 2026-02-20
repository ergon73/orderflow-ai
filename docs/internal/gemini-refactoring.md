# Экспертный анализ проекта OrderFlow AI и план рефакторинга

На основе предоставленной документации и анализа исходного кода (`settings.py`, `ai_parser`, `dashboard/views.py`, `orders/services.py` и др.), ниже представлен отчет о текущем состоянии проекта по 4 ключевым направлениям и предложены быстрые улучшения (Quick Wins) и исправления.

---

## 1. Безопасность (Security: Secrets, SQLi)

**Текущее состояние:** 
В проекте повсеместно активно используется ORM (Django QuerySets), поэтому прямых рисков SQL-инъекций не обнаружено. Секреты подтягиваются через `os.getenv` и `.env` файлы, что соответствует 12-factor app подходу.

**Проблемы:**
1. **Insecure Defaults:** В `config/settings.py` по умолчанию `DEBUG = env_bool("DEBUG", True)`. При деплое на продакшен, если забыть установить `DEBUG=False`, проект запустится с включенным дебагом, утекая конфигурацию.
2. **Weak Secret Key:** `SECRET_KEY = os.getenv("SECRET_KEY", "change-me")`. Опять же, приложение не упадет, если забыть задать секретный ключ, а запустится с уязвимым ключом `"change-me"`.
3. **Logging:** Отсутствует фильтрация чувствительных данных (токенов, паролей Bpium/Apiship) при потенциальном логировании ошибок сетевых запросов в `_post_with_retry`.

### ⚡ Quick Wins & Fixes (Security):
- Изменить поведение по умолчанию в `settings.py`: 
  `DEBUG = env_bool("DEBUG", False)`
- Обязать наличие `SECRET_KEY` (Fail-fast): 
  Вместо fallback на `"change-me"`, выбрасывать `ImproperlyConfigured`, если переменная не задана.
- Заблокировать использование дефолтных кредов для интеграций (Yookassa, Bpium), если проект поднимается в `PROD` окружении.

---

## 2. Архитектура (SOLID, Паттерны)

**Текущее состояние:**
Архитектура превосходна для MVP (14 дней). Используется Service Layer (`orders/services.py`), State Machine (`orders/state_machine.py`) и паттерн Strategy/Adapter для LLM-клиентов (`LLMClient(ABC)`).

**Проблемы:**
1. **Single Responsibility Principle (SRP) в `dashboard/views.py`**:
   Представления (`views`) перегружены бизнес-логикой. В `storefront_view` мы видим конструирование текста заказа (`_build_raw_text`), вызов сервиса, парсинга клиента. В `order_status_update_view` контроллер напрямую управляет Side-эффектами: вызывает интеграции ApiShip, Bpium и отправку Telegram нотификаций. Это нарушает SRP и затрудняет тестирование.
2. **Fat Functions в AI Parser**:
   Файл `ai_parser/client.py` растянулся на почти 1000 строк. Логика отправки HTTP запросов, логика fallback-парсинга JSON и маппинг ответов смешаны.

### ⚡ Quick Wins & Fixes (Architecture):
- **Событийная модель (Signals / Observers)**: Перенести вызовы Bpium, ApiShip и Telegram-нотификаций из `views.py` в Django Signals `post_save` для модели `OrderStatusHistory` или инкапсулировать их в внутри Service Layer (`change_order_status` in `services.py`). View должен только принимать запрос и возвращать ответ HTTP.
- **Разделение ai_parser**: Выделить функции `_coerce_items`, `_extract_chain_of_thought_fallback` и нормализацию сырых словарей (JSON) в отдельный модуль `ai_parser/cleaners.py` или `mappers.py`.
- **Dependency Injection**: Прокидывать HTTP-сессию или транспортный уровень для API-клиентов (YandexGPT, GigaChat) извне, чтобы легче мокать их в тестах.

---

## 3. Баги и Тестирование (Bugs & Tests)

**Текущее состояние:**
Общий уровень покрытия равен **77%** (согласно `docs/coverage_report.txt`). Это отличный результат. Есть интеграционные тесты интеграции API-клиентов и стейт-машины. Отлично реализован fallback-механизм для нестабильного JSON от GigaChat / YandexGPT.

**Проблемы:**
1. **Низкое покрытие Dashboard (57%) и Integrations (50-66%)**: `dashboard/views.py` (57%), `bot/notifications.py` (35%), `integrations/payment.py` (50%). Опасность: при рефакторинге админки можно легко сломать логику отображения и нотификаций, так как там сконцентрированы Side-эффекты из-за нарушений SRP (см. Архитектура).
2. **Обработка исключений в `payment.py` и `apiship.py`**: Заглушки HTTP ошибок и `catch-all` (`except Exception`) могут замаскировать критические баги, если сервис интеграции обновил API.

### ⚡ Quick Wins & Fixes (Bugs & Tests):
- Написать 3-4 Request Factory или Client тестов на `dashboard/views.py` (в частности на `storefront_view` и `order_status_update_view`), чтобы поднять покрытие.
- Написать Unit-тест на логику форматирования нотификаций в `bot/notifications.py` (отвязать генерацию текста от метода отправки через aiogram).
- Использовать жесткую типизацию и кастомные Exception классы вместо generic `Exception` в интеграциях, чтобы не "глотать" непредвиденные системные ошибки.

---

## 4. Best Practices Python / ML

**Текущее состояние:**
Использование `Pydantic` с `Instructor` (Constrained decoding) - это индустриальный стандарт и отличный выбор для Production MVP. Отличная работа с нормализацией телефонов через `phonenumbers`.

**Проблемы:**
1. **Hardcoded Промпты в коде**: Внутри `ai_parser.client.py` есть жесткие строковые манипуляции (`_force_json_reply`, подстановка JSON). LLM-промпты вперемешку с кодом тяжелее поддерживать не-разработчикам.
2. **Отсутствие Structural Logging (structlog)**: В проекте на 5 внешних API-интеграций (TG, Bpium, ApiShip, YooKassa, LLMs) требуются унифицированные логи: `json={order_id: 123, system: "apiship", status: 502, retry: 2}`. Без этого дебаг в проде будет кошмаром.
3. **ML Fallbacks (GigaChat/YandexGPT)**: Написан массивный парсер ломаных JSON-ов с десятками проверок ключей в `client.py` (`_extract_chain_of_thought_fallback` и `_coerce_items`). Он очень хрупок (brittle).

### ⚡ Quick Wins & Fixes (Python / ML Best Practices):
- **Логирование**: Настроить Django `LOGGING` с выносом в stdout (для сбора Docker'ом). Добавить `structlog` для формализованного отслеживания pipeline-а: Intake -> Parse -> Order -> Sync.
- **Управление промптами**: Вынести промпты из кода в отдельный YAML/JSON или Django БД, либо использовать `Jinja2` темплейты (как это сделано, например, в LangChain/LlamaIndex) вместо `.format()`.
- **Защита ML пайплайна**: Для GigaChat/YandexGPT: если модель вернула плохой JSON, вместо сложных эвристик ручного парсинга (сотни строк `_coerce_XXX`), лучше сразу кидать Validation Error в структуре Pydantic и использовать встроенный retry (как это делает `Instructor`), отдавая ошибку модели на исправление (Re-prompting).

---

## 🏆 План рефакторинга (Итог "Что делать сейчас"):

1. **Security**: Зайти в `settings.py` и поменять `DEBUG=False` по умолчанию. Добавить `raise ImproperlyConfigured("SECRET_KEY is required")`.
2. **Связанность**: В `dashboard/views.py` перенести логику отправки интеграций (`Bpium`, `ApiShip`, `TG Notifications`) в конец функции `change_order_status` из `services.py` (или в Signals).
3. **Чистота кода**: Выделить из `ai_parser/client.py` вспомогательные функции по очистке и валидации JSON в отдельный файл `parsers.py`.
4. **Стабильность**: Написать тесты на `dashboard/views.py` для защиты от регрессии при изменении UI.
