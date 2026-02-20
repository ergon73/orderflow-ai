from __future__ import annotations

from integrations.apiship import apiship_auto_create_on_confirmed, create_shipment_for_order_safe
from integrations.delivery import apply_delivery_cost
from integrations.sync import sync_order_to_bpium_safe
from orders.models import Order


def apply_confirmed_order_side_effects(order: Order) -> None:
    apply_delivery_cost(order)
    if apiship_auto_create_on_confirmed():
        create_shipment_for_order_safe(order)


def sync_order_after_parsing(order: Order) -> None:
    sync_order_to_bpium_safe(order)
