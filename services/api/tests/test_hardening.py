"""Block 9: rate limit headers + 429, security headers, body cap, request id."""

import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    p = MonkeyPatch()
    yield p
    p.undo()


def _reset_rate_limit_buckets() -> None:
    """The limiter keys unauthenticated requests on the client IP, and every
    TestClient in the suite shares "testclient" — so one module's traffic used
    to exhaust another's budget depending on file order. Clear the bucket for
    this process before asserting on limits."""
    try:
        import redis as _redis

        r = _redis.Redis.from_url("redis://localhost:6379/0")
        for key in r.scan_iter("ratelimit:*"):
            r.delete(key)
    except Exception:  # noqa: BLE001 — no Redis: the limiter fails open anyway
        pass


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    from app.config import get_settings

    monkeypatch_module.setenv("RATE_LIMIT_PER_MINUTE", "5")
    monkeypatch_module.setenv("BEHIND_TLS", "true")
    get_settings.cache_clear()
    _reset_rate_limit_buckets()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_security_headers_and_request_id_on_every_response(client):
    res = client.get("/health", headers={"X-Request-Id": "abc123"})
    assert res.status_code == 200
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert res.headers["Strict-Transport-Security"].startswith("max-age=")
    assert res.headers["X-Request-Id"] == "abc123"
    assert len(client.get("/health").headers["X-Request-Id"]) == 32


def test_body_cap_is_413_before_any_handler_runs(client):
    big = "x" * (1024 * 1024 + 10)
    res = client.post("/api/v1/auth/login", content=big, headers={"Content-Type": "application/json", "Content-Length": str(len(big))})
    assert res.status_code == 413


def test_health_and_webhooks_are_exempt_from_rate_limiting(client):
    for _ in range(8):
        assert client.get("/health").status_code == 200
    assert "X-RateLimit-Remaining" not in client.get("/health").headers


@pytest.mark.skipif(not (_reachable("localhost", 5432) and _reachable("localhost", 6379)), reason="dev DBs not running")
def test_rate_limit_headers_then_429_with_retry_after(client):
    creds = {"email": f"rl-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()   # 1 request from this IP bucket…
    auth = {"Authorization": f"Bearer {tokens['token']}"}              # …then a fresh per-user bucket
    seen = []
    for i in range(7):
        res = client.get("/api/v1/billing/plans", headers=auth)
        seen.append((res.status_code, res.headers.get("X-RateLimit-Remaining"), res.headers.get("Retry-After")))
    assert seen[0][0] == 200 and seen[0][1] == "4"
    assert seen[4][0] == 200 and seen[4][1] == "0"
    assert seen[5][0] == 429 and seen[5][1] == "0" and seen[5][2] is not None
