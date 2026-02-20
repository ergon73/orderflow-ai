# Production Readiness Roadmap (post-MVP)

Цель: зафиксировать обязательные доработки перед приёмкой в production.
Этот план не отменяет закрытие MVP (`GATE-3`), а формирует отдельный контур эксплуатационной готовности.

---

## 1) Security Hardening

- [ ] `PRD-SEC-01` Перевести внешний контур на HTTPS с валидным сертификатом (Let's Encrypt или корпоративный CA).
- [ ] `PRD-SEC-02` Включить принудительный `HTTP -> HTTPS` redirect и HSTS.
- [ ] `PRD-SEC-03` Включить secure-настройки Django для production:
`SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`.
- [ ] `PRD-SEC-04` Внедрить управление секретами через Vault/Secrets Manager (без хранения production-секретов в `.env`).
- [ ] `PRD-SEC-05` Настроить регулярную ротацию ключей/паролей и регламент emergency rotation.
- [ ] `PRD-SEC-06` Закрыть административный контур RBAC + MFA для операторов/админов.

## 2) Observability & Monitoring

- [ ] `PRD-OBS-01` Перейти на структурированные JSON-логи с `request_id`/`order_id`/`trace_id`.
- [ ] `PRD-OBS-02` Подключить централизованный сбор логов (ELK/Loki/Cloud Logging).
- [ ] `PRD-OBS-03` Ввести метрики приложения и инфраструктуры (Prometheus/Grafana).
- [ ] `PRD-OBS-04` Настроить алертинг по SLA/SLO:
ошибки 5xx, деградация latency, недоступность интеграций, рост retry/fallback.
- [ ] `PRD-OBS-05` Подключить error tracking (Sentry или аналог) с классификацией инцидентов.
- [ ] `PRD-OBS-06` Подготовить runbooks для типовых аварий (DB down, provider outage, bot downtime).

## 3) Backup, Restore, DR (RPO/RTO)

- [ ] `PRD-DR-01` Утвердить целевые значения:
`RPO` (допустимая потеря данных) и `RTO` (время восстановления), с согласованием владельца бизнеса.
- [ ] `PRD-DR-02` Настроить автоматические бэкапы БД (full + incremental/WAL/PITR).
- [ ] `PRD-DR-03` Хранить бэкапы в отдельном контуре (offsite/object storage), шифровать at-rest.
- [ ] `PRD-DR-04` Ввести регулярные тесты восстановления:
минимум ежеквартально, с протоколом фактических `RPO/RTO`.
- [ ] `PRD-DR-05` Настроить контроль целостности и срока хранения бэкапов (retention policy).
- [ ] `PRD-DR-06` Зафиксировать Disaster Recovery Plan и ответственных on-call.

## 4) Vendor Management & SLA Requirements

- [ ] `PRD-VND-01` Утвердить требования к платёжному провайдеру:
SLA доступности, webhook-signature, идемпотентность, incident communication, соответствие PCI DSS/локальным нормам.
- [ ] `PRD-VND-02` Утвердить требования к службе доставки:
SLA API, стабильность статусов, максимальная задержка обновления трекинга, sandbox parity, регламент поддержки.
- [ ] `PRD-VND-03` Утвердить требования к почтовому контуру:
SPF/DKIM/DMARC, SLA доступности IMAP/SMTP, обработка bounce/complaints.
- [ ] `PRD-VND-04` Определить поддержку и эскалацию у каждого провайдера:
каналы связи, матрица приоритетов, время реакции/решения.
- [ ] `PRD-VND-05` Подготовить fallback-поставщиков и критерии переключения (vendor failover strategy).
- [ ] `PRD-VND-06` Зафиксировать требования к контрактам:
SLA, ответственность, хранение/экспорт данных, условия расторжения и миграции.

## 5) Pentest Program & Release Gate

- [ ] `PRD-PEN-01` Выполнить pre-pentest checklist (security headers, authz matrix, secret hygiene, rate limits).
- [ ] `PRD-PEN-02` Провести внешний пентест (web/API/infra) сертифицированной командой.
- [ ] `PRD-PEN-03` Закрыть findings по SLA remediation:
Critical/High до релиза, Medium по согласованному плану.
- [ ] `PRD-PEN-04` Провести re-test и оформить sign-off от security/compliance.
- [ ] `PRD-PEN-05` Ввести policy:
релиз в production запрещён при открытых Critical/High security findings.

## 6) Support Model & Competency Requirements

- [ ] `PRD-SUP-01` Утвердить целевую модель поддержки:
внутренняя, аутсорсная или гибридная (L1/L2/L3).
- [ ] `PRD-SUP-02` Зафиксировать матрицу компетенций по уровням:
L1 (операционные сценарии), L2 (платформа и интеграции), L3 (разработка/hotfix).
- [ ] `PRD-SUP-03` Утвердить SLA/OLA поддержки:
матрица приоритетов P1/P2/P3, `first response`, `resolution time`, эскалации.
- [ ] `PRD-SUP-04` Описать процесс incident/problem management:
on-call график, handover, postmortem, CAPA.
- [ ] `PRD-SUP-05` Для аутсорса зафиксировать обязательные требования:
NDA, least-privilege доступ, аудит действий, требования к резервной смене.
- [ ] `PRD-SUP-06` Для критичных интеграций зафиксировать контактную карту:
каналы эскалации провайдеров (платёжка/доставка/email), окна поддержки.
- [ ] `PRD-SUP-07` Ввести регулярные тренировки поддержки:
минимум ежеквартальные drills по инцидентам и восстановлению.

## 7) Production Acceptance Criteria

- [ ] `PRD-GATE-01` Подтверждённые `RPO/RTO` достигнуты на тестах восстановления.
- [ ] `PRD-GATE-02` Мониторинг/алертинг покрывает бизнес-критичные сценарии intake/payment/delivery.
- [ ] `PRD-GATE-03` Подписанные SLA с внешними поставщиками и формализованные каналы поддержки.
- [ ] `PRD-GATE-04` Pentest закрыт, re-test пройден, release gate открыт.
- [ ] `PRD-GATE-05` Пройден Go-Live Readiness Review (бизнес + тех + security).
- [ ] `PRD-GATE-06` Модель поддержки и компетенции L1/L2/L3 подтверждены, SLA/OLA достижимы на учениях.

---

## Почему это уместно для MVP-документации

Да, это нормальная и правильная практика: MVP может быть закрыт как продуктовая гипотеза,
а production-readiness оформляется отдельным roadmap/чеклистом с измеримыми критериями приёмки.
