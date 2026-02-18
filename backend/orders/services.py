from __future__ import annotations

import uuid

from django.db import transaction

from .models import Customer, IntakeMessage, Order, OrderStatusHistory
from .state_machine import assert_valid_transition


@transaction.atomic
def get_or_create_telegram_customer(
    telegram_id: int, display_name: str | None = None
) -> Customer:
    defaults = {"name": (display_name or "").strip()}
    customer, created = Customer.objects.get_or_create(
        telegram_id=telegram_id, defaults=defaults
    )
    if not created and display_name and not customer.name:
        customer.name = display_name
        customer.save(update_fields=["name", "updated_at"])
    return customer


@transaction.atomic
def create_telegram_intake(
    customer: Customer, text: str, chat_id: int, message_id: int
) -> tuple[IntakeMessage, bool]:
    idempotency_key = f"tg_{chat_id}_{message_id}"
    intake, created = IntakeMessage.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "channel": IntakeMessage.Channel.TELEGRAM,
            "raw_text": text,
            "customer": customer,
            "metadata": {"chat_id": chat_id, "message_id": message_id},
        },
    )
    return intake, created


@transaction.atomic
def get_or_create_web_customer(
    name: str = "", phone: str = "", email: str = ""
) -> Customer:
    phone = phone.strip()
    email = email.strip().lower()
    customer = None

    if email:
        customer = Customer.objects.filter(email__iexact=email).first()
    if customer is None and phone:
        customer = Customer.objects.filter(phone=phone).first()

    if customer is None:
        return Customer.objects.create(name=name.strip(), phone=phone, email=email)

    updated = False
    if name.strip() and not customer.name:
        customer.name = name.strip()
        updated = True
    if phone and not customer.phone:
        customer.phone = phone
        updated = True
    if email and not customer.email:
        customer.email = email
        updated = True
    if updated:
        customer.save(update_fields=["name", "phone", "email", "updated_at"])
    return customer


def create_web_intake(
    customer: Customer, text: str, metadata: dict | None = None
) -> IntakeMessage:
    return IntakeMessage.objects.create(
        channel=IntakeMessage.Channel.WEB,
        raw_text=text,
        customer=customer,
        idempotency_key=f"web_{uuid.uuid4()}",
        metadata=metadata or {},
    )


@transaction.atomic
def get_or_create_email_customer(from_email: str, display_name: str | None = None) -> Customer:
    normalized_email = (from_email or "").strip().lower()
    defaults = {
        "name": (display_name or "").strip(),
        "email": normalized_email,
    }
    customer, created = Customer.objects.get_or_create(
        email=normalized_email,
        defaults=defaults,
    )
    if not created and display_name and not customer.name:
        customer.name = display_name.strip()
        customer.save(update_fields=["name", "updated_at"])
    return customer


@transaction.atomic
def create_email_intake(
    customer: Customer,
    text: str,
    mailbox: str,
    uidvalidity: str,
    uid: str,
    metadata: dict | None = None,
) -> tuple[IntakeMessage, bool]:
    key = f"email_{mailbox}_{uidvalidity}_{uid}"
    intake, created = IntakeMessage.objects.get_or_create(
        idempotency_key=key,
        defaults={
            "channel": IntakeMessage.Channel.EMAIL,
            "raw_text": text,
            "customer": customer,
            "metadata": metadata or {},
        },
    )
    return intake, created


def get_active_needs_info_order(customer: Customer) -> Order | None:
    return (
        Order.objects.filter(
            customer=customer,
            status=Order.Status.NEEDS_INFO,
            needs_manual_review=False,
        )
        .order_by("-created_at")
        .first()
    )


@transaction.atomic
def change_order_status(
    order: Order, new_status: str, actor: str, comment: str = ""
) -> Order:
    old_status = order.status
    assert_valid_transition(old_status, new_status)
    if old_status == new_status:
        return order

    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        comment=comment,
    )
    return order


@transaction.atomic
def request_order_edit(order: Order, actor: str, comment: str = "") -> Order:
    old_status = order.status
    if old_status == Order.Status.NEEDS_INFO:
        return order

    order.status = Order.Status.NEEDS_INFO
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=Order.Status.NEEDS_INFO,
        changed_by=actor,
        comment=comment or "client requested correction",
    )
    return order
