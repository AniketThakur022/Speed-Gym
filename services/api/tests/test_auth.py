"""Auth integration tests — run against the live dev stack (Postgres + Redis).

Skipped automatically when the databases aren't reachable, so CI without a
stack stays green (the health suite covers the no-DB path).
"""

import os
import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.security import hash_password, verify_password


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable("localhost", 5432) and _reachable("localhost", 6379)),
    reason="dev stack (Postgres+Redis) not running",
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def credentials():
    return {
        "email": f"test-{uuid.uuid4().hex[:12]}@vsg.com",
        "password": "correct-horse-battery",
        "display_name": "Parity Tester",
    }


def test_password_hash_roundtrip_and_rejection():
    stored = hash_password("s3cret-passphrase")
    assert verify_password("s3cret-passphrase", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", None)
    # Salted: same password hashes differently each time.
    assert stored != hash_password("s3cret-passphrase")


def test_register_returns_contract_shape(client, credentials):
    res = client.post("/api/v1/auth/register", json=credentials)
    assert res.status_code == 201
    body = res.json()
    assert set(body) == {"user", "token", "refreshToken"}
    assert set(body["user"]) >= {"id", "name", "email", "role"}
    assert body["user"]["email"] == credentials["email"]
    assert body["user"]["tier"] == "free"


def test_duplicate_email_conflicts(client, credentials):
    client.post("/api/v1/auth/register", json=credentials)
    res = client.post("/api/v1/auth/register", json=credentials)
    assert res.status_code == 409


def test_login_succeeds_and_wrong_password_401s(client, credentials):
    client.post("/api/v1/auth/register", json=credentials)
    ok = client.post(
        "/api/v1/auth/login",
        json={"email": credentials["email"], "password": credentials["password"]},
    )
    assert ok.status_code == 200
    assert ok.json()["token"]

    bad = client.post(
        "/api/v1/auth/login", json={"email": credentials["email"], "password": "nope"}
    )
    assert bad.status_code == 401


def test_me_requires_bearer_and_returns_the_caller(client, credentials):
    token = client.post("/api/v1/auth/register", json=credentials).json()["token"]
    assert client.get("/api/v1/auth/me").status_code == 401
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["user"]["email"] == credentials["email"]


def test_refresh_rotates_and_replay_kills_the_device_session(client, credentials):
    headers = {"X-Device-Fingerprint": "device-under-test"}
    first = client.post("/api/v1/auth/register", json=credentials, headers=headers).json()

    rotated = client.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}, headers=headers
    )
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refreshToken"] != first["refreshToken"]

    # Replaying the consumed token is detected...
    replay = client.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}, headers=headers
    )
    assert replay.status_code == 401
    assert "replay" in replay.json()["detail"].lower()

    # ...and the successor is revoked with it (whole device session killed).
    after = client.post(
        "/api/v1/auth/refresh", json={"refreshToken": second["refreshToken"]}, headers=headers
    )
    assert after.status_code == 401


def test_logout_revokes_the_refresh_token(client, credentials):
    tokens = client.post("/api/v1/auth/register", json=credentials).json()
    assert client.post("/api/v1/auth/logout", json={"refreshToken": tokens["refreshToken"]}).status_code == 200
    res = client.post("/api/v1/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
    assert res.status_code == 401


def test_qr_pairing_flow_end_to_end(client, credentials):
    token = client.post("/api/v1/auth/register", json=credentials).json()["token"]

    gen = client.post("/api/v1/auth/scanner-login/generate").json()
    assert gen["expiresIn"] == 300

    pending = client.get(
        "/api/v1/auth/scanner-login/poll",
        params={"code": gen["code"], "pollToken": gen["pollToken"]},
    )
    assert pending.json()["status"] == "pending"

    approved = client.post(
        "/api/v1/auth/scanner-login/verify",
        json={"code": gen["code"], "sig": gen["sig"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approved.status_code == 200

    collected = client.get(
        "/api/v1/auth/scanner-login/poll",
        params={"code": gen["code"], "pollToken": gen["pollToken"]},
    )
    assert collected.status_code == 200
    body = collected.json()
    assert body["status"] == "approved"
    assert body["user"]["email"] == credentials["email"]
    assert body["token"] and body["refreshToken"]

    # One-time nonce: the code is burned after collection.
    again = client.get(
        "/api/v1/auth/scanner-login/poll",
        params={"code": gen["code"], "pollToken": gen["pollToken"]},
    )
    assert again.status_code == 410


def test_qr_rejects_forged_signature_and_bad_poll_token(client, credentials):
    token = client.post("/api/v1/auth/register", json=credentials).json()["token"]
    gen = client.post("/api/v1/auth/scanner-login/generate").json()

    forged = client.post(
        "/api/v1/auth/scanner-login/verify",
        json={"code": gen["code"], "sig": "deadbeef"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert forged.status_code == 400

    wrong_poll = client.get(
        "/api/v1/auth/scanner-login/poll",
        params={"code": gen["code"], "pollToken": "not-the-token"},
    )
    assert wrong_poll.status_code == 403


def test_firebase_routes_exist_but_are_not_configured(client):
    for path in ("/api/v1/auth/google", "/api/v1/auth/phone"):
        res = client.post(path, json={"idToken": "fake"})
        assert res.status_code == 501


def test_payment_webhooks_never_accept_unsigned_bodies(client):
    """Block 4 replaced the 501 shells. With no webhook secret configured the
    routes answer 503; with one, a body lacking a valid signature is 400.
    Either way an unsigned webhook is never applied."""
    for path in ("/api/webhooks/stripe", "/api/webhooks/razorpay"):
        res = client.post(path, json={})
        assert res.status_code in (400, 503)
