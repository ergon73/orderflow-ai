# Техническое задание: OrderFlow AI
## AI-система обработки заказов для e-commerce (ФИНАЛ)

### 1. Общая информация

| Параметр | Значение |
|----------|----------|
| Название | OrderFlow AI |
| Тип | Веб-приложение + Telegram-бот |
| Срок MVP | 14 дней |
| Сложность | 5 из 5 |
| Автор | Георгий |

---

### 2. Описание и концепция

Система принимает заказы из двух каналов (Telegram-бот и веб-форма), извлекает структурированные данные из свободного текста с помощью LLM, ведёт жизненный цикл заказа через конечный автомат статусов, и предоставляет менеджеру веб-дашборд для управления заказами и аналитики.

**Ключевая ценность:** Клиент пишет «Хочу 3 красных кружки с доставкой на Ленина 42» — система автоматически извлекает товар, количество, адрес и создаёт структурированный заказ. Менеджер работает в веб-дашборде, а не в чатах.

**Принцип:** Дашборд — главный интерфейс. Бот — вторичный канал ввода. Не «бот-центричный» продукт, а полноценная веб-система.

---

### 3. Целевая аудитория и боли

**Аудитория:** Малый e-commerce бизнес (1–5 менеджеров), принимающий заказы через мессенджеры и сайт.

**Боли:** менеджеры вручную переносят данные из чатов в таблицы (ошибки, потеря заказов); нет единого места для отслеживания статуса; клиенты пишут в свободной форме; нет аналитики.

---

### 4. Функциональные требования

#### 4.1 Приём заказов (2 канала)

**Telegram-бот:** принимает текст на естественном языке, задаёт уточняющие вопросы если AI не извлёк ключевые поля, отправляет подтверждение с распознанными данными, позволяет клиенту подтвердить или скорректировать, уведомляет об изменении статуса.

**Веб-форма:** страница с полем свободного текста + структурированные поля как fallback, валидация на клиенте и сервере, подтверждение приёма.

#### 4.2 AI-парсинг заказов (двухфазная архитектура)

**Фаза 1 — Intake (сырой ввод):** Входящее сообщение сохраняется как `IntakeMessage` (raw_text + канал + клиент). Это отделяет сырые данные от распознанных. Идея заимствована у Модели-1 — архитектурно превосходит прямое создание заказа.

**Фаза 2 — Extraction (AI-парсинг):** `IntakeMessage` отправляется в LLM через библиотеку **Instructor** (constrained decoding). Результат сохраняется как `ExtractionAttempt` с полями: result_json, confidence, missing_fields. Если confidence < 0.7 или missing_fields не пусто — статус `NEEDS_INFO`, бот задаёт уточнения. Если extraction прошёл успешно — создаётся `Order`.

**Контракт AI-парсинга (Pydantic + Instructor):**

```python
class OrderExtract(BaseModel):
    chain_of_thought: str = Field(...,
        description="Сначала распиши на русском, какие товары нашёл, "
                    "как понял адрес и есть ли неоднозначности")
    items: list[OrderItem]          # [{title, qty, size?, color?}]
    customer: CustomerInfo          # {name?, phone?, email?}
    delivery: DeliveryInfo          # {address?, city?}
    comment: str | None = None
    missing_fields: list[str] = []  # что нужно уточнить
    clarifying_questions: list[str] = []
    confidence: float               # 0.0–1.0
```

> **chain_of_thought** — ключевой приём для gpt-4o-mini на русском языке. Модель сначала «рассуждает» в свободной форме, потом заполняет JSON. Это повышает accuracy на сложных фразах (сленг, опечатки, сокращения). Поле НЕ сохраняется в заказ — используется только для парсинга и отладки (видно ход «мыслей» модели в ExtractionAttempt.result_json).

**Вызов через Instructor** (гарантированно возвращает валидный Pydantic-объект, автоматический retry при ошибках схемы):

```python
import instructor
client = instructor.from_openai(openai.OpenAI())

extract = client.chat.completions.create(
    model="gpt-4o-mini",
    response_model=OrderExtract,
    max_retries=3,              # 1 попытка + 2 ретрая с передачей ошибки обратно в LLM
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": raw_text}
    ]
)
# extract — уже валидный OrderExtract, не нужен json.loads()
# extract.chain_of_thought — ход рассуждений (для отладки)
```

**Пост-валидация телефонов** — LLM извлекает «сырой» телефон, затем `phonenumbers` нормализует в E.164:

```python
import phonenumbers

def normalize_phone(raw: str) -> str | None:
    try:
        parsed = phonenumbers.parse(raw, "RU")
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None
# "8-916-123-45-67" → "+79161234567"
# "89031112233"     → "+79031112233"
```

**KPI:** Точность извлечения ≥ 85% на тестовом наборе из 50 заказов.

#### 4.3 Жизненный цикл заказа (State Machine)

```
NEW → NEEDS_INFO → CONFIRMED → IN_PROGRESS → SHIPPED → DELIVERED
                                    ↓              ↓
                                CANCELLED       RETURNED
```

Статус `NEEDS_INFO` (от Модели-1) — критически важен. Он отделяет «заказ принят, но данных не хватает» от «заказ подтверждён и готов к работе». Каждый переход фиксируется с timestamp, актором и комментарием.

**Формализованная матрица переходов** (production-паттерн из эталонных OMS):

```python
VALID_TRANSITIONS = {
    'new':         ['needs_info', 'confirmed', 'cancelled'],
    'needs_info':  ['confirmed', 'cancelled'],
    'confirmed':   ['in_progress', 'cancelled'],
    'in_progress': ['shipped', 'cancelled'],
    'shipped':     ['delivered', 'returned'],
    'delivered':   [],
    'cancelled':   [],
    'returned':    [],
}
```

Метод `change_status()` проверяет матрицу перед каждым переходом — невалидные переходы невозможны на уровне бизнес-логики.

#### 4.3.1 Slot Filling: паттерн уточняющего диалога

Когда AI определяет `missing_fields` (статус NEEDS_INFO), бот переходит в режим **Slot Filling** — дополнение неполного заказа через уточняющие вопросы.

**Принцип:** При новом сообщении клиента отправляем в LLM **текущий неполный JSON + новое сообщение**, а не всю историю:

```python
# Промпт для дополнения (slot filling):
"""
Текущий заказ (неполный): {current_extraction_json}
Новое сообщение клиента: "{new_message}"
Задача: Обнови поля заказа на основе нового сообщения. 
Не меняй поля, которые уже заполнены, если клиент не просит это явно.
"""
```

**Пример потока:**
1. Клиент: «Хочу пиццу» → AI: `{items: [{title: "пицца", qty: 1}], address: null}`, missing: [address]
2. Бот: «Куда доставить?»
3. Клиент: «На Ленина 1» → AI получает текущий JSON + «На Ленина 1»
4. AI: `{items: [{title: "пицца", qty: 1}], address: "Ленина 1"}`, missing: [] → CONFIRMED

**Хранение состояния:** Текущий неполный JSON хранится в `ExtractionAttempt.result_json`. Не нужен Redis — при новом сообщении берём последний ExtractionAttempt для этого клиента, мержим с новым через LLM, сохраняем как новый ExtractionAttempt.

**Преимущества:** экономия токенов (не шлём всю историю чата), повышение accuracy (модель работает в режиме «дополни», а не «пойми с нуля»), аудит (каждый ExtractionAttempt = итерация уточнения).

#### 4.4 Дашборд менеджера (ГЛАВНЫЙ ИНТЕРФЕЙС)

Таблица заказов с фильтрами (статус, дата, канал), поиск по клиенту/товару, карточка заказа (все данные + история статусов + исходный текст клиента), inline-кнопки смены статуса через HTMX, базовая статистика (Chart.js), экспорт в CSV.

#### 4.5 Имитация оплаты и доставки

Кнопка «Сформировать счёт» → PDF. Имитация оплаты — кнопка «Оплачено» (без реального шлюза). Имитация доставки — фейковый трек-номер.

> README: «Проект использует тестовый режим. Реальные платежи и доставка не обрабатываются.»

---

### 5. Архитектура

#### 5.1 Схема потока данных

```
Client (TG/Web)
  → Ingestion: сохранить IntakeMessage (raw_text + channel + idempotency_key)
  → AI Parser: Instructor + gpt-4o-mini → OrderExtract (Pydantic, auto-retry)
  → Validator: missing_fields?
    → Да: статус NEEDS_INFO, бот задаёт вопросы
    → Нет: @transaction.atomic → создать Order + OrderItems + History
  → Dashboard: менеджер видит заказ
```

#### 5.2 Компоненты

```
┌────────────────────────────────────────────────────────────┐
│  КЛИЕНТЫ: Telegram Bot (aiogram) │ Веб-форма (Django)     │
└───────────────┬────────────────────────────┬───────────────┘
                │                            │
┌───────────────▼────────────────────────────▼───────────────┐
│  BACKEND: Django + DRF                                     │
│  • POST /api/intake/     — приём сырого сообщения          │
│  • GET/PATCH /api/orders/ — CRUD заказов                   │
│  • POST /api/orders/{id}/status/ — смена статуса           │
│  • GET /api/stats/       — аналитика                       │
│                                                            │
│  AI Parser: Instructor + OpenAI (gpt-4o-mini)              │
│  LLMClient (ABC) → InstructorOpenAIClient / MockLLMClient  │
│  Validator: Pydantic + VALID_TRANSITIONS матрица            │
│  Services: @transaction.atomic для создания заказов         │
└───────────────┬────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────┐
│  ХРАНЕНИЕ: PostgreSQL                                      │
│  IntakeMessage (+ idempotency_key) → ExtractionAttempt     │
│  → Order → OrderItem │ OrderStatusHistory │ Customer       │
└───────────────┬────────────────────────────────────────────┘
                │
┌───────────────▼────────────────────────────────────────────┐
│  ДАШБОРД: Django templates + HTMX + Chart.js               │
│  Таблица заказов │ Карточка │ Статистика │ Экспорт CSV     │
└────────────────────────────────────────────────────────────┘
```

#### 5.3 Ключевые архитектурные решения

**Django, а не FastAPI.** Опыт с Django уже есть. Django ORM + Admin + templates — всё ускоряет разработку. Django Admin как fallback-дашборд если не успеешь кастомный.

**PostgreSQL, а не Google Sheets.** Sheets как primary storage — сигнал «не умею работать с БД». PostgreSQL — 30 минут настройки, реальный навык. Sheets можно добавить как опциональный экспорт.

**HTMX, а не React/Streamlit.** HTMX даёт интерактивность (inline-edit статусов, live-фильтры) без JavaScript. Streamlit — инструмент data science, не production web-app.

**Monolith, а не микросервисы.** Один Django-проект с apps: `orders`, `bot`, `dashboard`, `ai_parser`.

**IntakeMessage + ExtractionAttempt** (заимствовано у Модели-1). Отделяет сырой ввод от распознанного результата. Позволяет хранить историю попыток парсинга, retry, аудит. Архитектурно превосходит прямое создание Order из текста.

#### 5.4 Production-паттерны (адаптированные из эталонной OMS-архитектуры)

Эти паттерны заимствованы из production-систем уровня Amazon/Shopify, но адаптированы для MVP. Каждый добавляет ~10 минут работы, но демонстрирует инженерную зрелость.

**Абстрактный LLM-клиент** — позволяет заменить модель без изменения бизнес-логики:

```python
# ai_parser/client.py
from abc import ABC, abstractmethod

class LLMClient(ABC):
    @abstractmethod
    def parse(self, text: str) -> OrderExtract:
        raise NotImplementedError

class InstructorOpenAIClient(LLMClient):
    """Production: Instructor + gpt-4o-mini"""
    def parse(self, text: str) -> OrderExtract:
        return self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=OrderExtract,
            messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": text}]
        )

class MockLLMClient(LLMClient):
    """Для тестов без API-вызовов"""
    def parse(self, text: str) -> OrderExtract:
        return OrderExtract(items=[], confidence=0.0, missing_fields=["all"])
```

**Транзакционная целостность** — заказ и его позиции создаются атомарно:

```python
# orders/services.py
from django.db import transaction

@transaction.atomic
def create_order_from_extraction(extraction: OrderExtract, intake: IntakeMessage):
    order = Order.objects.create(intake=intake, customer=intake.customer, ...)
    for item in extraction.items:
        OrderItem.objects.create(order=order, title=item.title, quantity=item.qty)
    OrderStatusHistory.objects.create(
        order=order, old_status='', new_status='confirmed', changed_by='system'
    )
    return order
```

**Идемпотентность intake** — `idempotency_key` на IntakeMessage предотвращает дублирование заказов при повторной обработке одного и того же сообщения Telegram (сетевые сбои, webhook-ретраи).

**Event sourcing через таблицы** — IntakeMessage → ExtractionAttempt → Order — это реляционная реализация принципа event sourcing. При масштабировании заменяется на Kafka-events без изменения бизнес-логики.

#### 5.4 Модели данных

```python
class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, blank=True)
    telegram_id = models.BigIntegerField(null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

class IntakeMessage(models.Model):
    """Сырое входящее сообщение — до AI-обработки"""
    channel = models.CharField(max_length=20)  # telegram / web
    raw_text = models.TextField()
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True)
    # TG: f"tg_{chat_id}_{message_id}" — защита от дублей при retry
    created_at = models.DateTimeField(auto_now_add=True)

class ExtractionAttempt(models.Model):
    """Результат одной попытки AI-парсинга"""
    intake = models.ForeignKey(IntakeMessage, on_delete=models.CASCADE)
    model_name = models.CharField(max_length=50)  # gpt-4o-mini
    result_json = models.JSONField()
    confidence = models.FloatField()
    missing_fields = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

class Order(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Новый'
        NEEDS_INFO = 'needs_info', 'Требует уточнения'
        CONFIRMED = 'confirmed', 'Подтверждён'
        IN_PROGRESS = 'in_progress', 'В обработке'
        SHIPPED = 'shipped', 'Отправлен'
        DELIVERED = 'delivered', 'Доставлен'
        CANCELLED = 'cancelled', 'Отменён'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    intake = models.ForeignKey(IntakeMessage, on_delete=models.CASCADE)
    channel = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    delivery_address = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    track_number = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    title = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True)

class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='history')
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    comment = models.TextField(blank=True)
    changed_by = models.CharField(max_length=100)
    changed_at = models.DateTimeField(auto_now_add=True)
```

---

### 6. Технологический стек

| Компонент | Технология | Обоснование |
|-----------|-----------|-------------|
| Backend | Django 5.x + DRF | Опыт, ORM, Admin, templates |
| Telegram Bot | aiogram 3.x | Опыт, async |
| БД | PostgreSQL 16 | Реальная СУБД, JSONField |
| AI | OpenAI API (gpt-4o-mini) + **Instructor** | Constrained decoding, auto-retry, Pydantic |
| Валидация данных | **phonenumbers** | Нормализация телефонов RU → E.164 |
| Фронт дашборда | Django templates + HTMX + Chart.js | Интерактивность без SPA |
| PDF | WeasyPrint | Генерация счетов |
| Контейнеризация | Docker + docker-compose | Обязательно для портфолио |
| Линтинг | ruff | Быстрый, заменяет flake8+isort+black |
| Тесты | pytest + pytest-django | Стандарт |

---

### 7. Границы проекта

#### В MVP (ДЕЛАЕМ)

| # | Функция | Приоритет |
|---|---------|-----------|
| 1 | IntakeMessage + ExtractionAttempt + Order модели | P0 |
| 2 | Telegram-бот: приём текста, уточнение, подтверждение | P0 |
| 3 | AI-парсинг с Pydantic-валидацией | P0 |
| 4 | Веб-форма заказа | P0 |
| 5 | Дашборд: таблица, фильтры, карточка, смена статуса | P0 |
| 6 | State machine с NEEDS_INFO | P0 |
| 7 | Docker-compose (Django + PostgreSQL + бот) | P0 |
| 8 | Уведомления клиенту в Telegram | P1 |
| 9 | Статистика: Chart.js графики | P1 |
| 10 | PDF-счёт + экспорт CSV | P2 |
| 11 | Опциональный экспорт в Google Sheets | P2 |

#### За рамками MVP (НЕ ДЕЛАЕМ)

Email-парсинг, реальные платежи (ЮKassa/Stripe), реальная доставка (СДЭК), ML-прогнозы, мобильное приложение, каталог товаров, многоязычность, ролевая модель, Redis/Celery (синхронный парсинг для MVP достаточен).

---

### 8. Сквозные сценарии (Acceptance Criteria)

**Сценарий A — Telegram (happy path):**
1. Клиент пишет боту: «Нужны 2 футболки M синие, доставка на Ленина 15, телефон +79161234567»
2. AI извлекает: items=[{title: "футболка M синяя", qty: 2}], address="Ленина 15", phone="+79161234567"
3. Бот отвечает: «Ваш заказ: 2× футболка M синяя, доставка на Ленина 15. Подтвердить?»
4. Клиент нажимает «Подтвердить»
5. Заказ создаётся, менеджер видит его в дашборде

**Сценарий B — Telegram (Slot Filling — неполные данные):**
1. Клиент: «Хочу кружку»
2. AI извлекает: `{items: [{title: "кружка", qty: 1}], address: null}`, missing_fields: [address, phone]
3. Бот: «Уточните, пожалуйста: куда доставить и ваш телефон?»
4. Клиент: «3 штуки на Пушкина 10, тел 89161234567»
5. AI получает текущий JSON + новое сообщение → Slot Filling → `{items: [{qty: 3}], address: "Пушкина 10", phone: "89161234567"}`
6. Пост-валидация: phonenumbers → "+79161234567"
7. missing_fields: [] → CONFIRMED → заказ создаётся

**Сценарий C — Веб-форма:**
1. Клиент заполняет форму (текст + телефон)
2. Заказ появляется в дашборде со статусом NEW/NEEDS_INFO

**Критерий прохождения:** В 8/10 тестовых сообщениях корректно создаётся заказ или запрашиваются адекватные уточнения.

---

### 9. Нефункциональные требования

| Требование | Значение |
|------------|---------|
| Время обработки заказа (вкл. LLM) | < 10 секунд |
| Время отклика дашборда | < 2 секунды |
| Повторяемость парсинга | Стабильный результат (temperature=0) |
| Безопасность | Секреты в .env, HTTPS в production |
| Конфиденциальность | Privacy-заметка в README (какие данные хранятся) |

---

### 10. Ограничения и риски

| Риск | Вероятность | Влияние | Митигация |
|------|------------|---------|-----------|
| AI «галлюцинирует» | Средняя | Высокое | Instructor (auto-retry) + Pydantic + NEEDS_INFO + ручная правка |
| Бюджет OpenAI | Низкая | Среднее | gpt-4o-mini ($0.15/1M), лимит 100 заказов/день |
| Не успеть дашборд | Средняя | Высокое | Django Admin как fallback |
| Scope creep | Высокая | Критическое | Жёсткая фиксация P0, переключение на резерв |
| Дубли заказов (webhook retry) | Низкая | Среднее | idempotency_key на IntakeMessage |

**Бюджет API:** ~$5–10 за весь период разработки.

---

### 11. Метрики успеха

| Метрика | Целевое значение |
|---------|-----------------|
| Точность AI-парсинга | ≥ 85% на 50 тестовых заказах |
| Время обработки | < 10 секунд |
| Количество каналов | 2 (Telegram + веб) |
| Количество статусов | 7 (вкл. NEEDS_INFO) |
| Покрытие тестами | ≥ 50% бизнес-логики |

---

### 12. Definition of Done

Проект считается сданным, если:
1. Публичный GitHub-репозиторий с README (как запустить локально и в Docker)
2. Рабочий MVP по всем трём сквозным сценариям (A, B, C)
3. 50 тестовых заказов обработаны, accuracy ≥ 85%
4. Docker-compose: одна команда — всё поднимается
5. Скриншоты всех интерфейсов (12+)
6. Видео-демо (5–7 минут)
7. Библиотека промптов (документ)

---

### 13. План реализации

| Дни | Задачи | Результат | Чекпоинт |
|-----|--------|-----------|----------|
| 1 | Django + PostgreSQL + Docker + GitHub + модели | Пустой проект запускается | docker-compose up работает |
| 2 | IntakeMessage + ExtractionAttempt + Admin | Данные создаются через Admin | Модели видны в Admin |
| 3 | AI: Instructor + Pydantic (chain_of_thought) + phonenumbers + тесты | Текст → OrderExtract JSON | 5 тестовых текстов парсятся |
| 4 | Бот (manage.py run_bot): приём → парсинг → подтверждение → Order | **СКВОЗНОЙ СЦЕНАРИЙ** | Текст в боте → заказ в Admin |
| 5 | Веб-форма: страница + валидация + создание заказа | Второй канал работает | Форма → заказ в Admin |
| 6 | Дашборд: таблица заказов + фильтры HTMX | Менеджер видит заказы | Фильтры работают |
| 7 | Дашборд: карточка заказа + смена статуса + история | Менеджер управляет заказами | Статус меняется inline |
| 8 | NEEDS_INFO + Slot Filling (уточняющий диалог) + уведомления | Неполные заказы обрабатываются | Сценарий B проходит |
| 9 | Статистика Chart.js + счётчики | Аналитика на дашборде | Графики рендерятся |
| 10 | PDF-счёт + CSV-экспорт | Документы генерируются | PDF скачивается |
| 11 | Тестирование: 50 заказов + фикс багов | Стабильный MVP | accuracy ≥ 85% |
| 12 | Docker-compose финал: бот + Django + PG + Nginx | Всё одной командой | Чистый запуск |
| 13 | README + скриншоты + демо-данные (seed) | GitHub оформлен | README полный |
| 14 | Видео-демо + библиотека промптов | Материалы для сдачи | Всё загружено |

**Точка переключения на резерв (день 4):** Если нет работающего сквозного сценария «текст в боте → заказ в Admin» — переключаемся на генератор документации.

---

### 14. Структура репозитория

```
orderflow-ai/
├── docker-compose.yml
├── .env.example
├── README.md
├── docs/
│   ├── ТЗ.md
│   ├── prompts.md
│   └── screenshots/
├── backend/
│   ├── Dockerfile
│   ├── manage.py
│   ├── requirements.txt
│   ├── config/                # settings, urls, wsgi
│   ├── orders/                # модели, views, serializers, state machine
│   │   ├── models.py          # Customer, IntakeMessage, ExtractionAttempt, Order, OrderItem
│   │   ├── services.py        # @transaction.atomic, create_order_from_extraction, change_status
│   │   ├── state_machine.py   # VALID_TRANSITIONS матрица
│   │   └── admin.py           # Django Admin конфигурация
│   ├── ai_parser/             # промпты, Pydantic-схемы, LLM-клиент
│   │   ├── schemas.py         # OrderExtract (с chain_of_thought), CustomerInfo, DeliveryInfo
│   │   ├── client.py          # LLMClient (ABC) → InstructorOpenAIClient, MockLLMClient
│   │   ├── validators.py      # phonenumbers нормализация, пост-валидация полей
│   │   └── prompts.py         # системные промпты + slot filling промпт
│   ├── bot/                   # aiogram handlers
│   │   ├── management/
│   │   │   └── commands/
│   │   │       └── run_bot.py # Management command: python manage.py run_bot
│   │   ├── handlers.py        # /start, обработка текста, подтверждение
│   │   └── keyboards.py       # inline-кнопки
│   ├── dashboard/             # Django views + templates
│   │   ├── views.py           # OrderListView, OrderDetailView, StatsView
│   │   ├── templates/
│   │   └── static/            # CSS, Chart.js
│   └── tests/
│       ├── test_parser.py     # 50 тестовых заказов (MockLLMClient + реальный)
│       ├── test_orders.py     # state machine, CRUD, транзакционность
│       ├── test_idempotency.py # проверка idempotency_key
│       └── fixtures/          # тестовые данные
├── nginx/
│   └── nginx.conf
└── scripts/
    └── seed_data.py           # генерация 20 демо-заказов
```

---

### 15. Что говорить на собеседовании

> «Я построил омниканальную систему обработки заказов с AI-парсингом. Клиент пишет в Telegram или на сайте на естественном языке — Instructor + Pydantic гарантируют извлечение структурированных данных с автоматическим retry при ошибках схемы. Архитектура основана на production-паттернах OMS: event sourcing через IntakeMessage → ExtractionAttempt → Order, формализованная state machine с матрицей переходов, idempotency на уровне intake, транзакционная атомарность через @transaction.atomic, абстракция LLM-клиента для замены модели без изменения бизнес-логики. Django + PostgreSQL + aiogram + OpenAI API, развёрнуто в Docker. Точность парсинга — 87% на 50 тестовых заказах. При масштабировании IntakeMessage заменяется на Kafka-events, синхронный парсинг — на Celery-воркеры без рефакторинга бизнес-слоя.»
