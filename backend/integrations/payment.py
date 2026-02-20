from __future__ import annotations

import os
import uuid
from decimal import Decimal

import requests
from django.utils import timezone

from integrations.apiship import apiship_auto_create_on_paid, create_shipment_for_order_safe
from orders.models import Order


class YooKassaError(Exception):
    pass


def _credentials() -> tuple[str, str]:
    shop_id = os.getenv("YOOKASSA_SHOP_ID", "")
    secret = os.getenv("YOOKASSA_SECRET", "")
    if not shop_id or not secret:
        raise YooKassaError("YOOKASSA_SHOP_ID and YOOKASSA_SECRET are required")
    return shop_id, secret


def _resolve_amount(order: Order) -> Decimal:
    if order.total_amount and order.total_amount > 0:
        return order.total_amount
    if order.delivery_cost and order.delivery_cost > 0:
        return order.delivery_cost
    return Decimal("1.00")


def create_payment(order: Order, return_url: str) -> dict:
    shop_id, secret = _credentials()
    amount = _resolve_amount(order)
    payload = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": f"OrderFlow order #{order.id}",
        "metadata": {"order_id": str(order.id)},
    }
    response = requests.post(
        "https://api.yookassa.ru/v3/payments",
        auth=(shop_id, secret),
        headers={"Idempotence-Key": str(uuid.uuid4())},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "payment_id": data.get("id"),
        "status": data.get("status"),
        "confirmation_url": (data.get("confirmation") or {}).get("confirmation_url", ""),
        "raw": data,
    }


def get_payment(payment_id: str) -> dict:
    shop_id, secret = _credentials()
    response = requests.get(
        f"https://api.yookassa.ru/v3/payments/{payment_id}",
        auth=(shop_id, secret),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def mark_order_paid_if_succeeded(order: Order, payment_data: dict) -> Order:
    status = payment_data.get("status")
    if status == "succeeded" and not order.is_paid:
        order.is_paid = True
        order.paid_at = timezone.now()
        order.save(update_fields=["is_paid", "paid_at", "updated_at"])
        if apiship_auto_create_on_paid():
            create_shipment_for_order_safe(order)
    return order
