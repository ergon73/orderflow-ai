from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse


def _client_ip(request) -> str:
    forwarded_for = (request.META.get("HTTP_X_FORWARDED_FOR") or "").strip()
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    return (request.META.get("REMOTE_ADDR") or "").strip() or "unknown"


def storefront_post_rate_limit(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.method != "POST":
            return view_func(request, *args, **kwargs)

        limit = max(1, int(getattr(settings, "STOREFRONT_RATE_LIMIT_REQUESTS", 20)))
        window_seconds = max(
            1,
            int(getattr(settings, "STOREFRONT_RATE_LIMIT_WINDOW_SECONDS", 60)),
        )
        key = f"storefront:post:ip:{_client_ip(request)}"
        count = cache.get(key)
        if count is None:
            count = 1
            cache.set(key, count, timeout=window_seconds)
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                count = 1
                cache.set(key, count, timeout=window_seconds)

        if count > limit:
            response = HttpResponse("Too many requests. Try again later.", status=429)
            response["Retry-After"] = str(window_seconds)
            return response
        return view_func(request, *args, **kwargs)

    return _wrapped
