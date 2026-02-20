from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from unittest.mock import patch

from orders.models import Customer, IntakeMessage, Order


class ApiAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="api_manager",
            password="pass1234",
        )
        customer = Customer.objects.create(name="API User", phone="+79161234567")
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.WEB,
            raw_text="test",
            customer=customer,
            idempotency_key="api_auth_intake_1",
        )
        self.order = Order.objects.create(
            customer=customer,
            intake=intake,
            channel=IntakeMessage.Channel.WEB,
            status=Order.Status.NEW,
        )

    def test_api_orders_list_requires_auth(self):
        response = self.client.get("/api/orders/")
        self.assertIn(response.status_code, {401, 403})

    def test_api_orders_list_allows_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/orders/")
        self.assertEqual(response.status_code, 200)

    def test_api_order_detail_requires_auth(self):
        response = self.client.get(f"/api/orders/{self.order.id}/")
        self.assertIn(response.status_code, {401, 403})

    def test_api_status_patch_requires_auth(self):
        response = self.client.patch(
            f"/api/orders/{self.order.id}/status/",
            data={"status": Order.Status.CONFIRMED},
            content_type="application/json",
        )
        self.assertIn(response.status_code, {401, 403})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.NEW)

    def test_api_status_patch_allows_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/orders/{self.order.id}/status/",
            data={"status": Order.Status.CONFIRMED},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)

    def test_api_status_patch_rejects_invalid_payload(self):
        self.client.force_login(self.user)
        response = self.client.patch(
            f"/api/orders/{self.order.id}/status/",
            data={"status": "definitely-invalid-status"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("orders.api_views.APIUserThrottle.get_rate", return_value="1/min")
    def test_api_list_is_rate_limited(self, _mock_rate):
        self.client.force_login(self.user)

        first = self.client.get("/api/orders/")
        second = self.client.get("/api/orders/")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
