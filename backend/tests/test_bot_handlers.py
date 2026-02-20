from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import TestCase

from bot.handlers import (
    cancel_order_handler,
    confirm_order_handler,
    edit_order_handler,
    order_message_handler,
)
from orders.models import Customer, IntakeMessage, Order


class _DummyMessage:
    def __init__(self):
        self.answer_calls: list[tuple[str, dict]] = []

    async def answer(self, text: str, **kwargs):
        self.answer_calls.append((text, kwargs))


class _DummyIncomingMessage(_DummyMessage):
    def __init__(self, *, user_id: int, text: str):
        super().__init__()
        self.from_user = SimpleNamespace(
            id=user_id,
            full_name="Telegram User",
            username="telegram_user",
        )
        self.chat = SimpleNamespace(id=555)
        self.message_id = 777
        self.text = text


class _DummyCallback:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _DummyMessage()
        self.answer_calls: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False):
        self.answer_calls.append((text, show_alert))


class BotCallbackSecurityTests(TestCase):
    def setUp(self):
        customer = Customer.objects.create(
            name="Telegram Owner",
            phone="+79161234567",
            telegram_id=111,
        )
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="test",
            customer=customer,
            idempotency_key="tg_bot_security_1",
        )
        self.order = Order.objects.create(
            customer=customer,
            intake=intake,
            channel=IntakeMessage.Channel.TELEGRAM,
            status=Order.Status.NEW,
        )

    def test_confirm_callback_rejects_invalid_order_id(self):
        callback = _DummyCallback("order:confirm:not-int", user_id=111)
        async_to_sync(confirm_order_handler)(callback)
        self.assertEqual(callback.answer_calls, [("Некорректные данные", True)])

    def test_edit_callback_rejects_invalid_order_id(self):
        callback = _DummyCallback("order:edit:not-int", user_id=111)
        async_to_sync(edit_order_handler)(callback)
        self.assertEqual(callback.answer_calls, [("Некорректные данные", True)])

    def test_cancel_callback_rejects_invalid_order_id(self):
        callback = _DummyCallback("order:cancel:not-int", user_id=111)
        async_to_sync(cancel_order_handler)(callback)
        self.assertEqual(callback.answer_calls, [("Некорректные данные", True)])

    def test_confirm_callback_rejects_foreign_order(self):
        callback = _DummyCallback(f"order:confirm:{self.order.id}", user_id=222)

        with patch("bot.handlers._load_order", new=AsyncMock(return_value=self.order)):
            with patch("bot.handlers.change_order_status") as change_status:
                async_to_sync(confirm_order_handler)(callback)

        self.assertEqual(callback.answer_calls, [("Это не ваш заказ", True)])
        change_status.assert_not_called()

    def test_edit_callback_rejects_foreign_order(self):
        callback = _DummyCallback(f"order:edit:{self.order.id}", user_id=222)

        with patch("bot.handlers._load_order", new=AsyncMock(return_value=self.order)):
            with patch("bot.handlers.request_order_edit") as request_edit:
                async_to_sync(edit_order_handler)(callback)

        self.assertEqual(callback.answer_calls, [("Это не ваш заказ", True)])
        request_edit.assert_not_called()

    def test_confirm_callback_owner_happy_path(self):
        callback = _DummyCallback(f"order:confirm:{self.order.id}", user_id=111)

        def _change_status_side_effect(*args, **kwargs):
            order = kwargs["order"]
            order.status = Order.Status.CONFIRMED
            return order

        with patch("bot.handlers._load_order", new=AsyncMock(return_value=self.order)):
            with patch("bot.handlers.change_order_status", new=MagicMock(side_effect=_change_status_side_effect)) as change_status:
                with patch("bot.handlers.sync_order_to_bpium_safe", new=MagicMock(return_value=True)) as sync_bpium:
                    with patch("bot.handlers.apiship_auto_create_on_confirmed", new=MagicMock(return_value=False)):
                        async_to_sync(confirm_order_handler)(callback)

        self.assertTrue(any("подтверждён" in text for text, _ in callback.message.answer_calls))
        self.assertEqual(callback.answer_calls, [(None, False)])
        change_status.assert_called_once()
        sync_bpium.assert_called_once()

    def test_order_message_handler_needs_info_prompts_for_clarification(self):
        self.order.status = Order.Status.NEEDS_INFO
        self.order.save(update_fields=["status", "updated_at"])
        message = _DummyIncomingMessage(user_id=111, text="Хочу кружку, уточню позже")
        attempt = SimpleNamespace(
            missing_fields=["customer.phone"],
            result_json={"clarifying_questions": ["Укажите телефон"]},
        )

        with patch("bot.handlers.get_or_create_telegram_customer", return_value=self.order.customer):
            with patch("bot.handlers.create_telegram_intake", return_value=(self.order.intake, True)):
                with patch("bot.handlers._load_context_order", new=AsyncMock(return_value=None)):
                    with patch("bot.handlers.get_active_needs_info_order", return_value=None):
                        with patch("bot.handlers.process_intake_message", return_value=(self.order, attempt)):
                            async_to_sync(order_message_handler)(message)

        self.assertEqual(len(message.answer_calls), 1)
        answer_text, kwargs = message.answer_calls[0]
        self.assertIn("Уточните данные", answer_text)
        self.assertIn("Укажите телефон", answer_text)
        self.assertIn("reply_markup", kwargs)
