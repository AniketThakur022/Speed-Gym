"""Sync ingest tests — idempotency is the property that matters.

A client that drops connection mid-flush resends the batch. If a resend
double-counted attempts it would corrupt mastery, so re-sends must be absorbed.
"""

import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable("localhost", 5432), reason="dev Postgres not running"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth(client):
    credentials = {
        "email": f"sync-{uuid.uuid4().hex[:12]}@vsg.com",
        "password": "correct-horse-battery",
    }
    tokens = client.post("/api/v1/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['token']}"}


def _event(event_type="problem_attempt", **overrides):
    payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "client_timestamp": 1_760_000_000_000,
        "metadata": {"technique_id": "nikhilam", "is_correct": True},
    }
    payload.update(overrides)
    return payload


def test_sync_requires_authentication(client):
    assert client.post("/api/v1/sync", json={"events": []}).status_code == 401


def test_empty_batch_still_returns_entitlement(client, auth):
    body = client.post("/api/v1/sync", json={"events": []}, headers=auth).json()
    assert body["accepted"] == 0
    assert set(body["entitlement"]) == {"tier", "expires_at", "signature"}


def test_events_are_accepted_and_counted(client, auth):
    events = [_event(), _event(), _event("session_start")]
    body = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    assert body["accepted"] == 3
    assert body["duplicates"] == 0
    assert body["psychometric"] == 3


def test_resending_the_same_batch_does_not_double_count(client, auth):
    """The core guarantee: a retried flush must not inflate a learner's attempts."""
    events = [_event(), _event()]

    first = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    assert first["accepted"] == 2

    replay = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    assert replay["accepted"] == 0
    assert replay["duplicates"] == 2


def test_partial_resend_accepts_only_the_new_events(client, auth):
    original = [_event(), _event()]
    client.post("/api/v1/sync", json={"events": original}, headers=auth)

    mixed = original + [_event()]
    body = client.post("/api/v1/sync", json={"events": mixed}, headers=auth).json()
    assert body["accepted"] == 1
    assert body["duplicates"] == 2


def test_graph_writes_are_queued_through_the_outbox(client, auth):
    """Path C must not write Neo4j inline — a graph outage cannot lose a ledger row."""
    import psycopg

    event = _event()
    client.post("/api/v1/sync", json={"events": [event]}, headers=auth)

    with psycopg.connect("postgresql://vmsg:vmsg@localhost:5432/vmsg") as conn:
        row = conn.execute(
            "SELECT status FROM sync_outbox WHERE event_id = %s", (event["event_id"],)
        ).fetchone()
    assert row is not None and row[0] == "pending"


def test_session_end_writes_a_bkt_snapshot(client, auth):
    import psycopg

    session_id = str(uuid.uuid4())
    event = _event(
        "session_end",
        session_id=session_id,
        metadata={"technique_states": {"nikhilam": {"pLearned": 0.82, "state": "fragile"}}},
    )
    assert client.post("/api/v1/sync", json={"events": [event]}, headers=auth).status_code == 200

    with psycopg.connect("postgresql://vmsg:vmsg@localhost:5432/vmsg") as conn:
        row = conn.execute(
            "SELECT technique_states FROM bkt_state_snapshots WHERE session_id = %s::uuid",
            (session_id,),
        ).fetchone()
    assert row is not None
    assert row[0]["nikhilam"]["pLearned"] == 0.82


def test_content_feedback_replay_is_stored(client, auth):
    payload = {
        "templateId": "t2_mult_near_base_L2_demo",
        "trustStatus": "sandbox",
        "reason": "wrong_answer",
        "comment": "step 3 drops a carry",
        "reportedAt": 1_760_000_000_000,
        "domain": "vedic-math",
    }
    res = client.post("/api/v1/sync/content/feedback", json=payload, headers=auth)
    assert res.status_code == 200
    assert res.json()["key"] == "content/feedback"


def test_unknown_sync_keys_are_refused_rather_than_silently_dropped(client, auth):
    res = client.post("/api/v1/sync/content/unknown-thing", json={"templateId": "x"}, headers=auth)
    assert res.status_code == 404
