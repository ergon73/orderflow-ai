from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import TestCase

from integrations.apiship import map_apiship_status_to_order_status
from integrations.bpium import BpiumClient
from integrations.delivery import calculate_delivery_cost
from integrations.delivery import apply_delivery_cost
from integrations.apiship import calculate_delivery_cost_apiship
from integrations.apiship import create_shipment_for_order_safe, sync_shipping_status_safe
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

    @patch("integrations.delivery.calculate_delivery_cost_apiship")
    def test_apply_delivery_cost_prefers_apiship_when_available(self, apiship_cost):
        apiship_cost.return_value = Decimal("123.45")
        apply_delivery_cost(self.order)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_cost, Decimal("123.45"))

    @patch("integrations.delivery.calculate_delivery_cost_apiship")
    def test_apply_delivery_cost_falls_back_to_tariff_when_apiship_unavailable(self, apiship_cost):
        apiship_cost.return_value = None
        self.assertEqual(calculate_delivery_cost("Москва", order=self.order), Decimal("350.00"))

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

    @patch.dict(
        "os.environ",
        {
            "APISHIP_ENABLED": "true",
            "APISHIP_PROVIDER_KEY": "cse",
            "APISHIP_TARIFF_ID": "595",
            "APISHIP_FROM_CITY": "Москва",
            "APISHIP_FROM_ADDRESS": "Тестовая 1",
        },
        clear=False,
    )
    @patch("integrations.apiship.ApiShipClient")
    def test_apiship_create_shipment_sets_tracking_fields(self, apiship_cls):
        instance = apiship_cls.return_value
        instance.is_configured = True
        instance.create_order.return_value = {
            "id": "ship-14",
            "providerNumber": "TRK-123",
            "trackingUrl": "https://track.local/TRK-123",
            "status": {"key": "in_transit", "name": "В пути"},
        }

        ok = create_shipment_for_order_safe(self.order)
        self.assertTrue(ok)
        instance.create_order.assert_called_once()
        payload = instance.create_order.call_args.args[0]
        self.assertEqual(payload["order"]["providerKey"], "cse")
        self.assertEqual(payload["order"]["tariffId"], 595)
        self.assertEqual(payload["order"]["pickupType"], 1)
        self.assertEqual(payload["order"]["deliveryType"], 1)
        self.assertEqual(payload["cost"]["assessedCost"], 1.0)
        self.assertEqual(payload["cost"]["codCost"], 0.0)
        self.assertEqual(payload["places"][0]["length"], 10)
        self.assertEqual(payload["places"][0]["width"], 10)
        self.assertEqual(payload["places"][0]["height"], 10)
        self.assertEqual(payload["places"][0]["items"][0]["assessedCost"], 1.0)

        self.order.refresh_from_db()
        self.assertEqual(self.order.shipping_provider, "apiship")
        self.assertEqual(self.order.shipping_external_id, f"orderflow-{self.order.id}")
        self.assertEqual(self.order.track_number, "TRK-123")
        self.assertEqual(self.order.tracking_url, "https://track.local/TRK-123")
        self.assertEqual(self.order.shipping_status_raw, "in_transit")
        self.assertIsNotNone(self.order.shipping_synced_at)

    @patch.dict("os.environ", {"APISHIP_ENABLED": "true"}, clear=False)
    @patch("integrations.apiship.ApiShipClient")
    def test_apiship_status_sync_updates_order(self, apiship_cls):
        self.order.shipping_provider = "apiship"
        self.order.shipping_external_id = "ship-15"
        self.order.save(update_fields=["shipping_provider", "shipping_external_id", "updated_at"])

        instance = apiship_cls.return_value
        instance.is_configured = True
        instance.get_order_status.return_value = {
            "status": {"key": "delivered", "name": "Доставлен"},
            "providerNumber": "TRK-999",
            "trackingUrl": "https://track.local/TRK-999",
        }

        ok = sync_shipping_status_safe(self.order, update_order_status=False)
        self.assertTrue(ok)

        self.order.refresh_from_db()
        self.assertEqual(self.order.track_number, "TRK-999")
        self.assertEqual(self.order.tracking_url, "https://track.local/TRK-999")
        self.assertEqual(self.order.shipping_status_raw, "delivered")

    @patch.dict(
        "os.environ",
        {
            "APISHIP_ENABLED": "true",
            "APISHIP_FROM_CITY": "Москва",
            "APISHIP_FROM_ADDRESS": "Тестовая 1",
        },
        clear=False,
    )
    @patch("integrations.apiship.ApiShipClient")
    def test_apiship_calculator_parses_nested_tariffs(self, apiship_cls):
        instance = apiship_cls.return_value
        instance.is_configured = True
        instance.calculate.return_value = {
            "deliveryToDoor": [
                {
                    "providerKey": "cse",
                    "tariffs": [
                        {"tariffId": 595, "deliveryCost": 768.60},
                    ],
                }
            ]
        }

        cost = calculate_delivery_cost_apiship(self.order)
        self.assertEqual(cost, Decimal("768.60"))


class BpiumMappingTests(SimpleTestCase):
    def test_map_payload_skips_unmapped_fields_when_map_defined(self):
        client = BpiumClient(field_map={"external_id": "2", "status": "7"})
        mapped = client._map_payload(
            {
                "external_id": "14",
                "status": "confirmed",
                "tracking_url": "https://track.local/TRK-1",
            }
        )
        self.assertEqual(mapped, {"2": "14", "7": "confirmed"})


class ApiShipStatusMapTests(SimpleTestCase):
    def test_status_mapping(self):
        self.assertEqual(map_apiship_status_to_order_status("created"), Order.Status.IN_PROGRESS)
        self.assertEqual(map_apiship_status_to_order_status("uploading"), Order.Status.IN_PROGRESS)
        self.assertEqual(map_apiship_status_to_order_status("in_transit"), Order.Status.SHIPPED)
        self.assertEqual(map_apiship_status_to_order_status("delivered"), Order.Status.DELIVERED)
