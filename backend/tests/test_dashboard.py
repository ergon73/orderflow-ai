from django.test import Client, TestCase

from orders.models import Customer, IntakeMessage, Order, OrderItem


class DashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
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

    def test_invoice_view_returns_file_or_html_fallback(self):
        response = self.client.get(f"/dashboard/orders/{self.order.id}/invoice/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response["Content-Type"], ["application/pdf", "text/html; charset=utf-8"])
