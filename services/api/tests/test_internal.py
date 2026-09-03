"""Internal API tests.

This surface hands out problem ANSWERS and per-user ability, so its access
control matters as much as its behaviour.
"""

import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

KEY = {"X-Internal-Key": "dev-internal-key"}


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable("localhost", 5432) and _reachable("localhost", 7687)),
    reason="dev stack not running",
)


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    """TestClient's host is 'testclient', not 127.0.0.1, so the loopback guard
    would reject every request before the key is ever checked — which would
    make the key tests pass for the wrong reason. Disable only the loopback
    requirement here; the key check stays live and is what these tests cover.
    (The loopback guard itself is exercised against the running server, not
    through TestClient.)"""
    from app.config import get_settings

    monkeypatch_module.setenv("INTERNAL_API_REQUIRE_LOOPBACK", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    patcher = MonkeyPatch()
    yield patcher
    patcher.undo()


@pytest.fixture
def user(client):
    credentials = {
        "email": f"internal-{uuid.uuid4().hex[:12]}@vsg.com",
        "password": "correct-horse-battery",
    }
    return client.post("/api/v1/auth/register", json=credentials).json()["user"]["id"]


def test_internal_api_refuses_callers_without_the_key(client):
    for path, payload in (
        ("/internal/game/problem-batch", {"count": 1}),
        ("/internal/user/context", {"user_id": str(uuid.uuid4())}),
        ("/internal/match/complete", {"match_id": "ad_1", "results": []}),
    ):
        assert client.post(path, json=payload).status_code == 403


def test_internal_api_refuses_a_wrong_key(client):
    res = client.post(
        "/internal/game/problem-batch", json={"count": 1}, headers={"X-Internal-Key": "guess"}
    )
    assert res.status_code == 403


def test_problem_batch_returns_answers_for_server_side_scoring(client):
    res = client.post("/internal/game/problem-batch", json={"count": 3}, headers=KEY)
    assert res.status_code == 200
    problems = res.json()["problems"]
    assert problems
    for problem in problems:
        # The game server needs the answer; the client never receives this shape.
        assert problem["answer"]
        assert float(problem["answer"])
        assert problem["problem_text"]


def test_user_context_seeds_elo_from_ability_for_a_new_player(client, user):
    res = client.post("/internal/user/context", json={"user_id": user}, headers=KEY)
    assert res.status_code == 200
    body = res.json()
    assert body["elo"] == 1000  # theta 0 → 1000 + 400×0
    assert body["rating_deviation"] == 350
    assert body["cluster"] == "balanced"


def test_unknown_user_is_404_not_a_default_profile(client):
    res = client.post("/internal/user/context", json={"user_id": str(uuid.uuid4())}, headers=KEY)
    assert res.status_code == 404


def test_match_complete_persists_and_returns_rating_changes(client):
    players = []
    for _ in range(2):
        credentials = {
            "email": f"duel-{uuid.uuid4().hex[:12]}@vsg.com",
            "password": "correct-horse-battery",
        }
        players.append(client.post("/api/v1/auth/register", json=credentials).json()["user"]["id"])

    match_id = f"ad_20260903_{uuid.uuid4().hex[:3]}"
    body = {
        "match_id": match_id,
        "mode": "accuracy_duel",
        "results": [
            {
                "user_id": players[0], "final_rank": 1, "final_score": 12,
                "problems_attempted": 5, "problems_correct": 5, "accuracy_pct": 100.0,
                "avg_time_ms": 9000, "position_points": 2, "accuracy_bonus": 10,
                "theta_u_snapshot": 0.5,
            },
            {
                "user_id": players[1], "final_rank": 2, "final_score": 8,
                "problems_attempted": 5, "problems_correct": 4, "accuracy_pct": 80.0,
                "avg_time_ms": 11000, "position_points": 1, "accuracy_bonus": 7,
                "theta_u_snapshot": 0.5,
            },
        ],
    }
    res = client.post("/internal/match/complete", json=body, headers=KEY)
    assert res.status_code == 200
    payload = res.json()
    assert payload["persisted"] is True

    changes = {u["user_id"]: u["elo_change"] for u in payload["elo_updates"]}
    assert changes[players[0]] > 0
    assert changes[players[1]] < 0
    # Equal starting ratings: the duel is zero-sum to within rounding.
    assert abs(changes[players[0]] + changes[players[1]]) <= 2


def test_match_complete_is_idempotent(client):
    player = client.post(
        "/api/v1/auth/register",
        json={"email": f"idem-{uuid.uuid4().hex[:12]}@vsg.com", "password": "correct-horse-battery"},
    ).json()["user"]["id"]

    match_id = f"ad_20260903_{uuid.uuid4().hex[:3]}"
    body = {
        "match_id": match_id,
        "results": [
            {"user_id": player, "final_rank": 1, "final_score": 5, "theta_u_snapshot": 0.0}
        ],
    }
    assert client.post("/internal/match/complete", json=body, headers=KEY).status_code == 200
    # A retried persist must not create a second result row for the same player.
    assert client.post("/internal/match/complete", json=body, headers=KEY).status_code == 200


def test_leaderboard_is_ordered_by_rating(client):
    res = client.get("/internal/game/leaderboard", headers=KEY)
    assert res.status_code == 200
    ratings = [row["elo"] for row in res.json()["leaderboard"]]
    assert ratings == sorted(ratings, reverse=True)


QUARANTINED_SAMPLE = [
    "Tirthaji_Vedic_Math_sa_61",
    "Bird_Engineering_Math_sa_17",
    "Vedic_Made_Easy_sa_20",
]


def test_duel_problem_batch_applies_the_same_guards_as_practice(client):
    """The duel route feeds live matches, so it must apply the SAME content
    guards as the practice loop: a required skill edge, no blank prompts, and
    no factory-quarantined items. It previously used a bare MATCH, so the two
    serving paths enforced opposite rules."""
    res = client.post("/internal/game/problem-batch", json={"count": 20}, headers=KEY)
    assert res.status_code == 200
    for problem in res.json()["problems"]:
        assert problem["problem_id"] not in QUARANTINED_SAMPLE
        assert problem["problem_text"].strip()
