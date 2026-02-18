from __future__ import annotations

import json
import os
from decimal import Decimal

from orders.models import Order

DEFAULT_TARIFFS = {
    "москва": "350.00",
    "санкт-петербург": "450.00",
    "default": "500.00",
}


def load_tariffs() -> dict[str, str]:
    raw = os.getenv("DELIVERY_TARIFFS_JSON", "")
    if not raw:
        return DEFAULT_TARIFFS
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            normalized = {str(k).lower(): str(v) for k, v in data.items()}
            return {**DEFAULT_TARIFFS, **normalized}
    except json.JSONDecodeError:
        pass
    return DEFAULT_TARIFFS


def calculate_delivery_cost(city: str | None) -> Decimal:
    tariffs = load_tariffs()
    key = (city or "").strip().lower()
    raw_cost = tariffs.get(key, tariffs["default"])
    return Decimal(str(raw_cost))


def apply_delivery_cost(order: Order) -> Order:
    cost = calculate_delivery_cost(order.delivery_city)
    if order.delivery_cost != cost:
        order.delivery_cost = cost
        order.save(update_fields=["delivery_cost", "updated_at"])
    return order

