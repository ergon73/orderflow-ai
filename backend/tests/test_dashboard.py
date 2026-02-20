from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.contrib.auth import get_user_model
from unittest.mock import patch

from orders.models import Customer, IntakeMessage, Order, OrderItem


class DashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="manager",
            password="pass1234",
        )
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(name="Manager Test", phone="+79161234567")
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.WEB,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="web_test_1",
        )
        self.order = Order.objects.create(
            customer=self.customer,
            intake=intake,
            channel=IntakeMessage.Channel.WEB,
            status=Order.Status.NEW,
            delivery_address="Ленина 10",
        )
        OrderItem.objects.create(order=self.order, title="кружка", quantity=1)

    def test_dashboard_pages_require_login(self):
        anon = Client()
        response = anon.get("/dashboard/orders/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_storefront_post_creates_order_success_response(self):
        anon = Client()

        def _fake_process(*, intake, **kwargs):
            order = Order.objects.create(
                customer=intake.customer,
                intake=intake,
                channel=intake.channel,
                status=Order.Status.CONFIRMED,
                delivery_address="Тверская 1",
            )
            attempt = type("Attempt", (), {"missing_fields": [], "result_json": {}})
            return order, attempt

        with patch("dashboard.views.process_intake_message", side_effect=_fake_process):
            response = anon.post(
                "/storefront/",
                data={
                    "name": "Storefront User",
                    "phone": "+79160000000",
                    "email": "storefront@example.com",
                    "selected_product": "Кружка",
                    "quantity": 2,
                    "free_text": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заказ принят")

    @override_settings(STOREFRONT_RATE_LIMIT_REQUESTS=1, STOREFRONT_RATE_LIMIT_WINDOW_SECONDS=60)
    def test_storefront_post_is_rate_limited(self):
        anon = Client()

        def _fake_process(*, intake, **kwargs):
            order = Order.objects.create(
                customer=intake.customer,
                intake=intake,
                channel=intake.channel,
                status=Order.Status.CONFIRMED,
                delivery_address="Тверская 1",
            )
            attempt = type("Attempt", (), {"missing_fields": [], "result_json": {}})
            return order, attempt

        payload = {
            "name": "Rate Limited User",
            "phone": "+79160000001",
            "email": "ratelimit@example.com",
            "selected_product": "Кружка",
            "quantity": 1,
            "free_text": "",
        }

        with patch("dashboard.views.process_intake_message", side_effect=_fake_process):
            first = anon.post("/storefront/", data=payload, REMOTE_ADDR="203.0.113.10")
            second = anon.post("/storefront/", data=payload, REMOTE_ADDR="203.0.113.10")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)

    def test_order_list_page_is_available(self):
        response = self.client.get("/dashboard/orders/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.order.id}")

    def test_order_list_filters_by_status(self):
        response = self.client.get("/dashboard/orders/", {"status": Order.Status.NEW})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{self.order.id}")

    def test_invalid_status_transition_is_blocked(self):
        response = self.client.post(
            f"/dashboard/orders/{self.order.id}/status/",
            data={"status": Order.Status.DELIVERED},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.NEW)

    def test_mark_paid_endpoint(self):
        response = self.client.post(
            f"/dashboard/orders/{self.order.id}/mark-paid/",
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertIsNotNone(self.order.paid_at)

    def test_stats_page_is_available(self):
        response = self.client.get("/dashboard/stats/")
        self.assertEqual(response.status_code, 200)

    def test_csv_export_returns_attachment(self):
        response = self.client.get("/dashboard/export/csv/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=orders_export.csv", response["Content-Disposition"])
        self.assertIn("order_id", response.content.decode("utf-8"))

    def test_csv_export_contains_expected_columns(self):
        response = self.client.get("/dashboard/export/csv/")
        self.assertEqual(response.status_code, 200)
        first_line = response.content.decode("utf-8").splitlines()[0]
        header_columns = first_line.split(",")
        expected = [
            "order_id",
            "created_at",
            "channel",
            "status",
            "customer_name",
            "phone",
            "delivery_address",
            "is_paid",
            "paid_at",
            "delivery_cost",
            "total_amount",
            "track_number",
            "shipping_provider",
            "shipping_external_id",
            "tracking_url",
            "shipping_status_raw",
            "shipping_synced_at",
            "bpium_record_id",
        ]
        self.assertEqual(header_columns, expected)

    def test_invoice_view_returns_file_or_html_fallback(self):
        response = self.client.get(f"/dashboard/orders/{self.order.id}/invoice/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response["Content-Type"], ["application/pdf", "text/html; charset=utf-8"])

    def test_dashboard_order_detail_returns_404_for_unknown_order(self):
        response = self.client.get("/dashboard/orders/999999/")
        self.assertEqual(response.status_code, 404)

    def test_dashboard_status_update_returns_404_for_unknown_order(self):
        response = self.client.post(
            "/dashboard/orders/999999/status/",
            data={"status": Order.Status.CONFIRMED},
        )
        self.assertEqual(response.status_code, 404)

    def test_create_payment_link_persists_payment_id_in_comment(self):
        with patch(
            "dashboard.views.create_payment",
            return_value={
                "payment_id": "pay_123",
                "confirmation_url": "https://pay.example/confirm",
            },
        ) as create_payment_mock:
            response = self.client.post(
                f"/dashboard/orders/{self.order.id}/payment-link/",
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertIn("[payment_id:pay_123]", self.order.comment)
        create_payment_mock.assert_called_once()

    def test_refresh_payment_status_marks_order_paid(self):
        with patch(
            "dashboard.views.get_payment",
            return_value={"status": "succeeded", "id": "pay_123"},
        ) as get_payment_mock:
            with patch("dashboard.views.sync_order_to_bpium_safe", return_value=True) as sync_mock:
                response = self.client.post(
                    f"/dashboard/orders/{self.order.id}/payment-refresh/",
                    data={"payment_id": "pay_123"},
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertIsNotNone(self.order.paid_at)
        get_payment_mock.assert_called_once_with("pay_123")
        sync_mock.assert_called_once()

    def test_refresh_payment_status_requires_payment_id(self):
        response = self.client.post(
            f"/dashboard/orders/{self.order.id}/payment-refresh/",
            data={"payment_id": ""},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)
