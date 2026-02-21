import os
from unittest.mock import MagicMock
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError

from ai_parser.client import (
    GigaChatClient,
    InstructorOpenAIClient,
    MockLLMClient,
    YandexGPTClient,
    _parse_structured_response,
)
from ai_parser.schemas import CustomerInfo, DeliveryInfo, OrderExtract, OrderItem
from ai_parser.services import _load_previous_extraction, process_intake_message
from ai_parser.validators import apply_post_validation, normalize_phone
from orders.models import (
    Customer,
    ExtractionAttempt,
    IntakeMessage,
    Order,
    OrderStatusHistory,
)


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

    def test_post_validation_recalculates_missing_fields_from_canonical_slots(self):
        extract = OrderExtract(
            items=[OrderItem(title="кружка", qty=1)],
            delivery=DeliveryInfo(address="Москва, Арбат 5"),
            customer=CustomerInfo(phone="+79161234567"),
            missing_fields=["quantity.item", "address.new_address", "foo.bar"],
        )
        validated = apply_post_validation(extract)
        self.assertEqual(validated.missing_fields, [])


class StructuredResponseParsingTests(SimpleTestCase):
    def test_parse_structured_response_handles_unquoted_keys_and_item_aliases(self):
        raw = """
        {
          items: [
            {name: "кружка", quantity: "2"},
            {name: "футболка", quantity: 1}
          ],
          customer: {phone: "+79161234567"},
          delivery: {address: "Ленина 10"}
        }
        """
        parsed = _parse_structured_response(raw)
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].title, "кружка")
        self.assertEqual(parsed.items[0].qty, 2)

    def test_parse_structured_response_handles_product_name_alias(self):
        parsed = _parse_structured_response(
            {
                "items": [
                    {"product_name": "кружка", "quantity": 2},
                ]
            }
        )
        self.assertEqual(parsed.items[0].title, "кружка")
        self.assertEqual(parsed.items[0].qty, 2)

    def test_parse_structured_response_handles_chain_of_thought_list(self):
        raw_dict = {
            "chain_of_thought": ["шаг 1", "шаг 2"],
            "items": [{"title": "кружка", "qty": 1}],
        }
        parsed = _parse_structured_response(raw_dict)
        self.assertIn("шаг 1", parsed.chain_of_thought)
        self.assertIn("шаг 2", parsed.chain_of_thought)

    def test_extract_function_arguments_from_function_call(self):
        data = {
            "choices": [
                {
                    "message": {
                        "function_call": {
                            "name": "extract_order",
                            "arguments": '{"items":[{"title":"кружка","qty":1}]}',
                        }
                    }
                }
            ]
        }
        args = GigaChatClient._extract_function_arguments(data)
        self.assertIsInstance(args, str)
        parsed = _parse_structured_response(args)
        self.assertEqual(parsed.items[0].title, "кружка")

    def test_parse_structured_response_handles_chain_of_thought_object_payload(self):
        raw = """
        {
          "chain_of_thought": {
            "items": ["кружка", "худи"],
            "quantity": [3, 1],
            "address": "Москва, Ленинский проспект 45",
            "contact": "+7 (916) 123-45-67"
          },
          "missing_fields": [],
          "confidence": 1
        }
        """
        parsed = _parse_structured_response(raw)
        self.assertEqual(len(parsed.items), 2)
        self.assertEqual(parsed.items[0].title, "кружка")
        self.assertEqual(parsed.items[0].qty, 3)
        self.assertEqual(parsed.delivery.address, "Москва, Ленинский проспект 45")
        self.assertEqual(parsed.customer.phone, "+7 (916) 123-45-67")

    def test_parse_structured_response_handles_order_extract_alias_block(self):
        raw = """
        {
          "chain_of_thought": {
            "customer_message": "Хочу 2 кружки, доставка на Профсоюзную 20",
            "order_details": {
              "quantity": 2,
              "delivery_address": "ул. Профсоюзная 20",
              "delivery_contact": "8 916 123 45 67"
            }
          },
          "order_extract": {
            "quantity": 2,
            "delivery_address": "ул. Профсоюзная 20",
            "delivery_contact": "8 916 123 45 67"
          }
        }
        """
        parsed = _parse_structured_response(raw)
        self.assertEqual(parsed.delivery.address, "ул. Профсоюзная 20")
        self.assertEqual(parsed.customer.phone, "8 916 123 45 67")

    def test_parse_structured_response_handles_item_type_and_alias_fields(self):
        raw = """
        {
          "items": [{"type": "cup", "quantity": 3}],
          "delivery_address": "Москва, ул. Большая Никитская 14",
          "contact_number": "+79161234567",
          "missing_fields": ["item_type", "quantity"]
        }
        """
        parsed = _parse_structured_response(raw)
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.items[0].title, "кружка")
        self.assertEqual(parsed.items[0].qty, 3)
        self.assertEqual(parsed.delivery.address, "Москва, ул. Большая Никитская 14")
        self.assertEqual(parsed.customer.phone, "+79161234567")

    def test_parse_structured_response_handles_none_missing_fields(self):
        parsed = _parse_structured_response(
            {
                "items": [{"title": "кружка", "qty": 1}],
                "delivery": {"address": "Москва, Арбат 5"},
                "customer": {"phone": "+79161234567"},
                "missing_fields": None,
                "clarifying_questions": None,
            }
        )
        self.assertEqual(parsed.missing_fields, [])
        self.assertEqual(parsed.clarifying_questions, [])


class OpenAICompatibleFallbackTests(SimpleTestCase):
    def test_instructor_falls_back_to_raw_json_for_tool_parser_error(self):
        client = object.__new__(InstructorOpenAIClient)
        client.model_name = "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"
        client.max_retries = 3
        client._base_url = "http://127.0.0.1:8000/v1"
        client._client = MagicMock()
        client._raw_client = MagicMock()

        client._client.chat.completions.create.side_effect = ValueError(
            'tool_choice requires --tool-call-parser to be set'
        )

        message = type("Message", (), {"content": '{"items":[{"title":"кружка","qty":1}]}'})
        choice = type("Choice", (), {"message": message})
        raw_response = type("Response", (), {"choices": [choice]})
        client._raw_client.chat.completions.create.return_value = raw_response

        parsed = client.parse("Хочу 1 кружку")
        self.assertEqual(parsed.items[0].title, "кружка")
        self.assertEqual(parsed.items[0].qty, 1)
        self.assertEqual(client._raw_client.chat.completions.create.call_count, 1)


class CloudRetryTests(SimpleTestCase):
    @patch("ai_parser.client.time.sleep", return_value=None)
    @patch("ai_parser.client.requests.post")
    def test_yandex_retries_on_retryable_status_then_succeeds(self, mocked_post, _sleep):
        transient = MagicMock()
        transient.status_code = 503
        transient.headers = {}
        transient.close.return_value = None

        success = MagicMock()
        success.status_code = 200
        success.headers = {}
        success.json.return_value = {
            "result": {
                "alternatives": [
                    {"message": {"text": '{"items":[{"title":"кружка","qty":1}]}'}}
                ]
            }
        }
        mocked_post.side_effect = [transient, success]

        client = YandexGPTClient(
            api_key="fake",
            folder_id="folder-id",
            max_retries=1,
            retry_backoff_base=0.0,
            retry_backoff_max=0.0,
            retry_status_codes={503},
        )

        parsed = client.parse("Хочу 1 кружку")
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(mocked_post.call_count, 2)

    @patch("ai_parser.client.time.sleep", return_value=None)
    @patch("ai_parser.client.requests.post")
    def test_gigachat_retries_oauth_on_connection_error(self, mocked_post, _sleep):
        oauth_success = MagicMock()
        oauth_success.status_code = 200
        oauth_success.headers = {}
        oauth_success.json.return_value = {
            "access_token": "token",
            "expires_at": 4102444800000,
        }
        mocked_post.side_effect = [requests.ConnectionError("network"), oauth_success]

        client = GigaChatClient(
            auth_key="fake",
            max_retries=1,
            retry_backoff_base=0.0,
            retry_backoff_max=0.0,
        )

        token = client._get_access_token()
        self.assertEqual(token, "token")
        self.assertEqual(mocked_post.call_count, 2)


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

    def test_raw_text_fallback_fills_contact_and_address_when_llm_misses(self):
        class ItemsOnlyLLMClient:
            model_name = "items-only-test"

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="кружка", qty=1)],
                    confidence=0.5,
                )

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text=(
                "Хочу 1 кружку, доставка Москва, ул. Арбат 5, "
                "телефон +79161234567, email georgy.belyanin@gmail.com"
            ),
            customer=self.customer,
            idempotency_key="tg_fallback_1",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=ItemsOnlyLLMClient())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.customer.phone, "+79161234567")
        self.assertEqual(order.customer.email, "georgy.belyanin@gmail.com")
        self.assertIn("Арбат", order.delivery_address)
        self.assertFalse(attempt.missing_fields)

    def test_raw_text_fallback_fills_items_when_llm_returns_empty(self):
        class EmptyLLMClient:
            model_name = "empty-test"

            def parse(self, text, current_extraction=None):
                return OrderExtract(confidence=0.1)

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 2 кружки и 1 футболку, доставка Москва, ул. Арбат 5, телефон +79161234567",
            customer=self.customer,
            idempotency_key="tg_fallback_2",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=EmptyLLMClient())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.items.count(), 2)
        self.assertFalse(attempt.missing_fields)

    @patch.dict(
        os.environ,
        {
            "GIGACHAT_ESCALATION_ENABLED": "true",
            "GIGACHAT_ESCALATION_TEXT_LEN": "1",
            "GIGACHAT_ESCALATION_MISSING_FIELDS": "1",
        },
        clear=False,
    )
    @patch("ai_parser.services._build_gigachat_escalation_client")
    def test_gigachat_escalates_from_pro_to_max_for_complex_case(self, escalation_builder):
        class FakeGigaPro(GigaChatClient):
            def __init__(self):
                self.model_name = "GigaChat-2-Pro"
                self.auth_key = "fake"
                self.scope = "GIGACHAT_API_PERS"
                self.auth_url = "https://fake.local/oauth"
                self.api_url = "https://fake.local/chat"
                self.verify_ssl = True
                self.timeout = 5.0
                self._access_token = ""
                self._access_token_expires_at = 0.0

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="кружка", qty=1)],
                    confidence=0.5,
                )

        class FakeGigaMax(FakeGigaPro):
            def __init__(self):
                super().__init__()
                self.model_name = "GigaChat-2-Max"

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="кружка", qty=1)],
                    customer=CustomerInfo(phone="+79161234567", email="test@example.com"),
                    delivery=DeliveryInfo(address="Москва, Арбат 1"),
                    confidence=0.9,
                )

        escalation_builder.return_value = FakeGigaMax()

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 1 кружку",
            customer=self.customer,
            idempotency_key="tg_escalate_pro_to_max",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=FakeGigaPro())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(attempt.model_name, "GigaChat-2-Max")
        self.assertFalse(attempt.missing_fields)
        escalation_builder.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "GIGACHAT_ESCALATION_ENABLED": "true",
            "GIGACHAT_ESCALATION_TEXT_LEN": "1",
            "GIGACHAT_ESCALATION_MISSING_FIELDS": "1",
        },
        clear=False,
    )
    @patch("ai_parser.services._build_gigachat_escalation_client")
    def test_gigachat_fallback_to_max_when_pro_parse_fails(self, escalation_builder):
        class FailingGigaPro(GigaChatClient):
            def __init__(self):
                self.model_name = "GigaChat-2-Pro"
                self.auth_key = "fake"
                self.scope = "GIGACHAT_API_PERS"
                self.auth_url = "https://fake.local/oauth"
                self.api_url = "https://fake.local/chat"
                self.verify_ssl = True
                self.timeout = 5.0
                self._access_token = ""
                self._access_token_expires_at = 0.0

            def parse(self, text, current_extraction=None):
                raise ValueError("pro model parse failed")

        class FakeGigaMax(FailingGigaPro):
            def __init__(self):
                super().__init__()
                self.model_name = "GigaChat-2-Max"

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="футболка", qty=2)],
                    customer=CustomerInfo(phone="+79161234567"),
                    delivery=DeliveryInfo(address="Санкт-Петербург, Невский 10"),
                    confidence=0.85,
                )

        escalation_builder.return_value = FakeGigaMax()

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 2 футболки, доставка Санкт-Петербург, Невский 10, телефон +79161234567",
            customer=self.customer,
            idempotency_key="tg_escalate_on_error",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=FailingGigaPro())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(attempt.model_name, "GigaChat-2-Max")
        self.assertNotIn("customer.phone", attempt.missing_fields)
        self.assertNotIn("delivery.address", attempt.missing_fields)
        escalation_builder.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "YANDEXGPT_ESCALATION_ENABLED": "true",
            "YANDEXGPT_ESCALATION_TEXT_LEN": "1",
            "YANDEXGPT_ESCALATION_MISSING_FIELDS": "1",
        },
        clear=False,
    )
    @patch("ai_parser.services._build_yandex_escalation_client")
    def test_yandex_escalates_from_lite_to_full_for_complex_case(self, escalation_builder):
        class FakeYandexLite(YandexGPTClient):
            def __init__(self):
                self.model_name = "yandexgpt-lite"
                self.model_uri = "gpt://folder-id/yandexgpt-lite/latest"
                self.api_key = "fake"
                self.folder_id = "folder-id"
                self.endpoint = "https://fake.local/completion"
                self.timeout = 5.0

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="кружка", qty=1)],
                    confidence=0.4,
                )

        class FakeYandexFull(FakeYandexLite):
            def __init__(self):
                super().__init__()
                self.model_name = "yandexgpt"
                self.model_uri = "gpt://folder-id/yandexgpt/latest"

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="кружка", qty=1)],
                    customer=CustomerInfo(phone="+79161234567", email="test@example.com"),
                    delivery=DeliveryInfo(address="Москва, Арбат 1"),
                    confidence=0.9,
                )

        escalation_builder.return_value = FakeYandexFull()

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 1 кружку",
            customer=self.customer,
            idempotency_key="tg_yandex_escalate_lite_to_full",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=FakeYandexLite())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(attempt.model_name, "yandexgpt")
        self.assertFalse(attempt.missing_fields)
        escalation_builder.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "YANDEXGPT_ESCALATION_ENABLED": "true",
            "YANDEXGPT_ESCALATION_TEXT_LEN": "1",
            "YANDEXGPT_ESCALATION_MISSING_FIELDS": "1",
        },
        clear=False,
    )
    @patch("ai_parser.services._build_yandex_escalation_client")
    def test_yandex_fallback_to_full_when_lite_parse_fails(self, escalation_builder):
        class FailingYandexLite(YandexGPTClient):
            def __init__(self):
                self.model_name = "yandexgpt-lite"
                self.model_uri = "gpt://folder-id/yandexgpt-lite/latest"
                self.api_key = "fake"
                self.folder_id = "folder-id"
                self.endpoint = "https://fake.local/completion"
                self.timeout = 5.0

            def parse(self, text, current_extraction=None):
                raise ValueError("yandex lite parse failed")

        class FakeYandexFull(FailingYandexLite):
            def __init__(self):
                super().__init__()
                self.model_name = "yandexgpt"
                self.model_uri = "gpt://folder-id/yandexgpt/latest"

            def parse(self, text, current_extraction=None):
                return OrderExtract(
                    items=[OrderItem(title="футболка", qty=2)],
                    customer=CustomerInfo(phone="+79161234567"),
                    delivery=DeliveryInfo(address="Санкт-Петербург, Невский 10"),
                    confidence=0.85,
                )

        escalation_builder.return_value = FakeYandexFull()

        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 2 футболки, доставка Санкт-Петербург, Невский 10, телефон +79161234567",
            customer=self.customer,
            idempotency_key="tg_yandex_escalate_on_error",
        )

        order, attempt = process_intake_message(intake=intake, llm_client=FailingYandexLite())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(attempt.model_name, "yandexgpt")
        self.assertNotIn("customer.phone", attempt.missing_fields)
        self.assertNotIn("delivery.address", attempt.missing_fields)
        escalation_builder.assert_called_once()

    def test_load_previous_extraction_ignores_shadow_attempts(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10 телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_shadow_prev_1",
        )
        order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())

        ExtractionAttempt.objects.create(
            intake=intake,
            order=order,
            model_name="shadow:gigachat:GigaChat-2-Pro",
            result_json={},
            confidence=0.0,
            missing_fields=["shadow_error"],
            is_success=False,
        )

        previous = _load_previous_extraction(order)
        self.assertIsNotNone(previous)
        self.assertTrue(previous.items)
        self.assertEqual(previous.items[0].title, "кружка")

    def test_manual_review_counter_ignores_shadow_attempts(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_shadow_manual_1",
        )
        order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())
        self.assertEqual(order.status, Order.Status.NEEDS_INFO)

        for idx in range(10):
            ExtractionAttempt.objects.create(
                intake=intake,
                order=order,
                model_name=f"shadow:mock:{idx}",
                result_json={},
                confidence=0.0,
                missing_fields=["shadow_error"],
                is_success=False,
            )

        retry_intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Все еще хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_shadow_manual_2",
        )
        order, _ = process_intake_message(
            intake=retry_intake,
            llm_client=MockLLMClient(),
            order=order,
        )

        order.refresh_from_db()
        self.assertFalse(order.needs_manual_review)

    def test_side_effects_are_triggered_via_on_commit_for_confirmed_order(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу 2 кружки на Ленина 10 телефон 89161234567",
            customer=self.customer,
            idempotency_key="tg_on_commit_confirmed",
        )

        with patch("ai_parser.services.apply_confirmed_order_side_effects") as apply_effects_mock:
            with patch("ai_parser.services.sync_order_after_parsing") as sync_mock:
                with self.captureOnCommitCallbacks(execute=True):
                    order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())

        self.assertEqual(order.status, Order.Status.CONFIRMED)
        apply_effects_mock.assert_called_once()
        sync_mock.assert_called_once()

    def test_sync_is_not_scheduled_on_commit_for_needs_info_order(self):
        intake = IntakeMessage.objects.create(
            channel=IntakeMessage.Channel.TELEGRAM,
            raw_text="Хочу кружку на Ленина 10",
            customer=self.customer,
            idempotency_key="tg_on_commit_needs_info",
        )

        with patch("ai_parser.services.apply_confirmed_order_side_effects") as apply_effects_mock:
            with patch("ai_parser.services.sync_order_after_parsing") as sync_mock:
                with self.captureOnCommitCallbacks(execute=True):
                    order, _ = process_intake_message(intake=intake, llm_client=MockLLMClient())

        self.assertEqual(order.status, Order.Status.NEEDS_INFO)
        apply_effects_mock.assert_not_called()
        sync_mock.assert_not_called()
