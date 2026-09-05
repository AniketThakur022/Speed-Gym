"""Social surface against Postgres + Redis (+ Neo4j for the daily challenge).
Kids-mode restrictions are asserted through the real routes."""

import asyncio
import socket
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import flags as flags_service
from app.main import create_app

DSN = "postgresql://vmsg:vmsg@localhost:5432/vmsg"


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_reachable("localhost", 5432) and _reachable("localhost", 6379)), reason="dev Postgres/Redis not running"
)
needs_graph = pytest.mark.skipif(not _reachable("localhost", 7687), reason="dev Neo4j not running")


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    p = MonkeyPatch()
    yield p
    p.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    from app.config import get_settings

    monkeypatch_module.setenv("INTERNAL_API_REQUIRE_LOOPBACK", "false")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


INTERNAL = {"X-Internal-Key": "dev-internal-key"}


def _register(client, age=None, name=None):
    creds = {"email": f"soc-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery",
             "display_name": name or f"Learner {uuid.uuid4().hex[:4]}"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    uid = tokens["user"]["id"]
    if age is not None:
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE users SET age = %s WHERE id = %s::uuid", (age, uid))
            conn.commit()
    return {"Authorization": f"Bearer {tokens['token']}"}, uid, creds


def _set_flag(name, enabled):
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE feature_flags SET enabled = %s, rollout_pct = 100 WHERE flag_name = %s", (enabled, name))
        conn.commit()
    asyncio.run(flags_service.invalidate())


# ── policy ───────────────────────────────────────────────────────────────────


def test_policy_for_adult_and_kid(client):
    auth, _, _ = _register(client, age=25)
    p = client.get("/api/v1/social/policy", headers=auth).json()
    assert p["kids_mode"] is False and p["bots_enabled"] and p["taunts_enabled"]
    kid_auth, _, _ = _register(client, age=11)
    k = client.get("/api/v1/social/policy", headers=kid_auth).json()
    assert k["kids_mode"] and not k["ads_enabled"] and not k["bots_enabled"] and k["session_cap_minutes"] == 10


def test_internal_user_context_carries_the_kids_verdict(client):
    _, kid, _ = _register(client, age=9)
    _, adult, _ = _register(client, age=30)
    k = client.post("/internal/user/context", json={"user_id": kid}, headers=INTERNAL).json()
    a = client.post("/internal/user/context", json={"user_id": adult}, headers=INTERNAL).json()
    assert k["kids_mode"] is True and k["bots_allowed"] is False and k["age_group"] == 9
    assert a["kids_mode"] is False and a["bots_allowed"] is True
    _, unknown, _ = _register(client)
    u = client.post("/internal/user/context", json={"user_id": unknown}, headers=INTERNAL).json()
    assert u["age_group"] is None and u["bots_allowed"] is False


# ── friends ──────────────────────────────────────────────────────────────────


def test_friend_request_accept_and_remove(client):
    a_auth, a_id, _ = _register(client, age=20, name="Alice")
    b_auth, b_id, b_creds = _register(client, age=21, name="Bob")
    req = client.post("/api/v1/social/friends/request", json={"email": b_creds["email"]}, headers=a_auth)
    assert req.status_code == 200, req.text
    fid = req.json()["friendship_id"]
    assert client.post("/api/v1/social/friends/request", json={"email": b_creds["email"]}, headers=a_auth).status_code == 409

    inbox = client.get("/api/v1/social/friends", headers=b_auth).json()
    assert inbox["incoming"][0]["user_id"] == a_id and inbox["incoming"][0]["name"] == "Alice"
    # only the addressee can accept
    assert client.post("/api/v1/social/friends/respond", json={"friendship_id": fid, "action": "accept"}, headers=a_auth).status_code == 404
    acc = client.post("/api/v1/social/friends/respond", json={"friendship_id": fid, "action": "accept"}, headers=b_auth)
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    assert client.get("/api/v1/social/friends", headers=a_auth).json()["friends"][0]["user_id"] == b_id
    unlocked = client.get("/api/v1/social/achievements", headers=a_auth).json()
    assert next(x for x in unlocked["achievements"] if x["key"] == "first_friend")["unlocked_at"]

    assert client.post("/api/v1/social/friends/remove", json={"friendship_id": fid}, headers=b_auth).status_code == 200
    assert client.get("/api/v1/social/friends", headers=a_auth).json()["friends"] == []


def test_kids_cannot_friend_or_be_friended_directly(client):
    kid_auth, _, kid_creds = _register(client, age=10)
    adult_auth, _, adult_creds = _register(client, age=30)
    assert client.post("/api/v1/social/friends/request", json={"email": adult_creds["email"]}, headers=kid_auth).status_code == 403
    assert client.post("/api/v1/social/friends/request", json={"email": kid_creds["email"]}, headers=adult_auth).status_code == 403
    assert client.post("/api/v1/social/friends/qr/generate", headers=kid_auth).status_code == 403


def test_qr_pairing_is_one_time_and_signed(client):
    a_auth, a_id, _ = _register(client, age=20)
    b_auth, b_id, _ = _register(client, age=20)
    c_auth, _, _ = _register(client, age=20)
    code = client.post("/api/v1/social/friends/qr/generate", headers=a_auth).json()
    assert code["expiresIn"] == 300
    bad = client.post("/api/v1/social/friends/qr/redeem", json={"code": code["code"], "sig": "0" * 64}, headers=b_auth)
    assert bad.status_code == 400
    assert client.post("/api/v1/social/friends/qr/redeem", json=code, headers=a_auth).status_code == 400  # own code
    ok = client.post("/api/v1/social/friends/qr/redeem", json=code, headers=b_auth)
    assert ok.status_code == 200 and ok.json()["status"] == "accepted"
    assert client.post("/api/v1/social/friends/qr/redeem", json=code, headers=c_auth).status_code == 410  # used
    assert client.get("/api/v1/social/friends", headers=a_auth).json()["friends"][0]["user_id"] == b_id


def test_social_flags_dark_means_404(client):
    auth, _, _ = _register(client, age=20)
    _set_flag("social_friends", False)
    try:
        assert client.get("/api/v1/social/friends", headers=auth).status_code == 404
    finally:
        _set_flag("social_friends", True)
    assert client.get("/api/v1/social/friends", headers=auth).status_code == 200


# ── ghosts ───────────────────────────────────────────────────────────────────


def _ghost(client, auth, public=False, times=(4000, 5000, 6000), correct=(True, True, False)):
    return client.post("/api/v1/social/ghosts", json={
        "domain": "vedic-math", "skill": "nikhilam", "problem_ids": ["p1", "p2", "p3"],
        "answer_times_ms": list(times), "correct": list(correct), "is_public": public,
    }, headers=auth)


def test_ghost_record_visibility_and_race(client):
    owner_auth, owner_id, _ = _register(client, age=20, name="Owner")
    stranger_auth, _, _ = _register(client, age=20)
    private = _ghost(client, owner_auth).json()
    public = _ghost(client, owner_auth, public=True).json()
    seen = client.get("/api/v1/social/ghosts", headers=stranger_auth).json()["ghosts"]
    ids = {g["ghost_id"]: g for g in seen}
    assert public["ghost_id"] in ids and ids[public["ghost_id"]]["owner"] == "Anonymous"
    assert private["ghost_id"] not in ids
    assert client.post(f"/api/v1/social/ghosts/{private['ghost_id']}/race", json={"time_ms": 1000, "correct": 3}, headers=stranger_auth).status_code == 404

    race = client.post(f"/api/v1/social/ghosts/{public['ghost_id']}/race", json={"time_ms": 14000, "correct": 2}, headers=stranger_auth).json()
    assert race["won"] is True and race["xp_awarded"] == 30       # same correct, faster than 15000
    lost = client.post(f"/api/v1/social/ghosts/{public['ghost_id']}/race", json={"time_ms": 16000, "correct": 2}, headers=stranger_auth).json()
    assert lost["won"] is False and lost["xp_awarded"] == 0


def test_kids_ghosts_are_never_public(client):
    kid_auth, _, _ = _register(client, age=11)
    g = _ghost(client, kid_auth, public=True).json()
    assert g["is_public"] is False


def test_ghost_validation(client):
    auth, _, _ = _register(client, age=20)
    res = client.post("/api/v1/social/ghosts", json={"problem_ids": ["a", "b"], "answer_times_ms": [1], "correct": [True, False]}, headers=auth)
    assert res.status_code == 422


# ── match completion → XP, achievements, taunts ──────────────────────────────


def _complete_match(client, winner, loser, match_id=None, bot=False):
    match_id = match_id or f"ad_20260905_{uuid.uuid4().hex[:6]}"
    body = {
        "match_id": match_id, "mode": "accuracy_duel", "duration_ms": 90_000,
        "results": [
            {"user_id": winner, "is_bot": False, "final_rank": 1, "final_score": 12, "problems_attempted": 6,
             "problems_correct": 6, "accuracy_pct": 100, "avg_time_ms": 4000, "theta_u_snapshot": 0.5},
            {"user_id": loser if not bot else "bot-x", "is_bot": bot, "final_rank": 2, "final_score": 5,
             "problems_attempted": 6, "problems_correct": 1, "accuracy_pct": 16.7, "avg_time_ms": 3000, "theta_u_snapshot": 0.4},
        ],
    }
    res = client.post("/internal/match/complete", json=body, headers=INTERNAL)
    assert res.status_code == 200, res.text
    return match_id, res.json()


def test_match_complete_awards_xp_achievements_and_taunt(client):
    w_auth, w_id, _ = _register(client, age=22, name="Winner")
    l_auth, l_id, _ = _register(client, age=23, name="Loser")
    with psycopg.connect(DSN) as conn:   # sprinter → taunt every 3rd match; first match qualifies at 0 since_last? no: needs 2 prior
        conn.execute("INSERT INTO user_cognitive_profiles (user_id, behavioral_cluster) VALUES (%s::uuid, 'sprinter') ON CONFLICT (user_id) DO UPDATE SET behavioral_cluster = 'sprinter'", (l_id,))
        conn.commit()
    match_id, out = _complete_match(client, w_id, l_id)
    social = out["social"]
    assert social[w_id]["xp_awarded"] == 50 + 20 and "first_win" in social[w_id]["achievements_unlocked"]
    assert "perfect_game" in social[w_id]["achievements_unlocked"]
    assert social[l_id]["xp_awarded"] == 15 + 20
    assert social[l_id]["taunt"] is None and social[l_id]["taunt_suppressed"] == "frequency"
    # a resend of the same match pays nothing more
    _, again = _complete_match(client, w_id, l_id, match_id=match_id)
    assert again["social"][w_id]["xp_awarded"] == 0

    # 2nd match: still lost, still too early (every 3rd) — and a 3rd straight
    # loss would trip SOC-16 instead, so the sprinter WINS the 3rd match.
    _, out2 = _complete_match(client, w_id, l_id)
    assert out2["social"][l_id]["taunt_suppressed"] == "frequency"
    mid, out3 = _complete_match(client, l_id, w_id)
    taunt = out3["social"][l_id]["taunt"]
    assert taunt and taunt["id"] == "blowout_winner", out3["social"][l_id]
    assert client.get(f"/api/v1/social/taunts/{mid}", headers=l_auth).json()["taunt"]["id"] == "blowout_winner"
    assert "is_bot" not in str(out3["social"])


def test_three_straight_losses_silence_taunts(client):
    w_auth, w_id, _ = _register(client, age=22)
    _, l_id, _ = _register(client, age=23)
    with psycopg.connect(DSN) as conn:
        conn.execute("INSERT INTO user_cognitive_profiles (user_id, behavioral_cluster) VALUES (%s::uuid, 'sprinter') ON CONFLICT (user_id) DO UPDATE SET behavioral_cluster = 'sprinter'", (l_id,))
        conn.commit()
    for _ in range(3):
        _, out = _complete_match(client, w_id, l_id)
    assert out["social"][l_id]["taunt"] is None and out["social"][l_id]["taunt_suppressed"] == "loss_streak"


def test_bot_rounds_pay_half_xp_and_kids_never_get_taunts(client):
    _, kid_id, _ = _register(client, age=11)
    _, out = _complete_match(client, kid_id, "unused", bot=True)
    assert out["social"][kid_id]["xp_awarded"] == 25 + 20         # 0.5 × duel_win + streak day
    assert out["social"][kid_id]["taunt"] is None and out["social"][kid_id]["taunt_suppressed"] == "kids_mode"


def test_leaderboard_is_hidden_for_60s_after_a_match(client):
    w_auth, w_id, _ = _register(client, age=22)
    _, l_id, _ = _register(client, age=22)
    _complete_match(client, w_id, l_id)
    assert client.get("/api/v1/dashboard/leaderboard", headers=w_auth).json() == []


def test_kids_see_percentile_only(client):
    kid_auth, _, _ = _register(client, age=12)
    client.post("/api/v1/sync", json={"events": [{"event_id": str(uuid.uuid4()), "event_type": "problem_attempt",
                "client_timestamp": int(time.time() * 1000), "metadata": {"is_correct": True, "time_ms": 3000}}]}, headers=kid_auth)
    board = client.get("/api/v1/dashboard/leaderboard", headers=kid_auth).json()
    assert len(board) == 1 and board[0]["me"] is True and "percentile" in board[0]


def test_kids_ui_telemetry_is_minimised_and_devices_stripped(client):
    kid_auth, kid_id, _ = _register(client, age=9)
    events = [
        {"event_id": str(uuid.uuid4()), "event_type": "page_view", "client_timestamp": int(time.time() * 1000), "metadata": {}},
        {"event_id": str(uuid.uuid4()), "event_type": "problem_attempt", "client_timestamp": int(time.time() * 1000),
         "metadata": {"is_correct": True, "time_ms": 2000, "device_fingerprint": "abc", "skill": "nikhilam"}},
    ]
    res = client.post("/api/v1/sync", json={"events": events, "device_id": "dev-1"}, headers=kid_auth).json()
    assert res["minimized"] == 1 and res["accepted"] == 1
    with psycopg.connect(DSN) as conn:
        row = conn.execute("SELECT metadata FROM raw_events WHERE event_id = %s", (events[1]["event_id"],)).fetchone()
    assert "device_fingerprint" not in row[0] and row[0]["skill"] == "nikhilam"


# ── clips (dark by default) ──────────────────────────────────────────────────


def test_clips_need_flag_dual_consent_and_anonymise(client):
    a_auth, a_id, _ = _register(client, age=20)
    b_auth, b_id, _ = _register(client, age=20)
    match_id, _ = _complete_match(client, a_id, b_id)
    assert client.post("/api/v1/social/clips", json={"match_id": match_id}, headers=a_auth).status_code == 404  # dark
    _set_flag("social_clips", True)
    try:
        clip = client.post("/api/v1/social/clips", json={"match_id": match_id}, headers=a_auth).json()
        assert clip["status"] == "pending" and clip["players"] == ["You", "Opponent"]
        cid = clip["clip_id"]
        stranger_auth, _, _ = _register(client, age=20)
        assert client.get(f"/api/v1/social/clips/{cid}", headers=stranger_auth).status_code == 404
        assert client.post(f"/api/v1/social/clips/{cid}/consent", headers=a_auth).status_code == 404
        ready = client.post(f"/api/v1/social/clips/{cid}/consent", headers=b_auth).json()
        assert ready["status"] == "ready" and ready["you_are"] == "opponent"
        assert client.get(f"/api/v1/social/clips/{cid}", headers=stranger_auth).json()["players"] == ["Player", "Opponent"]
        kid_auth, _, _ = _register(client, age=11)
        assert client.post("/api/v1/social/clips", json={"match_id": match_id}, headers=kid_auth).status_code == 403
    finally:
        _set_flag("social_clips", False)


# ── daily challenge ──────────────────────────────────────────────────────────


@needs_graph
def test_daily_challenge_get_submit_rank(client):
    a_auth, a_id, _ = _register(client, age=20)
    today = client.get("/api/v1/social/daily", headers=a_auth)
    assert today.status_code == 200, today.text
    body = today.json()
    assert len(body["problems"]) == 10 and all("answer" not in p for p in body["problems"])
    assert body["submitted"] is None
    with psycopg.connect(DSN) as conn:
        answers = conn.execute("SELECT answers FROM daily_challenges WHERE challenge_date = %s", (body["date"],)).fetchone()[0]
    submit = client.post("/api/v1/social/daily/submit", json={"answers": [str(a) for a in answers], "total_time_ms": 120_000}, headers=a_auth)
    assert submit.status_code == 200, submit.text
    s = submit.json()
    assert s["problems_correct"] == 10 and s["score"] == 1000 + 480 and s["rank"] >= 1
    assert s["xp_awarded"] >= 50 + 100
    assert client.post("/api/v1/social/daily/submit", json={"answers": ["1"] * 10, "total_time_ms": 5}, headers=a_auth).status_code == 409
    board = client.get("/api/v1/social/daily/leaderboard", headers=a_auth).json()
    assert board["me"]["rank"] == s["rank"] and any(e["name"] == "You" for e in board["entries"])
    assert client.get("/api/v1/social/daily", headers=a_auth).json()["submitted"]["score"] == s["score"]
