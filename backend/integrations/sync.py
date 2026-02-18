from __future__ import annotations

import logging

from orders.models import Order

from .bpium import BpiumClient

logger = logging.getLogger(__name__)


SYNC_STATUSES = {
    Order.Status.CONFIRMED,
    Order.Status.IN_PROGRESS,
    Order.Status.SHIPPED,
    Order.Status.DELIVERED,
    Order.Status.CANCELLED,
    Order.Status.RETURNED,
}


def build_bpium_payload(order: Order) -> dict:
    items_summary = ", ".join(
        [f"{item.quantity}x {item.title}" for item in order.items.all()]
    )
    return {
        "external_id": str(order.id),
        "order_id": str(order.id),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "channel": order.channel,
        "status": order.status or None,
        "customer_name": order.customer.name or None,
        "phone": order.customer.phone or None,
        "items_summary": items_summary or None,
        "delivery_address": order.delivery_address or None,
        "delivery_cost": float(order.delivery_cost) if order.delivery_cost is not None else None,
        "total_amount": float(order.total_amount) if order.total_amount is not None else None,
        "is_paid": order.is_paid,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "track_number": order.track_number or None,
    }


def sync_order_to_bpium_safe(order: Order) -> bool:
    if order.status not in SYNC_STATUSES:
        return False

    client = BpiumClient()
    if not client.is_configured:
        return False

    payload = build_bpium_payload(order)
    try:
        if order.bpium_record_id:
            record_id = client.update_record(order.bpium_record_id, payload)
        else:
            existing_record_id = client.find_record_by_external_id(str(order.id))
            if existing_record_id:
                record_id = client.update_record(existing_record_id, payload)
            else:
                record_id = client.create_record(payload)
        if record_id and record_id != order.bpium_record_id:
            order.bpium_record_id = record_id
            order.save(update_fields=["bpium_record_id", "updated_at"])
        return True
    except Exception as exc:
        logger.warning(
            "bpium_sync_failed order_id=%s status=%s error=%s",
            order.id,
            order.status,
            exc,
        )
        return False
