from __future__ import annotations

import logging
import os

from django.db import transaction

from integrations.delivery import apply_delivery_cost
from integrations.sync import sync_order_to_bpium_safe
from orders.models import (
    ExtractionAttempt,
    IntakeMessage,
    Order,
    OrderItem,
    OrderStatusHistory,
)

from .client import (
    GigaChatClient,
    InstructorOpenAIClient,
    LLMClient,
    MockLLMClient,
    YandexGPTClient,
)
from .schemas import OrderExtract
from .validators import apply_post_validation

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_default_llm_client() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "openai" if os.getenv("OPENAI_API_KEY") else "mock"

    try:
        if provider == "mock":
            return MockLLMClient()

        if provider == "openai":
            return InstructorOpenAIClient(
                model_name=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL", "") or None,
                require_api_key=True,
            )

        if provider == "vllm":
            return InstructorOpenAIClient(
                model_name=os.getenv("VLLM_MODEL", os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")),
                api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
                base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
            )

        if provider == "yandexgpt":
            return YandexGPTClient(
                model_name=os.getenv("YANDEXGPT_MODEL_NAME", "yandexgpt-lite"),
                model_uri=os.getenv("YANDEXGPT_MODEL_URI", "") or None,
                api_key=os.getenv("YANDEXGPT_API_KEY"),
                folder_id=os.getenv("YANDEXGPT_FOLDER_ID"),
                endpoint=os.getenv(
                    "YANDEXGPT_API_URL",
                    "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                ),
                timeout=float(os.getenv("YANDEXGPT_TIMEOUT", "30")),
            )

        if provider == "gigachat":
            return GigaChatClient(
                model_name=os.getenv("GIGACHAT_MODEL", "GigaChat-2-Max"),
                auth_key=os.getenv("GIGACHAT_AUTH_KEY"),
                scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
                auth_url=os.getenv(
                    "GIGACHAT_AUTH_URL",
                    "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                ),
                api_url=os.getenv(
                    "GIGACHAT_API_URL",
                    "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
                ),
                verify_ssl=_env_bool("GIGACHAT_VERIFY_SSL", True),
                timeout=float(os.getenv("GIGACHAT_TIMEOUT", "30")),
            )
    except Exception as exc:
        logger.warning(
            "llm_provider_init_failed provider=%s error=%s fallback=mock",
            provider,
            exc,
        )
        return MockLLMClient()

    logger.warning("unknown_llm_provider provider=%s fallback=mock", provider)
    return MockLLMClient()


def _load_previous_extraction(order: Order | None) -> OrderExtract | None:
    if order is None:
        return None
    last_attempt = order.extraction_attempts.order_by("-created_at").first()
    if not last_attempt:
        return None
    try:
        return OrderExtract.model_validate(last_attempt.result_json)
    except Exception:
        return None


def _sync_order_items(order: Order, extract: OrderExtract) -> None:
    order.items.all().delete()
    for item in extract.items:
        OrderItem.objects.create(
            order=order,
            title=item.title,
            quantity=item.qty,
            size=item.size or "",
            color=item.color or "",
        )


@transaction.atomic
def process_intake_message(
    intake: IntakeMessage,
    llm_client: LLMClient | None = None,
    order: Order | None = None,
) -> tuple[Order, ExtractionAttempt]:
    llm = llm_client or get_default_llm_client()
    previous_extraction = _load_previous_extraction(order)
    raw_extract = llm.parse(text=intake.raw_text, current_extraction=previous_extraction)
    extract = apply_post_validation(raw_extract)

    new_status = (
        Order.Status.NEEDS_INFO if extract.missing_fields else Order.Status.CONFIRMED
    )

    if order is None:
        order = Order.objects.create(
            customer=intake.customer,
            intake=intake,
            channel=intake.channel,
            status=new_status,
            delivery_address=extract.delivery.address or "",
            delivery_city=extract.delivery.city or "",
            comment=extract.comment or "",
        )
        old_status = ""
    else:
        old_status = order.status
        order.status = new_status
        order.delivery_address = extract.delivery.address or order.delivery_address
        order.delivery_city = extract.delivery.city or order.delivery_city
        order.comment = extract.comment or order.comment
        order.save()

    if new_status == Order.Status.CONFIRMED and order.needs_manual_review:
        order.needs_manual_review = False
        order.save(update_fields=["needs_manual_review", "updated_at"])

    if new_status == Order.Status.CONFIRMED:
        apply_delivery_cost(order)

    customer = intake.customer
    customer_updated = False
    if extract.customer.name and customer.name != extract.customer.name:
        customer.name = extract.customer.name
        customer_updated = True
    if extract.customer.phone and customer.phone != extract.customer.phone:
        customer.phone = extract.customer.phone
        customer_updated = True
    if extract.customer.email and customer.email != extract.customer.email:
        customer.email = extract.customer.email
        customer_updated = True
    if customer_updated:
        customer.save()

    _sync_order_items(order, extract)

    attempt = ExtractionAttempt.objects.create(
        intake=intake,
        order=order,
        model_name=llm.model_name,
        result_json=extract.model_dump(mode="json"),
        confidence=float(extract.confidence),
        missing_fields=extract.missing_fields,
        is_success=not bool(extract.missing_fields),
    )

    if old_status != order.status:
        OrderStatusHistory.objects.create(
            order=order,
            old_status=old_status,
            new_status=order.status,
            changed_by="system",
            comment="auto-from-ai-parser",
        )

    if order.status == Order.Status.NEEDS_INFO:
        attempts_count = order.extraction_attempts.count()
        if attempts_count > 3 and not order.needs_manual_review:
            order.needs_manual_review = True
            order.save(update_fields=["needs_manual_review", "updated_at"])
            OrderStatusHistory.objects.create(
                order=order,
                old_status=order.status,
                new_status=order.status,
                changed_by="system",
                comment="manual review required after repeated failed extraction",
            )
    else:
        sync_order_to_bpium_safe(order)

    return order, attempt
