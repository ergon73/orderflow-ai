from __future__ import annotations

import logging
import os
import re
from typing import Any


_SENSITIVE_ENV_KEYS = (
    "SECRET_KEY",
    "OPENAI_API_KEY",
    "GIGACHAT_AUTH_KEY",
    "YANDEXGPT_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "BPIUM_PASSWORD",
    "YOOKASSA_SECRET",
    "APISHIP_TOKEN",
    "APISHIP_PASSWORD",
    "EMAIL_PASSWORD",
)

_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)\b(Basic)\s+[A-Za-z0-9._=\-]+"),
    re.compile(r"bot\d{6,12}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\b(token|password|secret|auth_key)\s*[:=]\s*[^\s,;]+"),
)


def sanitize_log_text(text: str) -> str:
    sanitized = text
    for env_key in _SENSITIVE_ENV_KEYS:
        secret_value = (os.getenv(env_key) or "").strip()
        if secret_value:
            sanitized = sanitized.replace(secret_value, "***")

    sanitized = _SENSITIVE_PATTERNS[0].sub(r"\1 ***", sanitized)
    sanitized = _SENSITIVE_PATTERNS[1].sub(r"\1 ***", sanitized)
    sanitized = _SENSITIVE_PATTERNS[2].sub("bot***", sanitized)
    sanitized = _SENSITIVE_PATTERNS[3].sub(r"\1=***", sanitized)
    return sanitized


def sanitize_exception_for_log(exc: Exception | str) -> str:
    return sanitize_log_text(str(exc))


def _sanitize_arg(value: Any) -> Any:
    if isinstance(value, Exception):
        return sanitize_exception_for_log(value)
    if isinstance(value, str):
        return sanitize_log_text(value)
    return value


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_log_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _sanitize_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_sanitize_arg(v) for v in record.args)
            else:
                record.args = _sanitize_arg(record.args)
        return True
