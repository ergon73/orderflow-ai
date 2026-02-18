from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Customer,
    ExtractionAttempt,
    IntakeMessage,
    Order,
    OrderItem,
    OrderStatusHistory,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "phone", "email", "telegram_id", "created_at")
    search_fields = ("name", "phone", "email", "telegram_id")
    list_filter = ("created_at",)


@admin.register(IntakeMessage)
class IntakeMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "customer", "idempotency_key", "created_at")
    search_fields = ("idempotency_key", "raw_text", "customer__name", "customer__phone")
    list_filter = ("channel", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "colored_status",
        "channel",
        "customer",
        "is_paid",
        "needs_manual_review",
        "created_at",
    )
    list_filter = ("status", "channel", "is_paid", "needs_manual_review", "created_at")
    search_fields = (
        "id",
        "customer__name",
        "customer__phone",
        "delivery_address",
        "bpium_record_id",
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="status")
    def colored_status(self, obj: Order):
        color = {
            Order.Status.NEW: "#6c757d",
            Order.Status.NEEDS_INFO: "#fd7e14",
            Order.Status.CONFIRMED: "#0d6efd",
            Order.Status.IN_PROGRESS: "#0dcaf0",
            Order.Status.SHIPPED: "#198754",
            Order.Status.DELIVERED: "#146c43",
            Order.Status.CANCELLED: "#dc3545",
            Order.Status.RETURNED: "#6f42c1",
        }.get(obj.status, "#6c757d")
        return format_html(
            '<span style="font-weight:600;color:{};">{}</span>',
            color,
            obj.get_status_display(),
        )


@admin.register(ExtractionAttempt)
class ExtractionAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "intake",
        "order",
        "model_name",
        "confidence",
        "is_success",
        "created_at",
    )
    list_filter = ("model_name", "is_success", "created_at")
    search_fields = ("intake__idempotency_key", "error_message")


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "title", "quantity", "price")
    search_fields = ("title", "order__id")


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "old_status", "new_status", "changed_by", "changed_at")
    list_filter = ("old_status", "new_status", "changed_at")
    search_fields = ("order__id", "changed_by", "comment")
