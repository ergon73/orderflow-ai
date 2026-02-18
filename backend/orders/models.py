from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    telegram_id = models.BigIntegerField(null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or self.phone or f"customer-{self.pk}"


class IntakeMessage(models.Model):
    class Channel(models.TextChoices):
        TELEGRAM = "telegram", "Telegram"
        WEB = "web", "Web"
        EMAIL = "email", "Email"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    raw_text = models.TextField()
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="intake_messages"
    )
    idempotency_key = models.CharField(max_length=128, unique=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["channel", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel}:{self.idempotency_key}"


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        NEEDS_INFO = "needs_info", "Needs info"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PROGRESS = "in_progress", "In progress"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"
        RETURNED = "returned", "Returned"

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="orders")
    intake = models.ForeignKey(IntakeMessage, on_delete=models.CASCADE, related_name="orders")
    channel = models.CharField(max_length=20, choices=IntakeMessage.Channel.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NEW, db_index=True
    )
    delivery_address = models.TextField(blank=True)
    delivery_city = models.CharField(max_length=120, blank=True)
    comment = models.TextField(blank=True)
    delivery_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    track_number = models.CharField(max_length=64, blank=True)
    needs_manual_review = models.BooleanField(default=False)
    bpium_record_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["customer", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"order-{self.pk}:{self.status}"


class ExtractionAttempt(models.Model):
    intake = models.ForeignKey(
        IntakeMessage, on_delete=models.CASCADE, related_name="extraction_attempts"
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="extraction_attempts",
    )
    model_name = models.CharField(max_length=64, default="gpt-4o-mini")
    result_json = models.JSONField(default=dict)
    confidence = models.FloatField(default=0.0)
    missing_fields = models.JSONField(default=list, blank=True)
    is_success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intake", "created_at"]),
            models.Index(fields=["order", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"attempt-{self.pk}:{self.model_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField(default=1)
    size = models.CharField(max_length=32, blank=True)
    color = models.CharField(max_length=32, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.title} x{self.quantity}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20)
    comment = models.TextField(blank=True)
    changed_by = models.CharField(max_length=100)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.order_id}:{self.old_status}->{self.new_status}"
