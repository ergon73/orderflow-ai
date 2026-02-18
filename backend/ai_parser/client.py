from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod

import instructor
from openai import OpenAI

from .prompts import (
    SLOT_FILLING_SYSTEM_PROMPT,
    SLOT_FILLING_USER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from .schemas import OrderExtract, OrderItem


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
    ) -> None:
        self.model_name = model_name
        self.max_retries = max_retries
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is required for InstructorOpenAIClient")
        self._client = instructor.from_openai(OpenAI(api_key=key))

    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        if current_extraction is None:
            system_prompt = SYSTEM_PROMPT
            user_prompt = text
        else:
            system_prompt = SLOT_FILLING_SYSTEM_PROMPT
            user_prompt = SLOT_FILLING_USER_PROMPT_TEMPLATE.format(
                current_extraction_json=current_extraction.model_dump_json(
                    ensure_ascii=False
                ),
                new_message=text,
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

