from __future__ import annotations

import json
import re
from typing import Any

from ai_parser.schemas import OrderExtract


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


def _quote_unquoted_json_keys(text: str) -> str:
    # Handle model outputs like {items: [...], customer: {...}}.
    return re.sub(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)", r'\1"\2"\3', text)


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        if digits:
            return int(digits)
        return None
    if isinstance(value, dict):
        for key in ("qty", "quantity", "new_quantity", "old_quantity", "count", "amount"):
            if key in value:
                parsed = _coerce_int(value.get(key))
                if parsed is not None:
                    return parsed
    return None


def _normalize_item_title(raw_title: Any) -> str:
    if raw_title is None:
        return ""
    title = str(raw_title).strip()
    if not title:
        return ""
    mapped = {
        "cup": "кружка",
        "mug": "кружка",
        "tshirt": "футболка",
        "t-shirt": "футболка",
        "tee": "футболка",
        "hoodie": "худи",
        "sweatshirt": "свитшот",
        "cap": "кепка",
    }
    return mapped.get(title.lower(), title)


def _pick_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_string_from_nested(
    data: dict[str, Any],
    key: str,
    *nested_keys: str,
) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for nested_key in nested_keys:
            nested_value = value.get(nested_key)
            if isinstance(nested_value, str) and nested_value.strip():
                return nested_value.strip()
    return None


def _coerce_items(raw_items: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    coerced_items: list[dict[str, Any]] = []
    for raw_item in raw_items:
        if isinstance(raw_item, str):
            title = _normalize_item_title(raw_item)
            if title:
                coerced_items.append({"title": title, "qty": 1})
            continue
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        if "title" not in item:
            for alias in (
                "name",
                "product_name",
                "product",
                "item_name",
                "item",
                "type",
                "kind",
            ):
                if alias in item:
                    candidate_title = _normalize_item_title(item.get(alias))
                    if candidate_title:
                        item["title"] = candidate_title
                        break
        elif isinstance(item.get("title"), str):
            item["title"] = _normalize_item_title(item.get("title"))

        if "qty" not in item:
            for alias in ("quantity", "count", "amount", "qty_value"):
                if alias in item:
                    item["qty"] = item.get(alias)
                    break

        parsed_qty = _coerce_int(item.get("qty"))
        if parsed_qty is not None:
            item["qty"] = parsed_qty
        elif item.get("title"):
            item["qty"] = 1

        if item.get("title"):
            coerced_items.append(item)
    return coerced_items


def _extract_chain_of_thought_fallback(chain: dict[str, Any]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}

    chain_items = chain.get("items")
    chain_qty = chain.get("quantity")
    if isinstance(chain_items, list):
        if isinstance(chain_qty, list) and len(chain_qty) == len(chain_items):
            items: list[dict[str, Any]] = []
            for raw_item, raw_qty in zip(chain_items, chain_qty):
                title = _normalize_item_title(raw_item)
                qty = _coerce_int(raw_qty) or 1
                if title:
                    items.append({"title": title, "qty": qty})
            if items:
                extracted["items"] = items
        else:
            items = _coerce_items(chain_items)
            if items:
                extracted["items"] = items

    quantity_obj = chain.get("quantity")
    if isinstance(quantity_obj, dict):
        title = _normalize_item_title(
            quantity_obj.get("item") or quantity_obj.get("type") or quantity_obj.get("product")
        )
        qty = _coerce_int(quantity_obj.get("new_quantity"))
        if qty is None:
            qty = _coerce_int(quantity_obj.get("old_quantity"))
        if qty is None:
            qty = _coerce_int(quantity_obj.get("quantity"))
        if title and qty is not None:
            extracted.setdefault("items", []).append({"title": title, "qty": qty})

    item_obj = chain.get("item")
    if isinstance(item_obj, dict):
        title = _normalize_item_title(item_obj.get("new_item") or item_obj.get("old_item"))
        if title:
            extracted.setdefault("items", []).append({"title": title, "qty": 1})

    address = _pick_string(chain, "address", "delivery_address")
    if address is None:
        address = _pick_string_from_nested(chain, "address", "new_address", "old_address")
    if address:
        extracted["delivery_address"] = address

    phone = _pick_string(chain, "phone", "contact", "contact_number", "delivery_contact")
    if phone is None:
        phone = _pick_string_from_nested(chain, "phone", "new_phone", "old_phone")
    if phone:
        extracted["contact_number"] = phone

    order_details = chain.get("order_details")
    if isinstance(order_details, dict):
        if "delivery_address" not in extracted:
            detail_address = _pick_string(order_details, "delivery_address", "address")
            if detail_address:
                extracted["delivery_address"] = detail_address
        if "contact_number" not in extracted:
            detail_phone = _pick_string(
                order_details,
                "delivery_contact",
                "contact_number",
                "phone",
            )
            if detail_phone:
                extracted["contact_number"] = detail_phone
        if "items" not in extracted:
            detail_qty = _coerce_int(order_details.get("quantity"))
            detail_item = _normalize_item_title(
                order_details.get("item")
                or order_details.get("product")
                or order_details.get("type")
            )
            if detail_qty is not None and detail_item:
                extracted["items"] = [{"title": detail_item, "qty": detail_qty}]

    return extracted


def _merge_canonical_aliases(normalized: dict[str, Any], alias_source: dict[str, Any]) -> None:
    if not isinstance(alias_source, dict):
        return

    if not normalized.get("items"):
        alias_items = alias_source.get("items")
        if not alias_items:
            for alias in ("skus", "products", "order_items"):
                if isinstance(alias_source.get(alias), list):
                    alias_items = alias_source.get(alias)
                    break
        coerced = _coerce_items(alias_items)
        if coerced:
            normalized["items"] = coerced
        else:
            qty = _coerce_int(
                alias_source.get("qty")
                or alias_source.get("quantity")
                or alias_source.get("count")
            )
            title = _normalize_item_title(
                alias_source.get("title")
                or alias_source.get("item")
                or alias_source.get("product")
                or alias_source.get("type")
            )
            if qty is not None and title:
                normalized["items"] = [{"title": title, "qty": qty}]

    if not isinstance(normalized.get("customer"), dict):
        normalized["customer"] = {}
    customer = normalized["customer"]
    if not isinstance(customer, dict):
        customer = {}
        normalized["customer"] = customer

    if not isinstance(normalized.get("delivery"), dict):
        normalized["delivery"] = {}
    delivery = normalized["delivery"]
    if not isinstance(delivery, dict):
        delivery = {}
        normalized["delivery"] = delivery

    if not customer.get("phone"):
        phone = _pick_string(
            alias_source,
            "phone",
            "contact_number",
            "delivery_contact",
            "contact",
        )
        if phone:
            customer["phone"] = phone

    if not customer.get("email"):
        email = _pick_string(alias_source, "email", "mail")
        if email:
            customer["email"] = email

    if not customer.get("name"):
        name = _pick_string(alias_source, "name", "customer_name")
        if name:
            customer["name"] = name

    if not delivery.get("address"):
        address = _pick_string(alias_source, "delivery_address", "address")
        if address:
            delivery["address"] = address

    if not delivery.get("city"):
        city = _pick_string(alias_source, "city", "delivery_city")
        if city:
            delivery["city"] = city

    if not isinstance(normalized.get("clarifying_questions"), list):
        if isinstance(normalized.get("clarifying_questions"), str):
            normalized["clarifying_questions"] = [normalized["clarifying_questions"]]
        else:
            normalized["clarifying_questions"] = []


def _normalize_order_extract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)

    # Some instruct models place structured payload inside chain_of_thought or order_extract.
    chain = normalized.get("chain_of_thought")
    if isinstance(chain, dict):
        _merge_canonical_aliases(normalized, _extract_chain_of_thought_fallback(chain))
        normalized["chain_of_thought"] = json.dumps(chain, ensure_ascii=False)
    elif isinstance(chain, list):
        normalized["chain_of_thought"] = "\n".join(
            str(part) for part in chain if part is not None
        )
    elif chain is None:
        normalized["chain_of_thought"] = ""
    elif not isinstance(chain, str):
        normalized["chain_of_thought"] = str(chain)

    order_extract = normalized.get("order_extract")
    if isinstance(order_extract, dict):
        _merge_canonical_aliases(normalized, order_extract)

    _merge_canonical_aliases(normalized, normalized)

    if normalized.get("missing_fields") is None:
        normalized["missing_fields"] = []
    elif isinstance(normalized.get("missing_fields"), str):
        raw_missing = normalized["missing_fields"].strip()
        normalized["missing_fields"] = [raw_missing] if raw_missing else []
    elif not isinstance(normalized.get("missing_fields"), list):
        normalized["missing_fields"] = []

    if normalized.get("clarifying_questions") is None:
        normalized["clarifying_questions"] = []
    elif isinstance(normalized.get("clarifying_questions"), str):
        raw_question = normalized["clarifying_questions"].strip()
        normalized["clarifying_questions"] = [raw_question] if raw_question else []
    elif not isinstance(normalized.get("clarifying_questions"), list):
        normalized["clarifying_questions"] = []

    confidence = normalized.get("confidence")
    if isinstance(confidence, str):
        try:
            normalized["confidence"] = float(confidence.strip())
        except Exception:
            normalized["confidence"] = 0.0
    elif confidence is None:
        normalized["confidence"] = 0.0

    if "items" in normalized:
        normalized["items"] = _coerce_items(normalized.get("items"))

    return normalized


def _parse_structured_response(raw_text: str | dict[str, Any]) -> OrderExtract:
    if isinstance(raw_text, dict):
        return OrderExtract.model_validate(_normalize_order_extract_payload(raw_text))

    payload = _extract_json_payload(raw_text)
    try:
        return OrderExtract.model_validate_json(payload)
    except Exception:
        patched = _quote_unquoted_json_keys(payload)
        data, _ = json.JSONDecoder().raw_decode(patched)
        return OrderExtract.model_validate(_normalize_order_extract_payload(data))
