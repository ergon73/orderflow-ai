# Fallback Scenarios Log

Краткий журнал сработавших fallback-сценариев и принятых обходов.

## 1) LLM provider outage in Telegram handler
- Симптом: при ошибке LLM бот не отвечал пользователю.
- Обход: добавлен безопасный ответ пользователю и логирование ошибки в `bot/handlers.py`.
- Результат: intake не "зависает" без ответа.

## 2) Bpium sync field mismatch
- Симптом: `400 field not found` при синхронизации в CRM.
- Обход: проброшен `BPIUM_FIELD_MAP` в контейнеры и синхронизирован с каталогом.
- Результат: upsert в Bpium проходит, pipeline заказа не падает.

## 3) ApiShip calculator/order errors
- Симптом: в части кейсов ApiShip возвращает валидационные ошибки адреса.
- Обход: fallback на локальные тарифы (`integrations/delivery.py`) и safe-wrapper для вызовов ApiShip.
- Результат: заказ остаётся операбельным даже при недоступности/ошибках ApiShip.

## 4) GigaChat TLS / certificate verification
- Симптом: ошибки TLS при `verify_ssl=true`.
- Обход: установка сертификата Минцифры + `GIGACHAT_CERT_PATH` в окружении.
- Результат: OAuth/chat completion работают со строгой TLS-проверкой.

## 5) Missing provider model in account
- Симптом: speed-пара `GigaChat-2-Lite` не доступна в `/models` для текущего аккаунта.
- Обход: speed-профиль временно переключен на `GigaChat-2`.
- Результат: парный speed-профиль остается рабочим без смешивания классов.
