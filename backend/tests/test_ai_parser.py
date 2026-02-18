from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError

from ai_parser.client import MockLLMClient
from ai_parser.schemas import CustomerInfo, DeliveryInfo, OrderExtract, OrderItem
from ai_parser.services import process_intake_message
from ai_parser.validators import apply_post_validation, normalize_phone
from orders.models import Customer, IntakeMessage, Order, OrderStatusHistory


class ValidatorTests(SimpleTestCase):
    def test_normalize_phone_valid(self):
        self.assertEqual(normalize_phone("8-916-123-45-67"), "+79161234567")

    def test_normalize_phone_invalid(self):
        self.assertIsNone(normalize_phone("123"))

    def test_post_validation_adds_missing_for_empty_extract(self):
        extract = OrderExtract()
        validated = apply_post_validation(extract)
        self.assertIn("items", validated.missing_fields)
        self.assertIn("delivery.address", validated.missing_fields)
        self.assertIn("customer.phone", validated.missing_fields)

    def test_post_validation_normalizes_phone(self):
        extract = OrderExtract(
            items=[OrderItem(title="кружка", qty=1)],
            delivery=DeliveryInfo(address="Ленина 10"),
            customer=CustomerInfo(phone="89161234567"),
        )
        validated = apply_post_validation(extract)
        self.assertEqual(validated.customer.phone, "+79161234567")
        self.assertNotIn("customer.phone", validated.missing_fields)

    def test_post_validation_short_address_marks_missing(self):
        extract = OrderExtract(
            items=[OrderItem(title="кружка", qty=1)],
            delivery=DeliveryInfo(address="дом"),
            customer=CustomerInfo(phone="89161234567"),
        )
        validated = apply_post_validation(extract)
        self.assertIn("delivery.address", validated.missing_fields)

    def test_schema_rejects_invalid_values(self):
        with self.assertRaises(ValidationError):
            OrderExtract(items=[OrderItem(title="кружка", qty=0)], confidence=1.2)


class ParserServiceTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name="Test User")

    def test_process_intake_creates_confirmed_order(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 2 кружки на Ленина 10 телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_1_1",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=MockLLMClient())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.items.count(), 1)
        self.assertTrue(attempt.is_success)
        self.assertEqual(attempt.order_id, order.id)

    def test_process_intake_creates_needs_info_order(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_1_2",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=MockLLMClient())

        self.assertEqual(order.status, Order.Status.NEEDS_INFO)
        self.assertIn("customer.phone", attempt.missing_fields)

    def test_slot_filling_updates_existing_order(self):
        first_intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_1_3",
        )
        order, _ = process_intake_message(
            intake=first_intake,
            llm_client=MockLLMClient(),
        )
        self.assertEqual(order.status, Order.Status.NEEDS_INFO)

        second_intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_1_4",
        )
        updated_order, attempt = process_intake_message(
            intake=second_intake,
            llm_client=MockLLMClient(),
            order=order,
        )

        self.assertEqual(updated_order.id, order.id)
        self.assertEqual(updated_order.status, Order.Status.CONFIRMED)
        self.assertEqual(updated_order.items.count(), 1)
        self.assertTrue(attempt.is_success)

    def test_status_history_created_on_transition(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_1_5",
        )

        order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())
        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 1)

        intake2 = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_1_6",
        )
        process_intake_message(intake=intake2, llm_client=MockLLMClient(), order=order)

        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 2)

    def test_mock_client_uses_predefined_response(self):
        response = OrderExtract(
            chain_of_thought="ok",
            items=[OrderItem(title="футболка", qty=2)],
            customer=CustomerInfo(phone="+79161234567"),
            delivery=DeliveryInfo(address="Пушкина 10"),
            confidence=0.95,
        )
        client = MockLLMClient(responses=[response])

        parsed = client.parse("ignored")
        self.assertEqual(parsed.items[0].title, "футболка")
        self.assertEqual(parsed.confidence, 0.95)

    def test_manual_review_enabled_after_repeated_failures(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_1_7",
        )
        order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())
        self.assertEqual(order.status, Order.Status.NEEDS_INFO)

        for idx in range(3):
            retry_intake = IntakeMessage.objects.create(
                channel=IntakeMessage.Channel.TELEGRAM,
                raw_text="Все еще хочу кружку на Ленина 10",
                customer=self.customer,
                idempotency_key=f"tg_1_retry_{idx}",
            )
            order, _ = process_intake_message(
                intake=retry_intake,
                llm_client=MockLLMClient(),
                order=order,
            )

        order.refresh_from_db()
        self.assertTrue(order.needs_manual_review)

    def test_parallel_orders_do_not_mix_when_order_is_explicit(self):
        intake_a = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_parallel_a",
        )
        order_a, _ = process_intake_message(intake=intake_a, llm_client=MockLLMClient())

        intake_b = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу футболку на Пушкина 20",
            customer=self.customer,
            idempotency_key="tg_parallel_b",
        )
        order_b, _ = process_intake_message(intake=intake_b, llm_client=MockLLMClient())

        self.assertEqual(order_a.status, Order.Status.NEEDS_INFO)
        self.assertEqual(order_b.status, Order.Status.NEEDS_INFO)

        intake_fix_a = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_parallel_fix_a",
        )
        updated_a, _ = process_intake_message(
            intake=intake_fix_a,
            llm_client=MockLLMClient(),
            order=order_a,
        )

        order_b.refresh_from_db()
        self.assertEqual(updated_a.id, order_a.id)
        self.assertEqual(updated_a.status, Order.Status.CONFIRMED)
        self.assertEqual(order_b.status, Order.Status.NEEDS_INFO)
