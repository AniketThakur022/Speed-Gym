"""Admin surface tests.

problem_health_scores decides what reaches a learner, so the privilege boundary
around it matters as much as the behaviour behind it.
"""

import socket
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

DB = "postgresql://vmsg:vmsg@localhost:5432/vmsg"


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable("localhost", 5432), reason="dev Postgres not running")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def _register(client, admin: bool = False) -> dict:
    credentials = {
        "email": f"admin-{uuid.uuid4().hex[:12]}@vsg.com",
        "password": "correct-horse-battery",
    }
    body = client.post("/api/v1/auth/register", json=credentials).json()
    if admin:
        with psycopg.connect(DB) as conn:
            conn.execute("UPDATE users SET is_admin = TRUE WHERE id = %s::uuid", (body["user"]["id"],))
            conn.commit()
    return {"Authorization": f"Bearer {body['token']}", "_id": body["user"]["id"]}


@pytest.fixture
def admin_headers(client):
    h = _register(client, admin=True)
    return {"Authorization": h["Authorization"]}


@pytest.fixture
def user_headers(client):
    h = _register(client, admin=False)
    return {"Authorization": h["Authorization"]}


# ── runtime config ──────────────────────────────────────────────────────────


def test_config_is_readable_without_a_token(client):
    """It carries the emergency kill-switch, so it must answer during an
    incident — including for a client whose token has expired."""
    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert "flags" in body
    assert body["degraded"] is False


def test_config_exposes_flag_state_only(client):
    """No thresholds, secrets or counts on an unauthenticated endpoint."""
    flags = client.get("/api/config").json()["flags"]
    assert flags
    for state in flags.values():
        assert set(state) == {"enabled", "rollout_pct"}


def test_phase_two_features_are_dark_by_default(client):
    flags = client.get("/api/config").json()["flags"]
    for name in ("boss_battle", "relay_race", "tournament", "dina_live", "irt_3pl_live"):
        assert flags[name]["enabled"] is False


# ── privilege boundary ──────────────────────────────────────────────────────


ADMIN_PATHS = [
    ("get", "/api/admin/content/trust"),
    ("get", "/api/admin/flags"),
]


@pytest.mark.parametrize("method,path", ADMIN_PATHS)
def test_admin_routes_reject_anonymous_callers(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_PATHS)
def test_admin_routes_reject_ordinary_users(client, user_headers, method, path):
    """A valid token is not authority: the flag is checked on the account."""
    assert getattr(client, method)(path, headers=user_headers).status_code == 403


def test_ordinary_user_cannot_change_content_trust(client, user_headers):
    res = client.post(
        "/api/admin/content/trust/Bird_Engineering_Math_sa_17",
        json={"trust_level": "TRUSTED", "reason": "should not work"},
        headers=user_headers,
    )
    assert res.status_code == 403


# ── trust administration ────────────────────────────────────────────────────


def test_admin_can_list_trust_with_totals(client, admin_headers):
    res = client.get("/api/admin/content/trust", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["totals"]
    assert sum(body["totals"].values()) >= 38  # the factory quarantine import


def test_override_requires_a_reason(client, admin_headers):
    """An unexplained override is indistinguishable from a mistake later."""
    res = client.post(
        "/api/admin/content/trust/Bird_Engineering_Math_sa_17",
        json={"trust_level": "TRUSTED", "reason": ""},
        headers=admin_headers,
    )
    assert res.status_code == 422


def test_override_rejects_an_unknown_trust_level(client, admin_headers):
    res = client.post(
        "/api/admin/content/trust/Bird_Engineering_Math_sa_17",
        json={"trust_level": "PROBABLY_FINE", "reason": "made-up level"},
        headers=admin_headers,
    )
    assert res.status_code == 422


def test_override_is_applied_and_audited_then_restored(client, admin_headers):
    content_id = "Bird_Engineering_Math_sa_17"
    before = client.get(f"/api/admin/content/trust/{content_id}", headers=admin_headers).json()
    original = before["trust_level"]

    res = client.post(
        f"/api/admin/content/trust/{content_id}",
        json={"trust_level": "SANDBOX", "reason": "manual review: walkthrough repaired"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["trust_level"] == "SANDBOX"

    detail = client.get(f"/api/admin/content/trust/{content_id}", headers=admin_headers).json()
    assert detail["trust_level"] == "SANDBOX"
    assert detail["overrides"], "the change must be answerable later"
    assert detail["overrides"][0]["reason"].startswith("manual review")
    assert detail["overrides"][0]["from"] == original

    # restore, so the suite leaves the trust table as it found it
    client.post(
        f"/api/admin/content/trust/{content_id}",
        json={"trust_level": original, "reason": "test teardown"},
        headers=admin_headers,
    )


def test_trust_detail_404s_for_content_with_no_record(client, admin_headers):
    res = client.get(f"/api/admin/content/trust/not-a-real-id-{uuid.uuid4().hex}", headers=admin_headers)
    assert res.status_code == 404


# ── feature flags ───────────────────────────────────────────────────────────


def test_unknown_flags_cannot_be_invented(client, admin_headers):
    """Creating a flag nothing reads gives a false sense of control."""
    res = client.post(
        "/api/admin/flags/not_a_real_flag", json={"enabled": True}, headers=admin_headers
    )
    assert res.status_code == 404


def test_kill_switch_round_trip_is_visible_in_public_config(client, admin_headers):
    """The whole point: an operator flips it, and clients see it."""
    assert client.get("/api/config").json()["flags"]["ad_engine"]["enabled"] is False

    client.post("/api/admin/flags/ad_engine", json={"enabled": True}, headers=admin_headers)
    assert client.get("/api/config").json()["flags"]["ad_engine"]["enabled"] is True

    client.post("/api/admin/flags/ad_engine", json={"enabled": False}, headers=admin_headers)
    assert client.get("/api/config").json()["flags"]["ad_engine"]["enabled"] is False
