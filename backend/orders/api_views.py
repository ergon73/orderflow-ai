from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import Order
from .serializers import OrderSerializer, OrderStatusUpdateSerializer
from .services import change_order_status


class APIUserThrottle(UserRateThrottle):
    scope = "api_user"


class APIOrderWriteThrottle(UserRateThrottle):
    scope = "api_order_write"


class OrderListAPIView(generics.ListAPIView):
    queryset = Order.objects.select_related("customer").prefetch_related("items").all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIUserThrottle]


class OrderDetailAPIView(generics.RetrieveAPIView):
    queryset = Order.objects.select_related("customer").prefetch_related("items").all()
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIUserThrottle]


class OrderStatusUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [APIOrderWriteThrottle]

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
