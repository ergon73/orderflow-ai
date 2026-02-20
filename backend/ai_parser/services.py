from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
from pathlib import Path
import re
import time

from django.db import transaction

from config.env_utils import env_bool
from orders.models import (
    ExtractionAttempt,
    IntakeMessage,
    Order,
    OrderItem as OrderItemModel,
    OrderStatusHistory,
)
from orders.orchestrator import apply_confirmed_order_side_effects, sync_order_after_parsing

from .client import (
    GigaChatClient,
    InstructorOpenAIClient,
    LLMClient,
    MockLLMClient,
    YandexGPTClient,
)
from .schemas import OrderExtract, OrderItem as ParsedOrderItem
from .validators import apply_post_validation, normalize_phone

logger = logging.getLogger(__name__)


PHONE_RE = re.compile(r"(\+?\d[\d\-\(\)\s]{9,}\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
ADDRESS_RE = re.compile(
    r"(?i)(?:адрес|доставка)\s*[:,-]?\s*([^;\n]+)"
)
ADDRESS_FALLBACK_RE = re.compile(
    r"(?i)\b(?:ул\.?|улица|пр-т|проспект|пер\.?|переулок|шоссе|наб\.?)\s*[^;\n]+"
)
ITEM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(\d{1,3})\s*(?:x\s*)?круж\w*"), "кружка"),
    (re.compile(r"(?i)\b(\d{1,3})\s*(?:x\s*)?футбол\w*"), "футболка"),
    (re.compile(r"(?i)\b(\d{1,3})\s*(?:x\s*)?худи\w*"), "худи"),
    (re.compile(r"(?i)\b(\d{1,3})\s*(?:x\s*)?свитшот\w*"), "свитшот"),
    (re.compile(r"(?i)\b(\d{1,3})\s*(?:x\s*)?кепк\w*"), "кепка"),
]
ITEM_KEYWORDS: list[tuple[str, str]] = [
    ("круж", "кружка"),
    ("футбол", "футболка"),
    ("худи", "худи"),
    ("свитшот", "свитшот"),
    ("кепк", "кепка"),
]

def _resolve_gigachat_verify() -> bool | str:
    cert_path = os.getenv("GIGACHAT_CERT_PATH", "").strip()
    if cert_path:
        candidates = [Path(cert_path)]
        repo_root = Path(__file__).resolve().parents[2]
        candidates.append(repo_root / cert_path)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return env_bool("GIGACHAT_VERIFY_SSL", True)


def _resolve_default_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        return "openai" if os.getenv("OPENAI_API_KEY") else "mock"
    return provider


def _build_llm_client_for_provider(provider: str) -> LLMClient:
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
            verify_ssl=_resolve_gigachat_verify(),
            timeout=float(os.getenv("GIGACHAT_TIMEOUT", "30")),
        )

    raise ValueError(f"Unknown provider: {provider}")


def _parse_provider_list(raw: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in raw.split(","):
        provider = part.strip().lower()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        result.append(provider)
    return result


def _multi_eval_enabled() -> bool:
    return env_bool("LLM_MULTI_EVAL_ENABLED", False)


def _run_shadow_evaluations(
    intake: IntakeMessage,
    order: Order,
    previous_extraction: OrderExtract | None,
    primary_provider: str,
) -> None:
    configured = os.getenv("LLM_MULTI_EVAL_PROVIDERS", "gigachat,yandexgpt,vllm")
    providers = [
        provider
        for provider in _parse_provider_list(configured)
        if provider != primary_provider
    ]
    if not providers:
        return

    def evaluate(provider: str) -> tuple[str, str, OrderExtract | None, str]:
        try:
            llm = _build_llm_client_for_provider(provider)
            extract = _parse_and_validate(
                llm=llm,
                intake_text=intake.raw_text,
                previous_extraction=previous_extraction,
            )
            return provider, llm.model_name, extract, ""
        except Exception as exc:
            return provider, "", None, str(exc)

    results: list[tuple[str, str, OrderExtract | None, str]] = []
    if env_bool("LLM_MULTI_EVAL_PARALLEL", True) and len(providers) > 1:
        max_workers = max(
            1,
            min(len(providers), int(os.getenv("LLM_MULTI_EVAL_MAX_WORKERS", "3"))),
        )
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {pool.submit(evaluate, provider): provider for provider in providers}
            for future in as_completed(future_map):
                results.append(future.result())
    else:
        for provider in providers:
            results.append(evaluate(provider))

    for provider, model_name, extract, error in results:
        if extract is not None:
            ExtractionAttempt.objects.create(
                intake=intake,
                order=order,
                model_name=f"shadow:{provider}:{model_name}",
                result_json=extract.model_dump(mode="json"),
                confidence=float(extract.confidence),
                missing_fields=extract.missing_fields,
                is_success=not bool(extract.missing_fields),
            )
        else:
            ExtractionAttempt.objects.create(
                intake=intake,
                order=order,
                model_name=f"shadow:{provider}:error",
                result_json={},
                confidence=0.0,
                missing_fields=["shadow_error"],
                is_success=False,
                error_message=(error or "shadow evaluation failed")[:1000],
            )


def _gigachat_escalation_enabled() -> bool:
    return env_bool("GIGACHAT_ESCALATION_ENABLED", True)


def _yandex_escalation_enabled() -> bool:
    return env_bool("YANDEXGPT_ESCALATION_ENABLED", True)


def _build_gigachat_escalation_client(primary: GigaChatClient) -> GigaChatClient | None:
    escalation_model = os.getenv("GIGACHAT_ESCALATION_MODEL", "GigaChat-2-Max").strip()
    if not escalation_model or escalation_model == primary.model_name:
        return None
    return GigaChatClient(
        model_name=escalation_model,
        auth_key=primary.auth_key,
        scope=primary.scope,
        auth_url=primary.auth_url,
        api_url=primary.api_url,
        verify_ssl=primary.verify_ssl,
        timeout=primary.timeout,
    )


def _is_yandex_lite_model(model_name: str, model_uri: str) -> bool:
    lower_name = (model_name or "").lower()
    lower_uri = (model_uri or "").lower()
    return "yandexgpt-lite" in lower_name or "yandexgpt-lite" in lower_uri


def _resolve_yandex_escalation_model_uri(
    primary: YandexGPTClient,
    escalation_model_name: str,
) -> str:
    explicit_uri = os.getenv("YANDEXGPT_ESCALATION_MODEL_URI", "").strip()
    if explicit_uri:
        return explicit_uri

    if primary.folder_id:
        return f"gpt://{primary.folder_id}/{escalation_model_name}/latest"

    current_uri = (primary.model_uri or "").strip()
    match = re.match(r"^gpt://([^/]+)/([^/]+)/([^/]+)$", current_uri)
    if not match:
        return ""
    folder_id, _, model_version = match.groups()
    return f"gpt://{folder_id}/{escalation_model_name}/{model_version}"


def _build_yandex_escalation_client(primary: YandexGPTClient) -> YandexGPTClient | None:
    escalation_model_name = os.getenv(
        "YANDEXGPT_ESCALATION_MODEL_NAME",
        "yandexgpt",
    ).strip() or "yandexgpt"
    escalation_model_uri = _resolve_yandex_escalation_model_uri(
        primary,
        escalation_model_name,
    )
    if not escalation_model_uri and not primary.folder_id:
        return None
    if (
        escalation_model_name == primary.model_name
        and (
            not escalation_model_uri
            or escalation_model_uri == (primary.model_uri or "")
        )
    ):
        return None
    return YandexGPTClient(
        model_name=escalation_model_name,
        model_uri=escalation_model_uri or None,
        api_key=primary.api_key,
        folder_id=primary.folder_id,
        endpoint=primary.endpoint,
        timeout=primary.timeout,
    )


def _extract_quality_score(extract: OrderExtract) -> int:
    return (
        (12 if extract.items else 0)
        + (6 if extract.customer.phone else 0)
        + (6 if extract.delivery.address else 0)
        + (3 if extract.customer.email else 0)
        - (4 * len(extract.missing_fields))
    )


def _is_complex_for_escalation(
    intake_text: str,
    extract: OrderExtract,
    order: Order | None,
    *,
    text_len_threshold: int,
    missing_threshold: int,
) -> bool:
    text = intake_text or ""

    if len(text) >= text_len_threshold:
        return True
    if len(extract.missing_fields) >= missing_threshold:
        return True
    if not extract.items:
        return True
    if not extract.delivery.address:
        return True
    if not extract.customer.phone:
        return True

    lower = text.lower()
    complexity_tokens = ("исправ", "замен", "вместо", "еще", "добав", "но", "однако")
    if any(token in lower for token in complexity_tokens):
        return True

    if order is not None and order.extraction_attempts.count() >= 2:
        return True
    return False


def _is_complex_for_gigachat_escalation(
    intake_text: str,
    extract: OrderExtract,
    order: Order | None,
) -> bool:
    text_len_threshold = int(os.getenv("GIGACHAT_ESCALATION_TEXT_LEN", "260"))
    missing_threshold = int(os.getenv("GIGACHAT_ESCALATION_MISSING_FIELDS", "2"))
    return _is_complex_for_escalation(
        intake_text,
        extract,
        order,
        text_len_threshold=text_len_threshold,
        missing_threshold=missing_threshold,
    )


def _is_complex_for_yandex_escalation(
    intake_text: str,
    extract: OrderExtract,
    order: Order | None,
) -> bool:
    text_len_threshold = int(os.getenv("YANDEXGPT_ESCALATION_TEXT_LEN", "260"))
    missing_threshold = int(os.getenv("YANDEXGPT_ESCALATION_MISSING_FIELDS", "2"))
    return _is_complex_for_escalation(
        intake_text,
        extract,
        order,
        text_len_threshold=text_len_threshold,
        missing_threshold=missing_threshold,
    )


def _parse_and_validate(
    llm: LLMClient,
    intake_text: str,
    previous_extraction: OrderExtract | None,
) -> OrderExtract:
    started_at = time.monotonic()
    provider_name = llm.__class__.__name__
    model_name = getattr(llm, "model_name", "")
    try:
        raw_extract = llm.parse(text=intake_text, current_extraction=previous_extraction)
    except Exception as exc:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        logger.warning(
            "llm_parse_failed provider=%s model=%s latency_ms=%s error=%s",
            provider_name,
            model_name,
            latency_ms,
            exc,
        )
        raise
    latency_ms = int((time.monotonic() - started_at) * 1000)
    logger.info(
        "llm_parse_completed provider=%s model=%s latency_ms=%s",
        provider_name,
        model_name,
        latency_ms,
    )
    enriched_extract = _enrich_extract_from_raw_text(raw_extract, intake_text)
    return apply_post_validation(enriched_extract)


def _extract_items_from_raw_text(raw_text: str) -> list[ParsedOrderItem]:
    text = raw_text or ""
    lowered = text.lower()
    aggregated: dict[str, int] = {}

    for pattern, title in ITEM_PATTERNS:
        for match in pattern.finditer(text):
            qty = int(match.group(1))
            aggregated[title] = aggregated.get(title, 0) + qty

    for token, title in ITEM_KEYWORDS:
        if token in lowered and title not in aggregated:
            aggregated[title] = 1

    return [ParsedOrderItem(title=title, qty=qty) for title, qty in aggregated.items()]


def _enrich_extract_from_raw_text(extract: OrderExtract, raw_text: str) -> OrderExtract:
    enriched = extract.model_copy(deep=True)
    text = raw_text or ""

    if not enriched.items:
        enriched.items = _extract_items_from_raw_text(text)

    if not (enriched.customer.phone and enriched.customer.phone.strip()):
        phone_match = PHONE_RE.search(text)
        if phone_match:
            normalized = normalize_phone(phone_match.group(1))
            if normalized:
                enriched.customer.phone = normalized

    if not (enriched.customer.email and enriched.customer.email.strip()):
        email_match = EMAIL_RE.search(text)
        if email_match:
            enriched.customer.email = email_match.group(1).strip()

    if not (enriched.delivery.address and enriched.delivery.address.strip()):
        address_match = ADDRESS_RE.search(text)
        if address_match:
            candidate = address_match.group(1).strip(" ,.")
            candidate = re.split(
                r"(?i)\b(?:телефон|phone|email|почта|имя|name)\b",
                candidate,
                maxsplit=1,
            )[0].strip(" ,.")
            if len(candidate) >= 5:
                enriched.delivery.address = candidate
        else:
            fallback_match = ADDRESS_FALLBACK_RE.search(text)
            if fallback_match:
                candidate = fallback_match.group(0).strip(" ,.")
                if len(candidate) >= 5:
                    enriched.delivery.address = candidate

    return enriched


def get_default_llm_client() -> LLMClient:
    provider = _resolve_default_provider()

    try:
        return _build_llm_client_for_provider(provider)
    except Exception as exc:
        logger.warning(
            "llm_provider_init_failed provider=%s error=%s fallback=mock",
            provider,
            exc,
        )
        return MockLLMClient()


def _load_previous_extraction(order: Order | None) -> OrderExtract | None:
    if order is None:
        return None
    last_attempt = (
        order.extraction_attempts.exclude(model_name__startswith="shadow:")
        .order_by("-created_at")
        .first()
    )
    if not last_attempt:
        return None
    try:
        return OrderExtract.model_validate(last_attempt.result_json)
    except Exception:
        return None


def _sync_order_items(order: Order, extract: OrderExtract) -> None:
    order.items.all().delete()
    for item in extract.items:
        OrderItemModel.objects.create(
            order=order,
            title=item.title,
            quantity=item.qty,
            size=item.size or "",
            color=item.color or "",
        )


def _resolve_extract_with_escalation(
    *,
    llm: LLMClient,
    intake_text: str,
    previous_extraction: OrderExtract | None,
    order: Order | None,
) -> tuple[OrderExtract, str]:
    selected_model_name = llm.model_name

    is_gigachat_escalation_path = (
        isinstance(llm, GigaChatClient)
        and _gigachat_escalation_enabled()
        and "pro" in llm.model_name.lower()
    )
    is_yandex_escalation_path = (
        isinstance(llm, YandexGPTClient)
        and _yandex_escalation_enabled()
        and _is_yandex_lite_model(llm.model_name, llm.model_uri)
    )

    try:
        extract = _parse_and_validate(llm, intake_text, previous_extraction)
    except Exception:
        escalation_llm: LLMClient | None = None
        if is_gigachat_escalation_path:
            escalation_llm = _build_gigachat_escalation_client(llm)
        elif is_yandex_escalation_path:
            escalation_llm = _build_yandex_escalation_client(llm)
        if escalation_llm is None:
            raise
        extract = _parse_and_validate(escalation_llm, intake_text, previous_extraction)
        return extract, escalation_llm.model_name

    if is_gigachat_escalation_path and _is_complex_for_gigachat_escalation(
        intake_text,
        extract,
        order,
    ):
        escalation_llm = _build_gigachat_escalation_client(llm)
        if escalation_llm is not None:
            try:
                escalation_extract = _parse_and_validate(
                    escalation_llm,
                    intake_text,
                    previous_extraction,
                )
                if _extract_quality_score(escalation_extract) > _extract_quality_score(extract):
                    return escalation_extract, escalation_llm.model_name
            except Exception as exc:
                logger.warning(
                    "gigachat_escalation_failed model=%s fallback_model=%s error=%s",
                    llm.model_name,
                    escalation_llm.model_name,
                    exc,
                )
    elif is_yandex_escalation_path and _is_complex_for_yandex_escalation(
        intake_text,
        extract,
        order,
    ):
        escalation_llm = _build_yandex_escalation_client(llm)
        if escalation_llm is not None:
            try:
                escalation_extract = _parse_and_validate(
                    escalation_llm,
                    intake_text,
                    previous_extraction,
                )
                if _extract_quality_score(escalation_extract) > _extract_quality_score(extract):
                    return escalation_extract, escalation_llm.model_name
            except Exception as exc:
                logger.warning(
                    "yandex_escalation_failed model=%s fallback_model=%s error=%s",
                    llm.model_name,
                    escalation_llm.model_name,
                    exc,
                )

    return extract, selected_model_name


def _resolve_order_status(extract: OrderExtract) -> str:
    return Order.Status.NEEDS_INFO if extract.missing_fields else Order.Status.CONFIRMED


def _upsert_order_from_extract(
    *,
    intake: IntakeMessage,
    order: Order | None,
    extract: OrderExtract,
    new_status: str,
) -> tuple[Order, str]:
    if order is None:
        created_order = Order.objects.create(
            customer=intake.customer,
            intake=intake,
            channel=intake.channel,
            status=new_status,
            delivery_address=extract.delivery.address or "",
            delivery_city=extract.delivery.city or "",
            comment=extract.comment or "",
        )
        return created_order, ""

    persisted_order = Order.objects.select_for_update().get(id=order.id)
    old_status = persisted_order.status
    persisted_order.status = new_status
    persisted_order.delivery_address = extract.delivery.address or persisted_order.delivery_address
    persisted_order.delivery_city = extract.delivery.city or persisted_order.delivery_city
    persisted_order.comment = extract.comment or persisted_order.comment
    persisted_order.save(
        update_fields=[
            "status",
            "delivery_address",
            "delivery_city",
            "comment",
            "updated_at",
        ]
    )
    return persisted_order, old_status


def _clear_manual_review_on_confirmed(order: Order, new_status: str) -> None:
    if new_status == Order.Status.CONFIRMED and order.needs_manual_review:
        order.needs_manual_review = False
        order.save(update_fields=["needs_manual_review", "updated_at"])


def _update_customer_from_extract(customer, extract: OrderExtract) -> None:
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
        customer.save(update_fields=["name", "phone", "email", "updated_at"])


def _create_extraction_attempt(
    *,
    intake: IntakeMessage,
    order: Order,
    model_name: str,
    extract: OrderExtract,
) -> ExtractionAttempt:
    return ExtractionAttempt.objects.create(
        intake=intake,
        order=order,
        model_name=model_name,
        result_json=extract.model_dump(mode="json"),
        confidence=float(extract.confidence),
        missing_fields=extract.missing_fields,
        is_success=not bool(extract.missing_fields),
    )


def _maybe_run_shadow_evals(
    *,
    intake: IntakeMessage,
    order: Order,
    previous_extraction: OrderExtract | None,
    llm_client: LLMClient | None,
) -> None:
    if llm_client is not None or not _multi_eval_enabled():
        return
    try:
        _run_shadow_evaluations(
            intake=intake,
            order=order,
            previous_extraction=previous_extraction,
            primary_provider=_resolve_default_provider(),
        )
    except Exception as exc:
        logger.warning("llm_shadow_eval_failed order_id=%s error=%s", order.id, exc)


def _record_status_transition(order: Order, old_status: str) -> None:
    if old_status == order.status:
        return
    OrderStatusHistory.objects.create(
        order=order,
        old_status=old_status,
        new_status=order.status,
        changed_by="system",
        comment="auto-from-ai-parser",
    )


def _maybe_mark_manual_review(order: Order) -> None:
    attempts_count = order.extraction_attempts.exclude(
        model_name__startswith="shadow:"
    ).count()
    if attempts_count <= 3 or order.needs_manual_review:
        return
    order.needs_manual_review = True
    order.save(update_fields=["needs_manual_review", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order,
        old_status=order.status,
        new_status=order.status,
        changed_by="system",
        comment="manual review required after repeated failed extraction",
    )


@transaction.atomic
def process_intake_message(
    intake: IntakeMessage,
    llm_client: LLMClient | None = None,
    order: Order | None = None,
) -> tuple[Order, ExtractionAttempt]:
    llm = llm_client or get_default_llm_client()
    previous_extraction = _load_previous_extraction(order)
    extract, selected_model_name = _resolve_extract_with_escalation(
        llm=llm,
        intake_text=intake.raw_text,
        previous_extraction=previous_extraction,
        order=order,
    )
    new_status = _resolve_order_status(extract)
    order, old_status = _upsert_order_from_extract(
        intake=intake,
        order=order,
        extract=extract,
        new_status=new_status,
    )
    _clear_manual_review_on_confirmed(order, new_status)

    if new_status == Order.Status.CONFIRMED:
        apply_confirmed_order_side_effects(order)

    _update_customer_from_extract(intake.customer, extract)

    _sync_order_items(order, extract)

    attempt = _create_extraction_attempt(
        intake=intake,
        order=order,
        model_name=selected_model_name,
        extract=extract,
    )
    _maybe_run_shadow_evals(
        intake=intake,
        order=order,
        previous_extraction=previous_extraction,
        llm_client=llm_client,
    )
    _record_status_transition(order, old_status)

    if order.status == Order.Status.NEEDS_INFO:
        _maybe_mark_manual_review(order)
    else:
        sync_order_after_parsing(order)

    return order, attempt
