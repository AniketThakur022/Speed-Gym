"""Hardening middleware (block 9).

* Rate limiting — fixed one-minute window in Redis keyed on the learner (JWT
  subject) or, unauthenticated, the client IP. Every response carries
  `X-RateLimit-Limit` / `X-RateLimit-Remaining` (the contract's header); over
  the limit → 429 with `Retry-After`. Redis down = fail OPEN: rate limiting
  is a traffic-shaping guard, not a security boundary, and an outage must not
  take the API down with it. Health, readiness, config, webhooks (providers
  retry on 429 forever) and the loopback internal API are exempt.
* Security headers on every response; HSTS only when the deployment says it
  terminates TLS (otherwise browsers would pin a plaintext dev host).
* Request body cap by Content-Length (413), larger for /sync batches.
* Request id — echoed as `X-Request-Id`, generated when absent — and a
  one-line structured access log.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import db
from .config import get_settings
from .security import decode_access_token

log = logging.getLogger("vmsg.access")

EXEMPT_PREFIXES = ("/health", "/ready", "/api/config", "/api/webhooks/", "/internal/", "/docs", "/openapi.json")
DEFAULT_BODY_LIMIT = 1 * 1024 * 1024
SYNC_BODY_LIMIT = 4 * 1024 * 1024


def _client_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            return "u:" + str(decode_access_token(auth.removeprefix("Bearer ").strip())["sub"])
        except Exception:  # noqa: BLE001 — expired/invalid: fall back to the IP bucket
            pass
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return "ip:" + ip


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        s = get_settings()
        path = request.url.path
        if s.rate_limit_per_minute <= 0 or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        limit = s.rate_limit_per_minute
        window = int(time.time() // 60)
        key = f"ratelimit:{_client_key(request)}:{window}"
        remaining = limit
        try:
            redis = db.get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 65)
            remaining = max(0, limit - int(count))
            if count > limit:
                retry = 60 - int(time.time() % 60)
                return JSONResponse(
                    {"detail": "rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": "0"},
                )
        except Exception:  # noqa: BLE001 — fail open
            remaining = limit

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(self)")
        h.setdefault("Cache-Control", "no-store")
        if get_settings().behind_tls:
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit():
            limit = SYNC_BODY_LIMIT if request.url.path.endswith("/sync") else DEFAULT_BODY_LIMIT
            if int(length) > limit:
                return JSONResponse({"detail": f"request body over {limit} bytes"}, status_code=413)
        return await call_next(request)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = rid
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        log.info(json.dumps({
            "rid": rid, "m": request.method, "p": request.url.path, "s": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }))
        return response


def install(app) -> None:
    """Outermost first: request id wraps everything; body limit before any
    handler reads; rate limit before work; headers on the way out."""
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
