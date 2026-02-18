from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Order
from .serializers import OrderSerializer, OrderStatusUpdateSerializer
from .services import change_order_status


class OrderListAPIView(generics.ListAPIView):
    queryset = Order.objects.select_related("customer").prefetch_related("items").all()
    serializer_class = OrderSerializer


class OrderDetailAPIView(generics.RetrieveAPIView):
    queryset = Order.objects.select_related("customer").prefetch_related("items").all()
    serializer_class = OrderSerializer


class OrderStatusUpdateAPIView(APIView):
    def patch(self, request, pk: int):
        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = get_object_or_404(Order, pk=pk)
        updated = change_order_status(
            order=order,
            new_status=serializer.validated_data["status"],
            actor="api",
            comment=serializer.validated_data.get("comment", ""),
        )
        return Response(OrderSerializer(updated).data, status=status.HTTP_200_OK)
