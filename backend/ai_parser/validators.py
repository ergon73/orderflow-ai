from __future__ import annotations

from copy import deepcopy

import phonenumbers

from .schemas import OrderExtract


def normalize_phone(raw: str | None, default_region: str = "RU") -> str | None:
    if not raw:
        return None
    try:
        parsed = phonenumbers.parse(raw, default_region)
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return None


def apply_post_validation(extract: OrderExtract) -> OrderExtract:
    validated = OrderExtract.model_validate(deepcopy(extract.model_dump()))
    # Recompute from canonical slots only. Ignore noisy model-specific labels.
    missing: set[str] = set()

    if not validated.items:
        missing.add("items")

    address = (validated.delivery.address or "").strip()
    if len(address) < 5:
        validated.delivery.address = None
        missing.add("delivery.address")
    else:
        missing.discard("delivery.address")

    normalized_phone = normalize_phone(validated.customer.phone)
    if normalized_phone:
        validated.customer.phone = normalized_phone
        missing.discard("customer.phone")
    else:
        validated.customer.phone = None
        missing.add("customer.phone")

    email = (validated.customer.email or "").strip()
    if email and "@" not in email:
        validated.customer.email = None
        missing.add("customer.email")

    validated.missing_fields = sorted(missing)
    if validated.missing_fields and not validated.clarifying_questions:
        validated.clarifying_questions = [
            "Пожалуйста, уточните недостающие данные для оформления заказа."
        ]
    return validated
