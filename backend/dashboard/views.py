import csv
import json
import re

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ai_parser.services import process_intake_message
from bot.notifications import send_order_status_notification
from integrations.apiship import apiship_auto_create_on_confirmed, create_shipment_for_order_safe
from integrations.payment import YooKassaError, create_payment, get_payment, mark_order_paid_if_succeeded
from integrations.sync import sync_order_to_bpium_safe
from orders.models import Order
from orders.services import (
    change_order_status,
    create_web_intake,
    get_or_create_web_customer,
)
from orders.state_machine import VALID_TRANSITIONS

from .forms import StorefrontOrderForm
from .rate_limit import storefront_post_rate_limit


def _build_raw_text(form_data: dict) -> str:
    free_text = (form_data.get("free_text") or "").strip()
    selected_product = (form_data.get("selected_product") or "").strip()
    quantity = form_data.get("quantity") or 1

    if free_text:
        return free_text
    return f"Хочу {quantity} x {selected_product}"


@storefront_post_rate_limit
def storefront_view(request):
    products = [
        {"title": "Кружка", "price": "590"},
        {"title": "Футболка", "price": "1990"},
        {"title": "Худи", "price": "3990"},
        {"title": "Термос", "price": "2490"},
    ]

    if request.method == "POST":
        form = StorefrontOrderForm(request.POST)
        if form.is_valid():
            raw_text = _build_raw_text(form.cleaned_data)
            customer = get_or_create_web_customer(
                name=form.cleaned_data.get("name", ""),
                phone=form.cleaned_data.get("phone", ""),
                email=form.cleaned_data.get("email", ""),
            )
            intake = create_web_intake(
                customer=customer,
                text=raw_text,
                metadata={"source": "storefront"},
            )
            order, attempt = process_intake_message(intake=intake)
            return render(
                request,
                "dashboard/storefront_success.html",
                {"order": order, "attempt": attempt},
            )
    else:
        form = StorefrontOrderForm()

    return render(
        request,
        "dashboard/storefront.html",
        {"form": form, "products": products},
    )


@login_required
def order_list_view(request):
    queryset = (
        Order.objects.select_related("customer")
        .prefetch_related("items", "history")
        .order_by("-created_at")
    )

    status = request.GET.get("status", "").strip()
    channel = request.GET.get("channel", "").strip()
    search = request.GET.get("search", "").strip()

    if status:
        queryset = queryset.filter(status=status)
    if channel:
        queryset = queryset.filter(channel=channel)
    if search:
        queryset = queryset.filter(
            Q(customer__name__icontains=search)
            | Q(customer__phone__icontains=search)
            | Q(items__title__icontains=search)
            | Q(id__icontains=search)
        ).distinct()

    context = {
        "orders": queryset[:200],
        "status": status,
        "channel": channel,
        "search": search,
        "status_choices": Order.Status.choices,
        "channel_choices": [
            ("telegram", "Telegram"),
            ("web", "Web"),
            ("email", "Email"),
        ],
    }
    return render(request, "dashboard/orders_list.html", context)


@login_required
def order_detail_view(request, order_id: int):
    order = get_object_or_404(
        Order.objects.select_related("customer").prefetch_related("items", "history"),
        id=order_id,
    )
    next_statuses = VALID_TRANSITIONS.get(order.status, [])
    return render(
        request,
        "dashboard/order_detail.html",
        {"order": order, "next_statuses": next_statuses},
    )


@require_POST
@login_required
def order_status_update_view(request, order_id: int):
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get("status", "").strip()
    actor = f"dashboard:{request.user.username}" if request.user.is_authenticated else "dashboard"
    comment = request.POST.get("comment", "").strip()

    try:
        order = change_order_status(
            order=order,
            new_status=new_status,
            actor=actor,
            comment=comment,
        )
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return render(
                request,
                "dashboard/partials/status_badge.html",
                {"order": order, "error": str(exc)},
                status=400,
            )
        messages.error(request, str(exc))
        return redirect("dashboard-order-detail", order_id=order.id)

    send_order_status_notification(order)
    sync_order_to_bpium_safe(order)
    if order.status == Order.Status.CONFIRMED and apiship_auto_create_on_confirmed():
        create_shipment_for_order_safe(order)

    if request.headers.get("HX-Request"):
        return render(request, "dashboard/partials/status_badge.html", {"order": order})
    messages.success(request, f"Статус заказа #{order.id} обновлён.")
    return redirect("dashboard-order-detail", order_id=order.id)


@require_POST
@login_required
def mark_order_paid_view(request, order_id: int):
    order = get_object_or_404(Order, id=order_id)
    if not order.is_paid:
        order.is_paid = True
        order.paid_at = timezone.now()
        order.save(update_fields=["is_paid", "paid_at", "updated_at"])
    sync_order_to_bpium_safe(order)
    return redirect("dashboard-order-detail", order_id=order.id)


@login_required
def stats_view(request):
    status_stats = list(
        Order.objects.values("status").annotate(total=Count("id")).order_by("status")
    )
    channel_stats = list(
        Order.objects.values("channel").annotate(total=Count("id")).order_by("channel")
    )
    day_stats = list(
        Order.objects.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
        .order_by("day")
    )
    return render(
        request,
        "dashboard/stats.html",
        {
            "status_stats": json.dumps(status_stats, default=str),
            "channel_stats": json.dumps(channel_stats, default=str),
            "day_stats": json.dumps(day_stats, default=str),
        },
    )


@login_required
def export_orders_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = "attachment; filename=orders_export.csv"
    writer = csv.writer(response)
    writer.writerow(
        [
            "order_id",
            "created_at",
            "channel",
            "status",
            "customer_name",
            "phone",
            "delivery_address",
            "is_paid",
            "paid_at",
            "delivery_cost",
            "total_amount",
            "track_number",
            "shipping_provider",
            "shipping_external_id",
            "tracking_url",
            "shipping_status_raw",
            "shipping_synced_at",
            "bpium_record_id",
        ]
    )

    orders = Order.objects.select_related("customer").order_by("-created_at")
    for order in orders:
        writer.writerow(
            [
                order.id,
                order.created_at.isoformat(),
                order.channel,
                order.status,
                order.customer.name,
                order.customer.phone,
                order.delivery_address,
                order.is_paid,
                order.paid_at.isoformat() if order.paid_at else "",
                order.delivery_cost or "",
                order.total_amount or "",
                order.track_number,
                order.shipping_provider,
                order.shipping_external_id,
                order.tracking_url,
                order.shipping_status_raw,
                order.shipping_synced_at.isoformat() if order.shipping_synced_at else "",
                order.bpium_record_id,
            ]
        )
    return response


@login_required
def invoice_view(request, order_id: int):
    order = get_object_or_404(Order.objects.select_related("customer"), id=order_id)
    context = {"order": order}
    html = render(request, "dashboard/invoice.html", context)

    # WeasyPrint is optional in this stage. If unavailable, return HTML fallback.
    try:
        from weasyprint import HTML

        pdf_content = HTML(string=html.content.decode("utf-8")).write_pdf()
        response = HttpResponse(pdf_content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="invoice_{order.id}.pdf"'
        return response
    except Exception:
        return html


def _extract_payment_id(comment: str) -> str | None:
    match = re.search(r"\[payment_id:([^\]]+)\]", comment or "")
    return match.group(1) if match else None


@require_POST
@login_required
def create_payment_link_view(request, order_id: int):
    order = get_object_or_404(Order, id=order_id)
    try:
        payment = create_payment(
            order=order,
            return_url=request.build_absolute_uri(f"/dashboard/orders/{order.id}/"),
        )
        payment_id = payment.get("payment_id")
        confirmation_url = payment.get("confirmation_url")
        if payment_id and f"[payment_id:{payment_id}]" not in order.comment:
            order.comment = (order.comment + f" [payment_id:{payment_id}]").strip()
            order.save(update_fields=["comment", "updated_at"])
        messages.success(
            request,
            f"Ссылка оплаты: {confirmation_url or 'не получена'}",
        )
    except YooKassaError as exc:
        messages.error(request, f"YooKassa не настроена: {exc}")
    except Exception as exc:
        messages.error(request, f"Не удалось создать платёж: {exc}")
    return redirect("dashboard-order-detail", order_id=order.id)


@require_POST
@login_required
def refresh_payment_status_view(request, order_id: int):
    order = get_object_or_404(Order, id=order_id)
    payment_id = request.POST.get("payment_id", "").strip() or _extract_payment_id(order.comment)
    if not payment_id:
        messages.error(request, "Payment ID не найден. Создайте платёжную ссылку заново.")
        return redirect("dashboard-order-detail", order_id=order.id)

    try:
        payment_data = get_payment(payment_id)
        mark_order_paid_if_succeeded(order, payment_data)
        sync_order_to_bpium_safe(order)
        messages.success(request, f"Статус платежа: {payment_data.get('status')}")
    except YooKassaError as exc:
        messages.error(request, f"YooKassa не настроена: {exc}")
    except Exception as exc:
        messages.error(request, f"Ошибка проверки платежа: {exc}")
    return redirect("dashboard-order-detail", order_id=order.id)
