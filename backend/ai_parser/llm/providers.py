from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

import instructor
import requests
from openai import OpenAI

from ai_parser.llm.base import LLMClient, _build_prompt_pair, _force_json_reply
from ai_parser.llm.normalization import _parse_structured_response
from ai_parser.llm.retry import _post_with_retry, _resolve_retry_settings
from ai_parser.schemas import OrderExtract, OrderItem
from config.env_utils import env_float, env_int


class InstructorOpenAIClient(LLMClient):
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        max_retries: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        require_api_key: bool = False,
    ) -> None:
        self.model_name = model_name
        default_retries = env_int("OPENAI_MAX_RETRIES", env_int("LLM_HTTP_MAX_RETRIES", 3))
        self.max_retries = max(0, max_retries if max_retries is not None else default_retries)
        self.timeout = timeout if timeout is not None else env_float("OPENAI_TIMEOUT", 30.0)
        self._base_url = ""
        key = api_key or os.getenv("OPENAI_API_KEY", "")
        if require_api_key and not key:
            raise ValueError("OPENAI_API_KEY is required for InstructorOpenAIClient")
        if not key:
            key = "EMPTY"

        resolved_base_url = (base_url or os.getenv("OPENAI_BASE_URL", "")).strip()
        client_kwargs: dict[str, Any] = {
            "api_key": key,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }
        if resolved_base_url:
            self._base_url = resolved_base_url.rstrip("/")
            client_kwargs["base_url"] = self._base_url

        self._raw_client = OpenAI(**client_kwargs)
        self._client = instructor.from_openai(self._raw_client)

    @staticmethod
    def _looks_like_tool_parser_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = (
            "tool-call-parser",
            "tool_choice",
            "requires --tool-call-parser",
            "does not support tool",
            "function call",
        )
        return any(marker in msg for marker in markers)

    def _raw_json_parse(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> OrderExtract:
        response = self._raw_client.chat.completions.create(
            model=self.model_name,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _force_json_reply(user_prompt)},
            ],
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise ValueError("LLM returned no choices")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text_part = part.get("text")
                    if isinstance(text_part, str):
                        parts.append(text_part)
            content = "\n".join(parts)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM returned empty content")
        return _parse_structured_response(content)

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        system_prompt, user_prompt = _build_prompt_pair(
            text=text,
            current_extraction=current_extraction,
        )
        try:
            return self._client.chat.completions.create(
                model=self.model_name,
                response_model=OrderExtract,
                max_retries=self.max_retries,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            # Some vLLM setups are launched without tool-calling parser.
            # For OpenAI-compatible custom endpoints we can fallback to plain JSON output.
            if self._base_url and self._looks_like_tool_parser_error(exc):
                return self._raw_json_parse(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
            raise


class YandexGPTClient(LLMClient):
    def __init__(
        self,
        model_name: str = "yandexgpt-lite",
        model_uri: str | None = None,
        api_key: str | None = None,
        folder_id: str | None = None,
        endpoint: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        timeout: float = 30.0,
        max_retries: int | None = None,
        retry_backoff_base: float | None = None,
        retry_backoff_max: float | None = None,
        retry_status_codes: set[int] | None = None,
    ) -> None:
        self.model_name = model_name
        self.api_key = (api_key or os.getenv("YANDEXGPT_API_KEY", "")).strip()
        self.folder_id = (folder_id or os.getenv("YANDEXGPT_FOLDER_ID", "")).strip()
        self.model_uri = (model_uri or os.getenv("YANDEXGPT_MODEL_URI", "")).strip()
        self.endpoint = endpoint
        self.timeout = timeout
        (
            default_max_retries,
            default_backoff_base,
            default_backoff_max,
            default_retry_status_codes,
        ) = _resolve_retry_settings("YANDEXGPT", default_retries=2)
        self.max_retries = max(0, max_retries if max_retries is not None else default_max_retries)
        self.retry_backoff_base = (
            retry_backoff_base if retry_backoff_base is not None else default_backoff_base
        )
        self.retry_backoff_max = (
            retry_backoff_max if retry_backoff_max is not None else default_backoff_max
        )
        self.retry_status_codes = set(retry_status_codes or default_retry_status_codes)

        if not self.api_key:
            raise ValueError("YANDEXGPT_API_KEY is required for YandexGPTClient")
        if not self.model_uri:
            if not self.folder_id:
                raise ValueError(
                    "YANDEXGPT_FOLDER_ID or YANDEXGPT_MODEL_URI is required for YandexGPTClient"
                )
            self.model_uri = f"gpt://{self.folder_id}/{self.model_name}/latest"

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        system_prompt, user_prompt = _build_prompt_pair(
            text=text,
            current_extraction=current_extraction,
        )
        payload = {
            "modelUri": self.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0,
                "maxTokens": "2500",
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": _force_json_reply(user_prompt)},
            ],
        }
        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.folder_id:
            headers["x-folder-id"] = self.folder_id

        response = _post_with_retry(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=self.timeout,
            max_retries=self.max_retries,
            backoff_base=self.retry_backoff_base,
            backoff_max=self.retry_backoff_max,
            retry_status_codes=self.retry_status_codes,
        )
        response.raise_for_status()
        data = response.json()

        alternatives = ((data.get("result") or {}).get("alternatives")) or []
        if not alternatives:
            raise ValueError("YandexGPT returned no alternatives")
        answer = ((alternatives[0].get("message") or {}).get("text")) or ""
        return _parse_structured_response(answer)


class GigaChatClient(LLMClient):
    def __init__(
        self,
        model_name: str = "GigaChat-2-Max",
        auth_key: str | None = None,
        scope: str = "GIGACHAT_API_PERS",
        auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        api_url: str = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        verify_ssl: bool | str = True,
        timeout: float = 30.0,
        max_retries: int | None = None,
        retry_backoff_base: float | None = None,
        retry_backoff_max: float | None = None,
        retry_status_codes: set[int] | None = None,
    ) -> None:
        self.model_name = model_name
        self.auth_key = (auth_key or os.getenv("GIGACHAT_AUTH_KEY", "")).strip()
        self.scope = scope
        self.auth_url = auth_url
        self.api_url = api_url
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        (
            default_max_retries,
            default_backoff_base,
            default_backoff_max,
            default_retry_status_codes,
        ) = _resolve_retry_settings("GIGACHAT", default_retries=2)
        self.max_retries = max(0, max_retries if max_retries is not None else default_max_retries)
        self.retry_backoff_base = (
            retry_backoff_base if retry_backoff_base is not None else default_backoff_base
        )
        self.retry_backoff_max = (
            retry_backoff_max if retry_backoff_max is not None else default_backoff_max
        )
        self.retry_status_codes = set(retry_status_codes or default_retry_status_codes)
        self._access_token = ""  # nosec B105
        self._access_token_expires_at = 0.0

        if not self.auth_key:
            raise ValueError("GIGACHAT_AUTH_KEY is required for GigaChatClient")

    @staticmethod
    def _extract_function_arguments(data: dict[str, Any]) -> str | dict[str, Any] | None:
        choices = data.get("choices") or []
        if not choices:
            return None

        message = choices[0].get("message") or {}
        function_call = message.get("function_call") or {}
        arguments = function_call.get("arguments")
        if isinstance(arguments, (str, dict)):
            return arguments

        tool_calls = message.get("tool_calls") or []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, (str, dict)):
                return arguments
        return None

    @staticmethod
    def _order_extract_function_spec() -> dict[str, Any]:
        return {
            "name": "extract_order",
            "description": (
                "Извлечь структуру заказа из текста клиента строго по JSON-схеме OrderExtract. "
                "Заполнять только найденные значения."
            ),
            "parameters": OrderExtract.model_json_schema(),
        }

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expires_at:
            return self._access_token

        response = _post_with_retry(
            self.auth_url,
            headers={
                "Authorization": f"Basic {self.auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"scope": self.scope},
            timeout=self.timeout,
            verify=self.verify_ssl,
            max_retries=self.max_retries,
            backoff_base=self.retry_backoff_base,
            backoff_max=self.retry_backoff_max,
            retry_status_codes=self.retry_status_codes,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token", "")
        if not token:
            raise ValueError("GigaChat auth failed: access_token is missing")

        expires_at = data.get("expires_at")
        if expires_at:
            # API returns ms timestamp, keep a safety window.
            self._access_token_expires_at = max(
                time.time() + 60,
                (float(expires_at) / 1000.0) - 60.0,
            )
        else:
            self._access_token_expires_at = time.time() + 1800
        self._access_token = token
        return token

    def _chat_completion(
        self,
        token: str,
        system_prompt: str,
        user_prompt: str,
        *,
        use_functions: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _force_json_reply(user_prompt)},
            ],
        }
        if use_functions:
            payload["functions"] = [self._order_extract_function_spec()]

        response = _post_with_retry(
            self.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=self.timeout,
            verify=self.verify_ssl,
            max_retries=self.max_retries,
            backoff_base=self.retry_backoff_base,
            backoff_max=self.retry_backoff_max,
            retry_status_codes=self.retry_status_codes,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_message_content(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts)
        return ""

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        system_prompt, user_prompt = _build_prompt_pair(
            text=text,
            current_extraction=current_extraction,
        )
        token = self._get_access_token()

        try:
            data = self._chat_completion(
                token=token,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                use_functions=True,
            )
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in {400, 404, 422}:
                raise
            data = self._chat_completion(
                token=token,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                use_functions=False,
            )

        arguments = self._extract_function_arguments(data)
        if arguments is not None:
            return _parse_structured_response(arguments)

        content = self._extract_message_content(data)
        if not content:
            raise ValueError("GigaChat returned empty content")
        return _parse_structured_response(content)


class MockLLMClient(LLMClient):
    def __init__(self, responses: list[OrderExtract] | None = None) -> None:
        self.model_name = "mock-llm"
        self._responses = list(responses or [])

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        if self._responses:
            return self._responses.pop(0)

        result = current_extraction.model_copy(deep=True) if current_extraction else OrderExtract()
        lowered = text.lower()

        parsed_items: list[OrderItem] = []
        qty_match = re.search(r"\b(\d{1,3})\b", lowered)
        qty = int(qty_match.group(1)) if qty_match else 1

        if "круж" in lowered:
            parsed_items.append(OrderItem(title="кружка", qty=qty))
        if "футбол" in lowered:
            parsed_items.append(OrderItem(title="футболка", qty=qty))

        if parsed_items and (not result.items or "исправ" in lowered or "замен" in lowered):
            result.items = parsed_items

        address_match = re.search(r"\bна\s+([^,.]+(?:\s+\d+)?)", text, flags=re.IGNORECASE)
        if address_match:
            result.delivery.address = address_match.group(1).strip()

        phone_match = re.search(r"(\+?\d[\d\-\(\)\s]{9,}\d)", text)
        if phone_match:
            result.customer.phone = phone_match.group(1).strip()

        missing = set(result.missing_fields)
        if not result.items:
            missing.add("items")
        if not (result.delivery.address and result.delivery.address.strip()):
            missing.add("delivery.address")
        if not (result.customer.phone and result.customer.phone.strip()):
            missing.add("customer.phone")

        result.missing_fields = sorted(missing)
        result.confidence = 0.85 if result.items else 0.3
        if result.missing_fields:
            result.clarifying_questions = ["Уточните недостающие поля заказа."]
        else:
            result.clarifying_questions = []
        if not result.chain_of_thought:
            result.chain_of_thought = "Черновой разбор сообщения завершен."

        return result
