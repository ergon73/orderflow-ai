from __future__ import annotations

import os
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import instructor
import requests
from openai import OpenAI

from .prompts import (
    SLOT_FILLING_SYSTEM_PROMPT,
    SLOT_FILLING_USER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from .schemas import OrderExtract, OrderItem


def _build_prompt_pair(
    text: str,
    current_extraction: OrderExtract | None = None,
) -> tuple[str, str]:
    if current_extraction is None:
        return SYSTEM_PROMPT, text

    user_prompt = SLOT_FILLING_USER_PROMPT_TEMPLATE.format(
        current_extraction_json=current_extraction.model_dump_json(ensure_ascii=False),
        new_message=text,
    )
    return SLOT_FILLING_SYSTEM_PROMPT, user_prompt


def _force_json_reply(prompt: str) -> str:
    return (
        f"{prompt}\n\n"
        "Ответь строго одним JSON-объектом по схеме OrderExtract. "
        "Без markdown, без пояснений, без дополнительных полей."
    )


def _extract_json_payload(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("LLM returned empty response")

    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse_structured_response(raw_text: str) -> OrderExtract:
    payload = _extract_json_payload(raw_text)
    return OrderExtract.model_validate_json(payload)


class LLMClient(ABC):
    model_name: str

    @abstractmethod
    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        raise NotImplementedError


class InstructorOpenAIClient(LLMClient):
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        max_retries: int = 3,
        api_key: str | None = None,
        base_url: str | None = None,
        require_api_key: bool = False,
    ) -> None:
        self.model_name = model_name
        self.max_retries = max_retries
        key = api_key or os.getenv("OPENAI_API_KEY", "")
        if require_api_key and not key:
            raise ValueError("OPENAI_API_KEY is required for InstructorOpenAIClient")
        if not key:
            key = "EMPTY"

        resolved_base_url = (base_url or os.getenv("OPENAI_BASE_URL", "")).strip()
        client_kwargs: dict[str, Any] = {"api_key": key}
        if resolved_base_url:
            client_kwargs["base_url"] = resolved_base_url.rstrip("/")

        self._client = instructor.from_openai(OpenAI(**client_kwargs))

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        system_prompt, user_prompt = _build_prompt_pair(
            text=text,
            current_extraction=current_extraction,
        )

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


class YandexGPTClient(LLMClient):
    def __init__(
        self,
        model_name: str = "yandexgpt-lite",
        model_uri: str | None = None,
        api_key: str | None = None,
        folder_id: str | None = None,
        endpoint: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        timeout: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.api_key = (api_key or os.getenv("YANDEXGPT_API_KEY", "")).strip()
        self.folder_id = (folder_id or os.getenv("YANDEXGPT_FOLDER_ID", "")).strip()
        self.model_uri = (model_uri or os.getenv("YANDEXGPT_MODEL_URI", "")).strip()
        self.endpoint = endpoint
        self.timeout = timeout

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

        response = requests.post(
            self.endpoint,
            json=payload,
            headers=headers,
            timeout=self.timeout,
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
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.model_name = model_name
        self.auth_key = (auth_key or os.getenv("GIGACHAT_AUTH_KEY", "")).strip()
        self.scope = scope
        self.auth_url = auth_url
        self.api_url = api_url
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self._access_token = ""
        self._access_token_expires_at = 0.0

        if not self.auth_key:
            raise ValueError("GIGACHAT_AUTH_KEY is required for GigaChatClient")

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expires_at:
            return self._access_token

        response = requests.post(
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

        response = requests.post(
            self.api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": self.model_name,
                "temperature": 0,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _force_json_reply(user_prompt)},
                ],
            },
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        response.raise_for_status()
        data = response.json()
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
