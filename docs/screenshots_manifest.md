# Скриншоты для сдачи (S10-10)

Каталог: `docs/screenshots/`

## Список кадров

1. `01_storefront.png` - витрина (главный экран).
2. `02_storefront_filled_form.png` - заполненная форма заказа.
3. `03_storefront_success.png` - успешное создание заказа из витрины.
4. `04_admin_login.png` - вход в Django Admin.
5. `05_admin_index.png` - главная страница Admin.
6. `06_admin_orders_list.png` - список заказов в Admin.
7. `07_admin_order_detail.png` - карточка заказа в Admin.
8. `08_dashboard_orders.png` - таблица заказов в менеджерском дашборде.
9. `09_dashboard_orders_filtered.png` - дашборд с фильтрами (status).
10. `10_dashboard_order_detail.png` - детальная карточка заказа.
11. `11_dashboard_stats.png` - аналитика/графики.
12. `12_api_docs_swagger.png` - Swagger (`/api/docs/`).
13. `13_bpium_login_or_home.png` - Bpium (login/home страница).
14. `14_dashboard_channel_telegram.png` - дашборд, фильтр `channel=telegram`.
15. `15_dashboard_channel_email.png` - дашборд, фильтр `channel=email`.

## Как переснять автоматически

```bash
node scripts/capture_screenshots.mjs
```

Опциональные env:

- `DEMO_BASE_URL` (default: `http://127.0.0.1:8001`)
- `DEMO_ADMIN_USER` (default: `demo_admin`)
- `DEMO_ADMIN_PASSWORD` (default: `DemoAdmin123!`)
- `DEMO_SCREENSHOT_DIR` (default: `docs/screenshots`)
