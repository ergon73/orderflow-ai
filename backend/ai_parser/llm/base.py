from __future__ import annotations

from abc import ABC, abstractmethod

from ai_parser.prompts import (
    SLOT_FILLING_SYSTEM_PROMPT,
    SLOT_FILLING_USER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
)
from ai_parser.schemas import OrderExtract


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


class LLMClient(ABC):
    model_name: str

    @abstractmethod
    def parse(
        self, text: str, current_extraction: OrderExtract | None = None
    ) -> OrderExtract:
        raise NotImplementedError
