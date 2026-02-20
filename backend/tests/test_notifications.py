from unittest.mock import patch

from django.test import TestCase

from bot.notifications import send_order_status_notification
from orders.models import Customer, IntakeMessage, Order


class NotificationTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name="Notify User",
            phone="+79161234567",
            telegram_id=123456,
        )
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="test",
            customer=self.customer,
            idempotency_key="notify_intake_1",
        )
        self.order = Order.objects.create(
            customer=self.customer,
            intake=intake,
            channel=IntakeMessage.Channel.TELEGRAM,
            status=Order.Status.NEW,
        )

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}, clear=False)
    @patch("bot.notifications.requests.post")
    def test_notification_returns_false_without_token(self, mocked_post):
        ok = send_order_status_notification(self.order)
        self.assertFalse(ok)
        mocked_post.assert_not_called()

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123456:TEST_TOKEN"}, clear=False)
    @patch("bot.notifications.requests.post")
    def test_notification_returns_false_without_telegram_id(self, mocked_post):
        self.order.customer.telegram_id = None
        self.order.customer.save(update_fields=["telegram_id", "updated_at"])

        ok = send_order_status_notification(self.order)
        self.assertFalse(ok)
        mocked_post.assert_not_called()

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123456:TEST_TOKEN"}, clear=False)
    @patch("bot.notifications.requests.post")
    def test_notification_sends_message_successfully(self, mocked_post):
        mocked_post.return_value.raise_for_status.return_value = None

        ok = send_order_status_notification(self.order)

        self.assertTrue(ok)
        mocked_post.assert_called_once()

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123456:TEST_TOKEN"}, clear=False)
    @patch("bot.notifications.requests.post")
    def test_notification_handles_request_error(self, mocked_post):
        mocked_post.side_effect = Exception("network down")
        with self.assertLogs("bot.notifications", level="WARNING") as logs:
            ok = send_order_status_notification(self.order)

        self.assertFalse(ok)
        self.assertTrue(any("failed_to_send_telegram_status_notification" in line for line in logs.output))
