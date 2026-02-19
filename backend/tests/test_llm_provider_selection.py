import os
from unittest.mock import patch

from django.test import SimpleTestCase

from ai_parser.client import MockLLMClient
from ai_parser.services import get_default_llm_client


class LLMProviderSelectionTests(SimpleTestCase):
    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "",
            "OPENAI_API_KEY": "",
        },
        clear=False,
    )
    def test_default_without_openai_key_uses_mock(self):
        client = get_default_llm_client()
        self.assertIsInstance(client, MockLLMClient)

    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "unknown-provider",
            "OPENAI_API_KEY": "",
        },
        clear=False,
    )
    def test_unknown_provider_falls_back_to_mock(self):
        client = get_default_llm_client()
        self.assertIsInstance(client, MockLLMClient)

    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test",
            "LLM_MODEL": "gpt-4o-mini",
        },
        clear=False,
    )
    @patch("ai_parser.services.InstructorOpenAIClient")
    def test_openai_provider_uses_instructor_client(self, client_cls):
        sentinel = object()
        client_cls.return_value = sentinel

        client = get_default_llm_client()

        self.assertIs(client, sentinel)
        client_cls.assert_called_once_with(
            model_name="gpt-4o-mini",
            api_key="sk-test",
            base_url=None,
            require_api_key=True,
        )

    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "vllm",
            "VLLM_BASE_URL": "http://127.0.0.1:8000/v1",
            "VLLM_API_KEY": "EMPTY",
            "VLLM_MODEL": "Qwen/Qwen2.5-7B-Instruct",
        },
        clear=False,
    )
    @patch("ai_parser.services.InstructorOpenAIClient")
    def test_vllm_provider_uses_openai_compatible_client(self, client_cls):
        sentinel = object()
        client_cls.return_value = sentinel

        client = get_default_llm_client()

        self.assertIs(client, sentinel)
        client_cls.assert_called_once_with(
            model_name="Qwen/Qwen2.5-7B-Instruct",
            api_key="EMPTY",
            base_url="http://127.0.0.1:8000/v1",
        )

    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "yandexgpt",
        },
        clear=False,
    )
    @patch("ai_parser.services.MockLLMClient")
    @patch("ai_parser.services.YandexGPTClient")
    def test_provider_init_error_falls_back_to_mock(self, yandex_cls, mock_cls):
        yandex_cls.side_effect = ValueError("missing yandex env")
        sentinel = object()
        mock_cls.return_value = sentinel

        client = get_default_llm_client()

        self.assertIs(client, sentinel)
        yandex_cls.assert_called_once()
        mock_cls.assert_called_once()
