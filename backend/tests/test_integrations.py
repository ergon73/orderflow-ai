from unittest.mock import patch

from django.test import TestCase

from integrations.delivery import apply_delivery_cost
from integrations.payment import mark_order_paid_if_succeeded
from integrations.sync import sync_order_to_bpium_safe
from orders.models import Customer, IntakeMessage, Order, OrderItem


class IntegrationTests(TestCase):
    def setUp(self):
        customer = Customer.objects.create(name="Integration User", phone="+79161234567")
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.WEB,
            raw_text="test",
            customer=customer,
            idempotency_key="integration_intake_1",
        )
        self.order = Order.objects.create(
            customer=customer,
            intake=intake,
            channel=IntakeMessage.Channel.WEB,
            status=Order.Status.CONFIRMED,
            delivery_city="Москва",
        )
        OrderItem.objects.create(order=self.order, title="кружка", quantity=1)

    def test_apply_delivery_cost(self):
        apply_delivery_cost(self.order)
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.delivery_cost)

    def test_bpium_sync_returns_false_when_not_configured(self):
        with patch("integrations.sync.BpiumClient") as bpium_cls:
            instance = bpium_cls.return_value
            instance.is_configured = False
            self.assertFalse(sync_order_to_bpium_safe(self.order))

    def test_bpium_sync_updates_record_id(self):
        with patch("integrations.sync.BpiumClient") as bpium_cls:
            instance = bpium_cls.return_value
            instance.is_configured = True
            instance.find_record_by_external_id.return_value = None
            instance.create_record.return_value = "rec_123"

            self.assertTrue(sync_order_to_bpium_safe(self.order))
            self.order.refresh_from_db()
            self.assertEqual(self.order.bpium_record_id, "rec_123")

    def test_bpium_sync_upserts_existing_record_by_external_id(self):
        with patch("integrations.sync.BpiumClient") as bpium_cls:
            instance = bpium_cls.return_value
            instance.is_configured = True
            instance.find_record_by_external_id.return_value = "rec_existing"
            instance.update_record.return_value = "rec_existing"

            self.assertTrue(sync_order_to_bpium_safe(self.order))
            self.order.refresh_from_db()
            instance.create_record.assert_not_called()
            instance.update_record.assert_called_once()
            self.assertEqual(self.order.bpium_record_id, "rec_existing")

    def test_bpium_sync_fallback_on_exception(self):
        with patch("integrations.sync.BpiumClient") as bpium_cls:
            instance = bpium_cls.return_value
            instance.is_configured = True
            instance.find_record_by_external_id.return_value = None
            instance.create_record.side_effect = Exception("bpium down")
            self.assertFalse(sync_order_to_bpium_safe(self.order))

    def test_mark_paid_if_succeeded(self):
        self.assertFalse(self.order.is_paid)
        mark_order_paid_if_succeeded(self.order, {"status": "succeeded"})
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertIsNotNone(self.order.paid_at)
