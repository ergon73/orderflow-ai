from __future__ import annotations

import os
import time
from typing import Any

import requests

from config.env_utils import env_float, env_int


RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
RETRYABLE_EXCEPTIONS = (requests.Timeout, requests.ConnectionError)


def _parse_retry_status_codes(raw: str) -> set[int]:
    parsed: set[int] = set()
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            code = int(token)
        except Exception:
            continue
        if 100 <= code <= 599:
            parsed.add(code)
    return parsed


def _resolve_retry_settings(prefix: str, *, default_retries: int = 2) -> tuple[int, float, float, set[int]]:
    max_retries = env_int(
        f"{prefix}_MAX_RETRIES",
        env_int("LLM_HTTP_MAX_RETRIES", default_retries),
    )
    backoff_base = env_float(
        f"{prefix}_RETRY_BACKOFF_BASE",
        env_float("LLM_HTTP_RETRY_BACKOFF_BASE", 0.5),
    )
    backoff_max = env_float(
        f"{prefix}_RETRY_BACKOFF_MAX",
        env_float("LLM_HTTP_RETRY_BACKOFF_MAX", 4.0),
    )
    provider_codes = _parse_retry_status_codes(os.getenv(f"{prefix}_RETRY_STATUS_CODES", ""))
    global_codes = _parse_retry_status_codes(os.getenv("LLM_HTTP_RETRY_STATUS_CODES", ""))
    status_codes = provider_codes or global_codes or set(RETRYABLE_STATUS_CODES)
    return max(0, max_retries), max(0.0, backoff_base), max(0.0, backoff_max), status_codes


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except Exception:
        return None
    if seconds < 0:
        return None
    return seconds


def _retry_sleep(
    *,
    retry_index: int,
    backoff_base: float,
    backoff_max: float,
    retry_after: float | None,
) -> None:
    delay = retry_after if retry_after is not None else (backoff_base * (2 ** max(0, retry_index - 1)))
    delay = min(backoff_max, delay) if backoff_max > 0 else delay
    if delay > 0:
        time.sleep(delay)


def _post_with_retry(
    url: str,
    *,
    max_retries: int,
    backoff_base: float,
    backoff_max: float,
    retry_status_codes: set[int],
    verify: bool | str | None = None,
    **kwargs: Any,
) -> requests.Response:
    attempts = 0
    while True:
        request_kwargs = dict(kwargs)
        if verify is not None:
            request_kwargs["verify"] = verify
        try:
            response = requests.post(url, **request_kwargs)
        except RETRYABLE_EXCEPTIONS as exc:
            # Certificate-chain errors are permanent configuration issues, not transient network failures.
            if isinstance(exc, requests.exceptions.SSLError) or attempts >= max_retries:
                raise
            attempts += 1
            _retry_sleep(
                retry_index=attempts,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
                retry_after=None,
            )
            continue

        if response.status_code in retry_status_codes and attempts < max_retries:
            attempts += 1
            retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            response.close()
            _retry_sleep(
                retry_index=attempts,
                backoff_base=backoff_base,
                backoff_max=backoff_max,
                retry_after=retry_after,
            )
            continue
        return response
