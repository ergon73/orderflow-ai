from __future__ import annotations

from django.core.management.base import BaseCommand

from integrations.apiship import sync_shipping_status_safe
from orders.models import Order


class Command(BaseCommand):
    help = "Sync shipping statuses from ApiShip for orders linked to apiship provider."

    def add_arguments(self, parser):
        parser.add_argument("--order-id", type=int, default=0, help="Sync a single order by id")
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max number of orders to sync in batch mode",
        )
        parser.add_argument(
            "--no-status-transition",
            action="store_true",
            help="Only update shipping fields, do not map to Order.Status",
        )
        parser.add_argument(
            "--include-terminal",
            action="store_true",
            help="Include delivered/cancelled/returned orders in batch",
        )

    def handle(self, *args, **options):
        order_id = options["order_id"]
        limit = max(1, options["limit"])
        update_order_status = not options["no_status_transition"]
        include_terminal = options["include_terminal"]

        if order_id:
            queryset = Order.objects.filter(id=order_id)
        else:
            queryset = Order.objects.filter(
                shipping_provider="apiship",
                shipping_external_id__isnull=False,
            ).exclude(shipping_external_id="")
            if not include_terminal:
                queryset = queryset.exclude(
                    status__in=[
                        Order.Status.DELIVERED,
                        Order.Status.CANCELLED,
                        Order.Status.RETURNED,
                    ]
                )
            queryset = queryset.order_by("-updated_at")[:limit]

        total = queryset.count()
        success = 0
        failed = 0
        self.stdout.write(f"Syncing shipping statuses for {total} order(s)")

        for order in queryset:
            ok = sync_shipping_status_safe(order, update_order_status=update_order_status)
            if ok:
                success += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"order #{order.id}: synced ({order.shipping_status_raw or 'no-status'})"
                    )
                )
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"order #{order.id}: skipped/failed"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. success={success}, failed={failed}, total={total}"
            )
        )

