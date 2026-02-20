from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from django.utils import timezone

from config.env_utils import env_bool, env_float, env_int
from config.logging_utils import sanitize_exception_for_log
from orders.models import Order
from orders.services import change_order_status

logger = logging.getLogger(__name__)


class ApiShipError(Exception):
    pass


RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def _compact_dict(raw: dict[str, Any]) -> dict[str, Any]:
    compacted: dict[str, Any] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            compacted[key] = stripped
            continue
        if isinstance(value, dict):
            nested = _compact_dict(value)
            if nested:
                compacted[key] = nested
            continue
        compacted[key] = value
    return compacted


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if decimal < 0:
        return None
    return decimal


def _positive_int(value: int, default: int) -> int:
    return value if value > 0 else default


def _positive_float(value: float, default: float) -> float:
    return value if value > 0 else default


def _default_item_cost() -> Decimal:
    parsed = _as_decimal(os.getenv("APISHIP_DEFAULT_ITEM_COST", "1.00"))
    if parsed is None or parsed <= 0:
        return Decimal("1.00")
    return parsed.quantize(Decimal("0.01"))


def _default_places_payload() -> list[dict[str, Any]]:
    weight_grams = _default_weight_grams()
    length_cm, width_cm, height_cm = _default_dimensions_cm()
    return [
        {
            "weight": weight_grams,
            "length": length_cm,
            "width": width_cm,
            "height": height_cm,
        }
    ]


def _default_dimensions_cm() -> tuple[int, int, int]:
    length = _positive_int(env_int("APISHIP_PLACE_LENGTH_CM", 10), 10)
    width = _positive_int(env_int("APISHIP_PLACE_WIDTH_CM", 10), 10)
    height = _positive_int(env_int("APISHIP_PLACE_HEIGHT_CM", 10), 10)
    return length, width, height


def _default_weight_grams() -> int:
    # Project env stores kg for readability; ApiShip expects grams.
    weight_kg = _positive_float(env_float("APISHIP_DEFAULT_WEIGHT_KG", 1.0), 1.0)
    return max(1, int(round(weight_kg * 1000)))


def _extract_token(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("accessToken", "access_token", "token", "apiKey", "api_key"):
        token = data.get(key)
        if isinstance(token, str) and token.strip():
            return token.strip()
    return ""


def _extract_status_info(data: Any) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "", ""
    status = data.get("status")
    if isinstance(status, dict):
        key = str(status.get("key") or "").strip()
        name = str(status.get("name") or "").strip()
        if key:
            return key, name
        if name:
            return name, name
    status_key = str(data.get("statusKey") or "").strip()
    status_name = str(data.get("statusName") or "").strip()
    if status_key:
        return status_key, status_name
    if status_name:
        return status_name, status_name
    if isinstance(status, str):
        normalized = status.strip()
        return normalized, normalized
    return "", ""


def _extract_tracking(data: Any) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "", ""

    provider_number = str(data.get("providerNumber") or "").strip()
    barcode = str(data.get("barcode") or "").strip()
    track_number = provider_number or barcode
    tracking_url = str(data.get("trackingUrl") or data.get("trackUrl") or "").strip()

    return track_number, tracking_url


def _extract_shipping_external_id(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("id", "orderId", "order_id", "clientNumber", "client_number"):
        value = data.get(key)
        if value is None:
            continue
        candidate = str(value).strip()
        if candidate:
            return candidate
    return ""


def map_apiship_status_to_order_status(status_key: str, status_name: str = "") -> str | None:
    normalized = f"{status_key} {status_name}".lower()
    if not normalized.strip():
        return None

    if any(token in normalized for token in ("cancel", "отмен", "canceled", "cancelled")):
        return Order.Status.CANCELLED
    if any(token in normalized for token in ("return", "возврат")):
        return Order.Status.RETURNED
    if any(token in normalized for token in ("deliver", "вруч", "доставлен", "completed")):
        return Order.Status.DELIVERED
    if any(
        token in normalized
        for token in ("transit", "on_way", "route", "courier", "shipped", "отгруж", "в пути")
    ):
        return Order.Status.SHIPPED
    if any(
        token in normalized
        for token in ("accept", "processing", "created", "new", "pickup", "upload", "готов", "принят")
    ):
        return Order.Status.IN_PROGRESS
    return None


@dataclass
class ApiShipClient:
    base_url: str = field(
        default_factory=lambda: (os.getenv("APISHIP_BASE_URL", "http://api.dev.apiship.ru/v1").rstrip("/"))
    )
    token: str = field(default_factory=lambda: (os.getenv("APISHIP_TOKEN", "")).strip())
    login: str = field(default_factory=lambda: (os.getenv("APISHIP_LOGIN", "")).strip())
    password: str = field(default_factory=lambda: (os.getenv("APISHIP_PASSWORD", "")).strip())
    auth_path: str = field(default_factory=lambda: (os.getenv("APISHIP_AUTH_PATH", "/users/login")).strip())
    calculator_path: str = field(
        default_factory=lambda: (os.getenv("APISHIP_CALCULATOR_PATH", "/calculator")).strip()
    )
    orders_path: str = field(default_factory=lambda: (os.getenv("APISHIP_ORDERS_PATH", "/orders/sync")).strip())
    order_status_path: str = field(
        default_factory=lambda: (os.getenv("APISHIP_ORDER_STATUS_PATH", "/orders/status")).strip()
    )
    timeout: int = field(default_factory=lambda: env_int("APISHIP_TIMEOUT", 20))
    max_retries: int = field(default_factory=lambda: env_int("APISHIP_MAX_RETRIES", 2))
    retry_backoff_base: float = field(
        default_factory=lambda: env_float("APISHIP_RETRY_BACKOFF_BASE", 0.5)
    )
    retry_backoff_max: float = field(
        default_factory=lambda: env_float("APISHIP_RETRY_BACKOFF_MAX", 4.0)
    )

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self._auth_header = (os.getenv("APISHIP_AUTH_HEADER", "Authorization")).strip() or "Authorization"
        self._auth_prefix = os.getenv("APISHIP_AUTH_PREFIX", "")
        self._access_token = self.token

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and (self._access_token or (self.login and self.password)))

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized_path}"

    def _auth_headers(self) -> dict[str, str]:
        token = self._access_token or self._login()
        if not token:
            raise ApiShipError("ApiShip token is missing")
        value = f"{self._auth_prefix}{token}" if self._auth_prefix else token
        return {self._auth_header: value}

    def _login(self) -> str:
        if self._access_token:
            return self._access_token
        if not (self.login and self.password):
            raise ApiShipError("APISHIP_TOKEN or APISHIP_LOGIN/APISHIP_PASSWORD is required")

        response = self._request(
            "POST",
            self.auth_path,
            json={"login": self.login, "password": self.password},
            with_auth=False,
        )
        token = _extract_token(response)
        if not token:
            raise ApiShipError("ApiShip login did not return access token")
        self._access_token = token
        return token

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                delay = float(retry_after.strip())
            except Exception:
                delay = 0.0
        else:
            delay = self.retry_backoff_base * (2 ** max(0, attempt - 1))
        if self.retry_backoff_max > 0:
            delay = min(delay, self.retry_backoff_max)
        if delay > 0:
            time.sleep(delay)

    def _request(
        self,
        method: str,
        path: str,
        *,
        with_auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        if with_auth:
            headers.update(self._auth_headers())
        kwargs["headers"] = headers

        attempts = 0
        while True:
            try:
                response = self.session.request(
                    method=method,
                    url=self._url(path),
                    timeout=self.timeout,
                    **kwargs,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempts >= self.max_retries:
                    raise ApiShipError(f"ApiShip request failed: {exc}") from exc
                attempts += 1
                self._sleep(attempts, None)
                continue

            if response.status_code in RETRYABLE_STATUS_CODES and attempts < self.max_retries:
                attempts += 1
                self._sleep(attempts, response.headers.get("Retry-After"))
                response.close()
                continue

            if response.status_code == 401 and with_auth and self.login and self.password:
                # Token expired -> re-login once.
                self._access_token = ""
                if attempts < self.max_retries:
                    attempts += 1
                    self._sleep(attempts, None)
                    continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                body = response.text[:1000]
                raise ApiShipError(
                    f"ApiShip HTTP {response.status_code}: {body}"
                ) from exc

            if not response.content:
                return {}
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}

    def calculate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", self.calculator_path, json=payload)

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", self.orders_path, json=payload)

    def get_order_status(self, client_number: str) -> dict[str, Any]:
        return self._request(
            "GET",
            self.order_status_path,
            params={"clientNumber": client_number},
        )


def apiship_enabled() -> bool:
    return env_bool("APISHIP_ENABLED", False)


def apiship_auto_create_on_confirmed() -> bool:
    return env_bool("APISHIP_AUTO_CREATE_ON_CONFIRMED", False)


def apiship_auto_create_on_paid() -> bool:
    return env_bool("APISHIP_AUTO_CREATE_ON_PAID", False)


def _shipment_type(raw: str, *, default_value: int) -> int:
    normalized = (raw or "").strip().lower()
    if not normalized:
        return default_value
    if normalized.isdigit():
        value = int(normalized)
        return value if value in (1, 2) else default_value
    alias_map = {
        "courier": 1,
        "door": 1,
        "pickup": 2,
        "point": 2,
        "pvz": 2,
        "locker": 2,
        "postomat": 2,
    }
    return alias_map.get(normalized, default_value)


def _pickup_type() -> int:
    return _shipment_type(os.getenv("APISHIP_PICKUP_TYPE", "courier"), default_value=1)


def _delivery_type() -> int:
    return _shipment_type(os.getenv("APISHIP_DELIVERY_TYPE", "courier"), default_value=1)


def _client_number_for_order(order: Order) -> str:
    prefix = (os.getenv("APISHIP_CLIENT_NUMBER_PREFIX", "orderflow") or "orderflow").strip()
    return f"{prefix}-{order.id}"


def _env_tariff_id() -> int | None:
    raw = (os.getenv("APISHIP_TARIFF_ID", "") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _build_sender_address() -> str:
    from_address = (os.getenv("APISHIP_FROM_ADDRESS", "") or "").strip()
    from_city = (os.getenv("APISHIP_FROM_CITY", "") or "").strip()
    if from_address:
        return from_address
    if from_city:
        return from_city
    return ""


def _build_sender_payload() -> dict[str, Any]:
    return _compact_dict(
        {
            "countryCode": (os.getenv("APISHIP_FROM_COUNTRY_CODE", "RU") or "RU").strip(),
            "addressString": _build_sender_address() or None,
            "contactName": (os.getenv("APISHIP_SENDER_NAME", "OrderFlow Store") or "OrderFlow Store").strip(),
            "phone": (os.getenv("APISHIP_SENDER_PHONE", "+79990000000") or "+79990000000").strip(),
            "email": (os.getenv("APISHIP_SENDER_EMAIL", "") or "").strip() or None,
        }
    )


def _build_recipient_payload(order: Order) -> dict[str, Any]:
    return _compact_dict(
        {
            "countryCode": (os.getenv("APISHIP_RECIPIENT_COUNTRY_CODE", "RU") or "RU").strip(),
            "addressString": (order.delivery_address or "").strip() or None,
            "contactName": (order.customer.name or "").strip() or "Получатель",
            "phone": (order.customer.phone or "").strip() or "+79990000000",
            "email": (order.customer.email or "").strip() or None,
        }
    )


def _build_places_payload(order: Order) -> tuple[list[dict[str, Any]], Decimal]:
    default_item_cost = _default_item_cost()
    db_items = list(order.items.all())
    if not db_items:
        db_items = []

    total_units = sum(max(1, int(item.quantity or 1)) for item in db_items) or 1
    total_weight = _default_weight_grams()
    unit_weight = max(1, total_weight // total_units)
    length_cm, width_cm, height_cm = _default_dimensions_cm()

    single_item_total = _as_decimal(order.total_amount) if len(db_items) == 1 else None
    assessed_total = Decimal("0.00")
    place_items: list[dict[str, Any]] = []

    if not db_items:
        db_items_payload = [
            {
                "description": "Товар",
                "quantity": 1,
                "assessedCost": float(default_item_cost),
                "cost": 0.0,
                "weight": unit_weight,
                "length": length_cm,
                "width": width_cm,
                "height": height_cm,
            }
        ]
        assessed_total = default_item_cost
    else:
        db_items_payload = []
        for item in db_items:
            quantity = max(1, int(item.quantity or 1))
            assessed_cost = _as_decimal(item.price)
            if assessed_cost is None or assessed_cost <= 0:
                if single_item_total is not None and single_item_total > 0:
                    assessed_cost = (single_item_total / Decimal(quantity)).quantize(Decimal("0.01"))
                else:
                    assessed_cost = default_item_cost
            assessed_total += assessed_cost * Decimal(quantity)
            db_items_payload.append(
                {
                    "description": item.title or "Товар",
                    "quantity": quantity,
                    "assessedCost": float(assessed_cost.quantize(Decimal("0.01"))),
                    "cost": 0.0,
                    "weight": unit_weight,
                    "length": length_cm,
                    "width": width_cm,
                    "height": height_cm,
                }
            )

    place_items.extend(db_items_payload)
    places = [
        {
            "weight": unit_weight * sum(max(1, int(item.get("quantity", 1) or 1)) for item in place_items),
            "length": length_cm,
            "width": width_cm,
            "height": height_cm,
            "items": place_items,
        }
    ]
    return places, assessed_total.quantize(Decimal("0.01"))


def _build_calculator_payload(order: Order) -> dict[str, Any]:
    weight_grams = _default_weight_grams()
    length_cm, width_cm, height_cm = _default_dimensions_cm()
    payload = {
        "providerKey": os.getenv("APISHIP_PROVIDER_KEY", "").strip() or None,
        "pickupType": _pickup_type(),
        "deliveryType": _delivery_type(),
        "from": {
            "city": os.getenv("APISHIP_FROM_CITY", "").strip() or None,
            "addressString": os.getenv("APISHIP_FROM_ADDRESS", "").strip() or None,
        },
        "to": {
            "city": (order.delivery_city or "").strip() or None,
            "addressString": (order.delivery_address or "").strip() or None,
        },
        "weight": weight_grams,
        "length": length_cm,
        "width": width_cm,
        "height": height_cm,
        "places": _default_places_payload(),
        "assessedCost": float(order.total_amount) if order.total_amount else None,
    }
    return _compact_dict(payload)


def _build_create_order_payload(
    order: Order,
    *,
    client_number: str,
    provider_key: str,
    tariff_id: int,
    pickup_type: int,
    delivery_type: int,
) -> dict[str, Any]:
    if not provider_key:
        return {}
    places, assessed_total = _build_places_payload(order)
    length_cm, width_cm, height_cm = _default_dimensions_cm()
    total_weight = sum(int(place.get("weight") or 0) for place in places) or _default_weight_grams()
    payload = {
        "order": {
            "clientNumber": client_number,
            "providerKey": provider_key,
            "pickupType": pickup_type,
            "deliveryType": delivery_type,
            "tariffId": tariff_id,
            "weight": total_weight,
            "length": length_cm,
            "width": width_cm,
            "height": height_cm,
            "description": (order.comment or "").strip() or None,
        },
        "cost": {
            "assessedCost": float(assessed_total),
            "codCost": 0.0,
        },
        "sender": _build_sender_payload(),
        "recipient": _build_recipient_payload(order),
        "places": places,
    }
    return _compact_dict(payload)


def _extract_tariff_candidates(response: dict[str, Any]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []

    nested_blocks = [
        response.get("deliveryToDoor"),
        response.get("deliveryToPoint"),
        response.get("deliveryToPostomat"),
        response.get("deliveryToLocker"),
    ]
    for block_list in nested_blocks:
        if not isinstance(block_list, list):
            continue
        for block in block_list:
            if not isinstance(block, dict):
                continue
            provider_key = str(block.get("providerKey") or "").strip()
            tariffs = block.get("tariffs")
            if not isinstance(tariffs, list):
                continue
            for tariff in tariffs:
                if not isinstance(tariff, dict):
                    continue
                tariff_id = tariff.get("tariffId")
                try:
                    parsed_tariff_id = int(tariff_id)
                except Exception:
                    continue
                if provider_key:
                    candidates.append((provider_key, parsed_tariff_id))

    offers = response.get("offers")
    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            provider_key = str(offer.get("providerKey") or "").strip()
            tariff_id = offer.get("tariffId")
            try:
                parsed_tariff_id = int(tariff_id)
            except Exception:
                continue
            if provider_key:
                candidates.append((provider_key, parsed_tariff_id))

    deduped: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def calculate_delivery_cost_apiship(order: Order) -> Decimal | None:
    if not apiship_enabled():
        return None
    client = ApiShipClient()
    if not client.is_configured:
        return None

    payload = _build_calculator_payload(order)
    if not payload.get("from") or not payload.get("to"):
        return None

    try:
        response = client.calculate(payload)
    except Exception as exc:
        logger.warning(
            "apiship_calculator_failed order_id=%s error=%s",
            order.id,
            sanitize_exception_for_log(exc),
        )
        return None

    candidates: list[Any] = [
        response.get("cost"),
        response.get("deliveryCost"),
        response.get("total"),
        response.get("price"),
        response.get("amount"),
    ]

    for block_key in ("deliveryToDoor", "deliveryToPoint", "deliveryToPostomat", "deliveryToLocker"):
        blocks = response.get(block_key)
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            tariffs = block.get("tariffs")
            if not isinstance(tariffs, list):
                continue
            for tariff in tariffs:
                if not isinstance(tariff, dict):
                    continue
                candidates.extend(
                    [
                        tariff.get("deliveryCost"),
                        tariff.get("cost"),
                        tariff.get("total"),
                        tariff.get("price"),
                    ]
                )

    offers = response.get("offers")
    if isinstance(offers, list) and offers:
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            candidates.extend(
                [
                    offer.get("cost"),
                    offer.get("deliveryCost"),
                    offer.get("total"),
                    offer.get("price"),
                ]
            )

    for candidate in candidates:
        parsed = _as_decimal(candidate)
        if parsed is not None:
            return parsed.quantize(Decimal("0.01"))
    return None


def create_shipment_for_order_safe(order: Order) -> bool:
    if not apiship_enabled():
        return False
    client = ApiShipClient()
    if not client.is_configured:
        return False

    if order.shipping_provider == "apiship" and order.shipping_external_id:
        return True

    client_number = _client_number_for_order(order)
    pickup_type = _pickup_type()
    delivery_type = _delivery_type()
    forced_provider = (os.getenv("APISHIP_PROVIDER_KEY", "") or "").strip()
    forced_tariff = _env_tariff_id()
    tariff_candidates: list[tuple[str, int]] = []

    if forced_provider and forced_tariff is not None:
        tariff_candidates.append((forced_provider, forced_tariff))
    else:
        calc_payload = _build_calculator_payload(order)
        if calc_payload.get("from") and calc_payload.get("to"):
            try:
                calc_response = client.calculate(calc_payload)
                tariff_candidates = _extract_tariff_candidates(calc_response)
            except Exception as exc:
                logger.warning(
                    "apiship_calculator_before_create_failed order_id=%s error=%s",
                    order.id,
                    sanitize_exception_for_log(exc),
                )
        if forced_provider:
            tariff_candidates = [candidate for candidate in tariff_candidates if candidate[0] == forced_provider]
        if forced_tariff is not None:
            tariff_candidates = [candidate for candidate in tariff_candidates if candidate[1] == forced_tariff]

    if not tariff_candidates:
        logger.warning(
            "apiship_create_order_skipped_no_tariff order_id=%s provider=%s tariff=%s",
            order.id,
            forced_provider or "<auto>",
            forced_tariff if forced_tariff is not None else "<auto>",
        )
        return False

    response: dict[str, Any] = {}
    last_error: Exception | None = None
    created = False
    for provider_key, tariff_id in tariff_candidates:
        payload = _build_create_order_payload(
            order,
            client_number=client_number,
            provider_key=provider_key,
            tariff_id=tariff_id,
            pickup_type=pickup_type,
            delivery_type=delivery_type,
        )
        if not payload:
            continue
        try:
            response = client.create_order(payload)
            created = True
            break
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            if "already exists" in message or "уже существует" in message:
                order.shipping_provider = "apiship"
                order.shipping_external_id = client_number
                order.shipping_synced_at = timezone.now()
                order.save(update_fields=["shipping_provider", "shipping_external_id", "shipping_synced_at", "updated_at"])
                sync_shipping_status_safe(order, update_order_status=False)
                return True
            continue

    if not created:
        if last_error is not None:
            logger.warning(
                "apiship_create_order_failed order_id=%s error=%s",
                order.id,
                sanitize_exception_for_log(last_error),
            )
        return False

    provider_order_id = _extract_shipping_external_id(response)
    shipping_external_id = client_number
    track_number, tracking_url = _extract_tracking(response)
    status_key, status_name = _extract_status_info(response)

    order.shipping_provider = "apiship"
    order.shipping_external_id = shipping_external_id
    if track_number and not order.track_number:
        order.track_number = track_number
    if tracking_url:
        order.tracking_url = tracking_url
    if status_key or status_name:
        order.shipping_status_raw = status_key or status_name
    order.shipping_synced_at = timezone.now()
    order.save(
        update_fields=[
            "shipping_provider",
            "shipping_external_id",
            "track_number",
            "tracking_url",
            "shipping_status_raw",
            "shipping_synced_at",
            "updated_at",
        ]
    )

    if not track_number:
        sync_shipping_status_safe(order, update_order_status=False)

    if provider_order_id and provider_order_id != client_number:
        logger.info(
            "apiship_create_order_mapping order_id=%s client_number=%s provider_order_id=%s",
            order.id,
            client_number,
            provider_order_id,
        )

    return True


def sync_shipping_status_safe(order: Order, *, update_order_status: bool = True) -> bool:
    if order.shipping_provider != "apiship":
        return False
    client = ApiShipClient()
    if not client.is_configured:
        return False

    first_client_number = (order.shipping_external_id or "").strip()
    fallback_client_number = _client_number_for_order(order)
    client_numbers: list[str] = []
    if first_client_number:
        client_numbers.append(first_client_number)
    if fallback_client_number and fallback_client_number not in client_numbers:
        client_numbers.append(fallback_client_number)
    if not client_numbers:
        return False

    response: dict[str, Any] | None = None
    last_error: Exception | None = None
    for client_number in client_numbers:
        try:
            response = client.get_order_status(client_number)
            break
        except Exception as exc:
            last_error = exc
            continue

    if response is None:
        logger.warning(
            "apiship_status_sync_failed order_id=%s error=%s",
            order.id,
            sanitize_exception_for_log(last_error),
        )
        return False

    source = response
    data_items = response.get("data")
    if isinstance(data_items, list) and data_items:
        if isinstance(data_items[0], dict):
            source = data_items[0]

    track_number, tracking_url = _extract_tracking(source)
    status_key, status_name = _extract_status_info(source)

    if track_number:
        order.track_number = track_number
    if tracking_url:
        order.tracking_url = tracking_url
    if status_key or status_name:
        order.shipping_status_raw = status_key or status_name
    order.shipping_synced_at = timezone.now()
    order.save(
        update_fields=[
            "track_number",
            "tracking_url",
            "shipping_status_raw",
            "shipping_synced_at",
            "updated_at",
        ]
    )

    if update_order_status:
        mapped_status = map_apiship_status_to_order_status(status_key, status_name)
        if mapped_status and mapped_status != order.status:
            try:
                change_order_status(
                    order=order,
                    new_status=mapped_status,
                    actor="apiship_sync",
                    comment=f"apiship status: {status_key or status_name}",
                )
            except Exception as exc:
                logger.warning(
                    "apiship_status_transition_skipped order_id=%s from=%s to=%s error=%s",
                    order.id,
                    order.status,
                    mapped_status,
                    sanitize_exception_for_log(exc),
                )

    return True
