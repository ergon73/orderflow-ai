from django.urls import path

from .api_views import OrderDetailAPIView, OrderListAPIView, OrderStatusUpdateAPIView

urlpatterns = [
    path("orders/", OrderListAPIView.as_view(), name="api-orders-list"),
    path("orders/<int:pk>/", OrderDetailAPIView.as_view(), name="api-orders-detail"),
    path(
        "orders/<int:pk>/status/",
        OrderStatusUpdateAPIView.as_view(),
        name="api-orders-status",
    ),
]

