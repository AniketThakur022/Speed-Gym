"""The frozen /api/v1/dashboard/* contract, fed by real synced events."""

import socket
import time
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


pytestmark = pytest.mark.skipif(not _reachable("localhost", 5432), reason="dev Postgres not running")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth(client):
    creds = {"email": f"dash-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery",
             "display_name": "Dash Tester"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    return {"Authorization": f"Bearer {tokens['token']}"}


def _attempt(is_correct, time_ms, skill="nikhilam", domain="vedic-math"):
    return {"event_id": str(uuid.uuid4()), "event_type": "problem_attempt",
            "client_timestamp": int(time.time() * 1000),
            "metadata": {"skill": skill, "problem_id": "t1", "is_correct": is_correct, "time_ms": time_ms, "domain": domain}}


def _seed(client, auth):
    events = [_attempt(True, 4000) for _ in range(6)] + [_attempt(False, 9000) for _ in range(2)]
    events.append({"event_id": str(uuid.uuid4()), "event_type": "session_end", "client_timestamp": int(time.time() * 1000),
                   "session_id": str(uuid.uuid4()),
                   "metadata": {"problems_attempted": 8, "problems_correct": 6, "session_type": "sprint", "domain": "vedic-math",
                                "technique_states": {"nikhilam": {"pLearned": 0.82, "state": "fluid"},
                                                     "urdhva": {"pLearned": 0.41, "state": "fragile"}}}})
    res = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    assert res["accepted"] == 9
    return res


def test_sync_awards_xp_and_a_streak_day(client, auth):
    res = _seed(client, auth)
    # 6 correct × 10 + session 25 + first streak day 20
    assert res["xp_awarded"] == 6 * 10 + 25 + 20
    streak = client.get("/api/v1/dashboard/streak", headers=auth).json()
    assert streak["current"] == 1 and streak["xp"] == 105
    assert len(streak["days"]) == 7 and any(streak["days"]) and streak["labels"] == ["M", "T", "W", "T", "F", "S", "S"]


def test_resent_batch_pays_no_xp_twice(client, auth):
    events = [_attempt(True, 3000)]
    first = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    again = client.post("/api/v1/sync", json={"events": events}, headers=auth).json()
    assert first["xp_awarded"] >= 10 and again["xp_awarded"] == 0


def test_stats_metrics_radar_shapes_from_real_attempts(client, auth):
    _seed(client, auth)
    stats = client.get("/api/v1/dashboard/stats", headers=auth).json()
    assert stats["accuracy"] == 75 and stats["questions"] == 8 and stats["speed"] == 5
    assert 0 <= stats["percentile"] <= 99
    metrics = client.get("/api/v1/dashboard/metrics", headers=auth).json()
    assert [m["label"] for m in metrics] == ["Action Delay", "Focus Density"]
    assert metrics[0]["value"].endswith("ms") and metrics[1]["value"] == "75%"
    radar = client.get("/api/v1/dashboard/radar", headers=auth).json()
    assert [a["label"] for a in radar] == ["Speed", "Logic", "Stamina", "Focus", "Memory", "Reflex"]
    assert all(0 <= a["value"] <= 1 for a in radar)
    assert next(a for a in radar if a["label"] == "Logic")["value"] == 0.75


def test_domain_filter_on_stats(client, auth):
    _seed(client, auth)
    assert client.get("/api/v1/dashboard/stats?domain=gmat", headers=auth).json()["questions"] == 0
    assert client.get("/api/v1/dashboard/stats?domain=vedic-math", headers=auth).json()["questions"] == 8


def test_topics_come_from_the_bkt_snapshot(client, auth):
    _seed(client, auth)
    topics = client.get("/api/v1/dashboard/topics", headers=auth).json()
    assert topics[0] == {"name": "nikhilam", "value": 82, "color": "primary"}
    assert topics[1]["name"] == "urdhva" and topics[1]["value"] == 41


def test_recent_activity_and_events(client, auth):
    _seed(client, auth)
    recent = client.get("/api/v1/dashboard/recent-activity", headers=auth).json()
    assert recent[0]["label"] == "Sprint session" and recent[0]["score"] == "6/8"
    events = client.get("/api/v1/dashboard/events", headers=auth).json()
    assert {"title": "Daily Challenge", "time": "Today", "tag": "LIVE"} in events


def test_leaderboard_contains_me_with_a_rank(client, auth):
    _seed(client, auth)
    board = client.get("/api/v1/dashboard/leaderboard", headers=auth).json()
    me = next(e for e in board if e.get("me"))
    assert me["name"] == "You" and me["rank"] >= 1 and me["xp"] == 105
    assert all(set(e) >= {"rank", "name", "xp"} for e in board)


def test_new_learner_gets_zeros_not_errors(client, auth):
    for path in ("stats", "metrics", "radar", "streak", "topics", "leaderboard", "recent-activity", "events"):
        res = client.get(f"/api/v1/dashboard/{path}", headers=auth)
        assert res.status_code == 200, path
    assert client.get("/api/v1/dashboard/stats", headers=auth).json() == {"accuracy": 0, "questions": 0, "percentile": 0, "speed": 0}
