"""Feature-flag service: deterministic rollout, fail-closed, kill-switch latency."""

import asyncio
import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from app import flags as flags_service
from app.flags import _decide, bucket
from app.main import create_app


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


# ── pure ─────────────────────────────────────────────────────────────────────


def test_bucket_is_stable_and_spread():
    assert bucket("user-1", "f") == bucket("user-1", "f")
    assert bucket("user-1", "f") != bucket("user-1", "g") or bucket("user-2", "f") != bucket("user-1", "f")
    hits = sum(1 for i in range(2000) if bucket(f"u{i}", "flag") < 10)
    assert 140 <= hits <= 260  # ~10%


def test_decide_rules():
    on = {"name": "x", "enabled": True, "rollout_pct": 100}
    off = {"name": "x", "enabled": False, "rollout_pct": 100}
    partial = {"name": "x", "enabled": True, "rollout_pct": 50}
    assert _decide(on, None) and _decide(on, "u")
    assert not _decide(off, "u")
    assert not _decide(None, "u")                       # unknown flag = dark
    assert not _decide(partial, None)                   # anonymous never in a partial rollout
    kept = sum(1 for i in range(1000) if _decide(partial, f"u{i}"))
    assert 400 <= kept <= 600
    assert _decide(partial, "u1") == _decide(partial, "u1")


# ── DB + Redis ───────────────────────────────────────────────────────────────

pytestmark_db = pytest.mark.skipif(
    not (_reachable("localhost", 5432) and _reachable("localhost", 6379)), reason="dev DBs not running"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def admin(client):
    import psycopg

    creds = {"email": f"flagadmin-{uuid.uuid4().hex[:8]}@vsg.com", "password": "correct-horse-battery"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    with psycopg.connect("postgresql://vmsg:vmsg@localhost:5432/vmsg") as conn:
        conn.execute("UPDATE users SET is_admin = TRUE WHERE id = %s::uuid", (tokens["user"]["id"],))
        conn.commit()
    return {"Authorization": f"Bearer {tokens['token']}"}


def _set(client, admin, name, enabled, rollout=None):
    body = {"enabled": enabled}
    if rollout is not None:
        body["rollout_pct"] = rollout
    res = client.post(f"/api/admin/flags/{name}", json=body, headers=admin)
    assert res.status_code == 200, res.text


@pytestmark_db
def test_config_reflects_a_flip_immediately_in_process(client, admin):
    _set(client, admin, "social_ghosts", True, 100)
    assert client.get("/api/config").json()["flags"]["social_ghosts"]["enabled"] is True
    _set(client, admin, "social_ghosts", False)
    cfg = client.get("/api/config").json()
    assert cfg["degraded"] is False
    assert cfg["flags"]["social_ghosts"]["enabled"] is False
    assert asyncio.run(flags_service.flag_enabled("social_ghosts", "anyone")) is False
    _set(client, admin, "social_ghosts", True, 100)


@pytestmark_db
def test_partial_rollout_is_deterministic_per_user(client, admin):
    _set(client, admin, "social_clips", True, 30)
    try:
        answers = {f"u{i}": asyncio.run(flags_service.flag_enabled("social_clips", f"u{i}")) for i in range(50)}
        again = {u: asyncio.run(flags_service.flag_enabled("social_clips", u)) for u in answers}
        assert answers == again
        assert 0 < sum(answers.values()) < 50
        assert asyncio.run(flags_service.flag_enabled("social_clips", None)) is False
    finally:
        _set(client, admin, "social_clips", False, 100)


@pytestmark_db
def test_unknown_flags_cannot_be_invented_and_config_exposes_states_only(client, admin):
    assert client.post("/api/admin/flags/made_up", json={"enabled": True}, headers=admin).status_code == 404
    cfg = client.get("/api/config").json()
    for f in cfg["flags"].values():
        assert set(f) == {"enabled", "rollout_pct"}


@pytestmark_db
def test_admin_kpi_read(client, admin):
    res = client.get("/api/admin/kpi", headers=admin)
    assert res.status_code == 200 and "metrics" in res.json()
