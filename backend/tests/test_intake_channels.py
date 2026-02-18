from django.test import Client, TestCase

from ai_parser.client import MockLLMClient
from ai_parser.services import process_intake_message
from orders.models import IntakeMessage, Order
from orders.services import (
    create_email_intake,
    create_telegram_intake,
    create_web_intake,
    get_or_create_email_customer,
    get_or_create_telegram_customer,
    get_or_create_web_customer,
)


class IntakeChannelTests(TestCase):
    def test_telegram_idempotency(self):
        customer = get_or_create_telegram_customer(telegram_id=101, display_name="TG User")
        intake1, created1 = create_telegram_intake(
            customer=customer,
            text="Хочу кружку на Ленина 10",
            chat_id=10,
            message_id=20,
        )
        intake2, created2 = create_telegram_intake(
            customer=customer,
            text="Хочу кружку на Ленина 10",
            chat_id=10,
            message_id=20,
        )

        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(intake1.id, intake2.id)

    def test_web_intake_creates_order(self):
        customer = get_or_create_web_customer(name="Web User", phone="89161234567")
        intake = create_web_intake(customer=customer, text="Хочу 2 кружки на Ленина 10")

        order, attempt = process_intake_message(intake=intake, llm_client=MockLLMClient())

        self.assertEqual(order.channel, IntakeMessage.Channel.WEB)
        self.assertIn(order.status, [Order.Status.NEEDS_INFO, Order.Status.CONFIRMED])
        self.assertEqual(attempt.order_id, order.id)

    def test_email_intake_idempotency(self):
        customer = get_or_create_email_customer(
            from_email="mail@example.com",
            display_name="Email User",
        )
        intake1, created1 = create_email_intake(
            customer=customer,
            text="Нужна футболка M",
            mailbox="INBOX",
            uidvalidity="123",
            uid="456",
        )
        intake2, created2 = create_email_intake(
            customer=customer,
            text="Нужна футболка M",
            mailbox="INBOX",
            uidvalidity="123",
            uid="456",
        )

        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(intake1.id, intake2.id)

    def test_swagger_is_available(self):
        client = Client()
        response = client.get("/api/docs/")
        self.assertEqual(response.status_code, 200)
