from django.urls import path

from .views import (
    create_payment_link_view,
    export_orders_csv,
    invoice_view,
    mark_order_paid_view,
    order_detail_view,
    order_list_view,
    order_status_update_view,
    refresh_payment_status_view,
    stats_view,
    storefront_view,
)

urlpatterns = [
    path("storefront/", storefront_view, name="storefront"),
    path("dashboard/orders/", order_list_view, name="dashboard-orders"),
    path("dashboard/orders/<int:order_id>/", order_detail_view, name="dashboard-order-detail"),
    path(
        "dashboard/orders/<int:order_id>/status/",
        order_status_update_view,
        name="dashboard-order-status",
    ),
    path(
        "dashboard/orders/<int:order_id>/mark-paid/",
        mark_order_paid_view,
        name="dashboard-order-mark-paid",
    ),
    path("dashboard/stats/", stats_view, name="dashboard-stats"),
    path("dashboard/export/csv/", export_orders_csv, name="dashboard-export-csv"),
    path("dashboard/orders/<int:order_id>/invoice/", invoice_view, name="dashboard-invoice"),
    path(
        "dashboard/orders/<int:order_id>/payment-link/",
        create_payment_link_view,
        name="dashboard-payment-link",
    ),
    path(
        "dashboard/orders/<int:order_id>/payment-refresh/",
        refresh_payment_status_view,
        name="dashboard-payment-refresh",
    ),
]
