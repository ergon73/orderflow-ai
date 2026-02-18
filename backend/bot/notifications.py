from __future__ import annotations

import logging
import os

import requests

from orders.models import Order

logger = logging.getLogger(__name__)


def send_order_status_notification(order: Order) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = order.customer.telegram_id
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = (
        f"Обновление по заказу #{order.id}\n"
        f"Статус: {order.get_status_display()}\n"
        f"Комментарий: {order.comment or '-'}"
    )
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning(
            "failed_to_send_telegram_status_notification order_id=%s error=%s",
            order.id,
            exc,
        )
        return False

