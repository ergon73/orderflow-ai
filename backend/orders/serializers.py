from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("id", "title", "quantity", "size", "color", "price")


class OrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "channel",
            "status",
            "customer_name",
            "customer_phone",
            "delivery_address",
            "delivery_city",
            "delivery_cost",
            "total_amount",
            "is_paid",
            "paid_at",
            "track_number",
            "needs_manual_review",
            "bpium_record_id",
            "created_at",
            "updated_at",
            "items",
        )


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.Status.choices)
    comment = serializers.CharField(required=False, allow_blank=True)

