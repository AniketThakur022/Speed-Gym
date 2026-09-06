"""Regressions for the 16 findings confirmed by the blocks 5–9 adversarial
review (2026-09-06). One test per defect, named for the defect."""

import hashlib
import hmac
import json
import socket
import subprocess
import time
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.chat.hints import ProblemContext, answer_forms, redact, segment_steps, usable_steps
from app.content import extract_numeric_answer, format_answer
from app.main import create_app


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


DSN = "postgresql://vmsg:vmsg@localhost:5432/vmsg"
needs_pg = pytest.mark.skipif(not _reachable("localhost", 5432), reason="dev Postgres not running")


# ── #4 stored answers must round-trip (was "%g" → 9.99e+07) ─────────────────


@pytest.mark.parametrize("value", [99900024.0, 99900021.0, 1e6, 12345678.9, 0.4, -2556.0, 1234567890123.0])
def test_format_answer_round_trips_through_the_grader(value):
    stored = format_answer(value)
    assert "e" not in stored.lower(), stored
    assert extract_numeric_answer(stored) == pytest.approx(value)


def test_large_distinct_answers_do_not_collapse_onto_one_string():
    # The two real graph problems the review found colliding on "9.99e+07".
    assert format_answer(99900024.0) != format_answer(99900021.0)


# ── #7 an unparseable answer key must still redact the answer ───────────────


def test_multi_part_answer_key_redacts_its_numbers():
    forms = answer_forms("a = 12 and b = 0.4")     # real key, extract → None
    assert redact("so b = 0.4 exactly", forms)[1] is True
    assert redact("that gives a = 12", forms)[1] is True


def test_answer_key_with_currency_or_units_redacts():
    assert redact("total is 2556", answer_forms("£2,556"))[1] is True
    assert redact("total is 2,556", answer_forms("£2,556"))[1] is True
    assert redact("the volume is 117.5", answer_forms("volume, V = 117.5 cm³"))[1] is True


def test_redaction_does_not_swallow_ordinary_small_numbers():
    forms = answer_forms("144")
    assert redact("step 1 of 2", forms)[1] is False
    assert redact("the answer is 144", forms)[1] is True
    # 0/1 inside a multi-part key are too common to redact
    assert redact("start at step 1", answer_forms("a = 1 and b = 250"))[1] is False


# ── #8 page-level steps concatenate several worked examples ────────────────


def test_every_examples_final_step_is_withheld_not_just_the_last():
    steps = ["Sum positives: 27+81=108", "Sum negatives: -74-19=-93",
             "Taking the negatives from the positives: 108 - 93 = 15",
             "Next: line up the digits", "Add the columns", "Result is 42"]
    numbers = [1, 2, 3, 1, 2, 3]
    assert [len(s) for s in segment_steps(steps, numbers)] == [3, 3]
    ctx = ProblemContext(template_id="t", question_text="Add 27, -74, 81 and -19",
                         steps=steps, step_numbers=numbers, answer_key="15")
    kept = usable_steps(ctx)
    assert all("15" not in s for s in kept)
    assert "Result is 42" not in kept          # each segment's last step goes
    assert "Sum positives: 27+81=108" in kept  # genuine working survives


def test_single_example_steps_still_drop_only_the_final_step():
    ctx = ProblemContext(template_id="t", question_text="q", steps=["one", "two", "three"],
                         step_numbers=[1, 2, 3], answer_key="99")
    assert usable_steps(ctx) == ["one", "two"]


# ── #13 a backup must never be written where the nightly commit would push it ─


def test_backup_script_refuses_a_destination_the_nightly_commit_would_push():
    """An in-repo destination that git does NOT ignore must abort before the
    dump is written — tools/daily_commit.sh runs `git add -A` and pushes."""
    res = subprocess.run(
        ["bash", "scripts/backup.sh"],
        cwd="../..", env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "BACKUP_DIR": "./docs/_backup_probe"},
        capture_output=True, text=True, timeout=120,
    )
    try:
        assert res.returncode == 1
        assert "REFUSING" in res.stderr and "gitignored" in res.stderr
    finally:
        subprocess.run(["rm", "-rf", "docs/_backup_probe"], cwd="../..")


def test_backups_are_gitignored_as_defence_in_depth():
    res = subprocess.run(["git", "check-ignore", "backups/x/vmsg.pgdump"], cwd="../..",
                         capture_output=True, text=True)
    assert res.returncode == 0, "backups/ must be gitignored"


# ── #14 prod compose must not fall back to the committed dev secret ─────────


def test_prod_compose_requires_secrets_from_env():
    text = open("../../docker-compose.prod.yml").read()
    for key in ("JWT_SECRET", "OFFLINE_TOKEN_SECRET", "INTERNAL_API_KEY",
                "POSTGRES_PASSWORD", "NEO4J_PASSWORD"):
        assert f"${{{key}:?" in text, f"{key} must be a required interpolation in the prod override"
    # ...and no dev literal survives outside the explanatory comment.
    directives = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("dev-only-change-me" in ln for ln in directives)
    assert not any("NEO4J_AUTH: neo4j/vmsg-dev-password" in ln for ln in directives)


# ── #15/#16 hardening middleware ────────────────────────────────────────────


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    p = MonkeyPatch()
    yield p
    p.undo()


@pytest.fixture(scope="module")
def limited(monkeypatch_module):
    from app.config import get_settings

    monkeypatch_module.setenv("RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch_module.setenv("TRUSTED_PROXIES", "")
    get_settings.cache_clear()
    # Shared "ip:testclient" bucket — see test_hardening._reset_rate_limit_buckets.
    try:
        import redis as _redis

        r = _redis.Redis.from_url("redis://localhost:6379/0")
        for key in r.scan_iter("ratelimit:*"):
            r.delete(key)
    except Exception:  # noqa: BLE001
        pass
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.mark.skipif(not _reachable("localhost", 6379), reason="dev Redis not running")
def test_rotating_x_forwarded_for_cannot_escape_the_rate_limit(limited):
    """Was: a fresh XFF per request gave every request its own bucket."""
    codes = [
        limited.get("/api/v1/billing/plans", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
        for i in range(12)
    ]
    assert 429 in codes, "unverified X-Forwarded-For must not create new buckets"


@pytest.mark.skipif(not _reachable("localhost", 6379), reason="dev Redis not running")
def test_rate_limited_and_oversized_responses_still_carry_cors(limited):
    origin = {"Origin": "https://examarena.com"}
    for _ in range(8):
        res = limited.get("/api/v1/billing/plans", headers=origin)
    assert res.status_code == 429
    assert res.headers.get("access-control-allow-origin") == "https://examarena.com"
    big = "x" * (1024 * 1024 + 10)
    res = limited.post("/api/v1/auth/login", content=big,
                       headers={**origin, "Content-Type": "application/json", "Content-Length": str(len(big))})
    assert res.status_code == 413
    assert res.headers.get("access-control-allow-origin") == "https://examarena.com"


def test_rate_limit_headers_are_exposed_to_browsers(limited):
    res = limited.get("/health", headers={"Origin": "https://examarena.com"})
    exposed = res.headers.get("access-control-expose-headers", "")
    assert "X-RateLimit-Remaining" in exposed and "Retry-After" in exposed


# ── behavioural regressions (need the dev Postgres) ─────────────────────────

INTERNAL = {"X-Internal-Key": "dev-internal-key"}


@pytest.fixture(scope="module")
def api(monkeypatch_module):
    from app.config import get_settings

    monkeypatch_module.setenv("INTERNAL_API_REQUIRE_LOOPBACK", "false")
    monkeypatch_module.setenv("RATE_LIMIT_PER_MINUTE", "0")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def _user(api, age=25):
    import psycopg

    creds = {"email": f"rev-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery"}
    tok = api.post("/api/v1/auth/register", json=creds).json()
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE users SET age = %s WHERE id = %s::uuid", (age, tok["user"]["id"]))
        conn.commit()
    return {"Authorization": f"Bearer {tok['token']}"}, tok["user"]["id"]


def _flag(name, enabled):
    import asyncio

    import psycopg

    from app import flags as flags_service

    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE feature_flags SET enabled = %s, rollout_pct = 100 WHERE flag_name = %s", (enabled, name))
        conn.commit()
    asyncio.run(flags_service.invalidate())


def _match(api, me, opponent_id=None, bot=False):
    mid = f"ad_20260906_{uuid.uuid4().hex[:6]}"
    body = {"match_id": mid, "mode": "accuracy_duel", "duration_ms": 90_000, "results": [
        {"user_id": me, "is_bot": False, "final_rank": 1, "final_score": 12, "problems_attempted": 6,
         "problems_correct": 6, "accuracy_pct": 100, "avg_time_ms": 4000, "theta_u_snapshot": 0.5},
        {"user_id": opponent_id or "bot-x", "is_bot": bot, "final_rank": 2, "final_score": 5,
         "problems_attempted": 6, "problems_correct": 1, "accuracy_pct": 16.7, "avg_time_ms": 3000,
         "theta_u_snapshot": 0.4},
    ]}
    assert api.post("/internal/match/complete", json=body, headers=INTERNAL).status_code == 200
    return mid


@needs_pg
def test_clip_response_is_identical_for_a_bot_and_a_human_opponent(api):
    """Was: a bot match returned ready/opponent_consent=true, a human match
    pending/false — a reliable bot oracle across the API boundary."""
    _flag("social_clips", True)
    try:
        owner, owner_id = _user(api)
        _, human_id = _user(api)
        human_match = _match(api, owner_id, opponent_id=human_id)
        bot_match = _match(api, owner_id, bot=True)

        h = api.post("/api/v1/social/clips", json={"match_id": human_match}, headers=owner).json()
        b = api.post("/api/v1/social/clips", json={"match_id": bot_match}, headers=owner).json()
        tell = lambda c: (c["status"], c["opponent_consent"], c["players"], c["payload"]["opponent"] is None)
        assert tell(h) == tell(b), f"bot oracle: {tell(h)} vs {tell(b)}"
        assert b["status"] == "pending" and b["opponent_consent"] is False
        # ...and opponent stats are present in both, so their absence cannot leak it either
        assert b["payload"]["opponent"] is not None
    finally:
        _flag("social_clips", False)


@needs_pg
def test_a_future_device_clock_cannot_freeze_the_streak(api):
    """Was: a client_timestamp in 2027 wrote a future last_activity_date, after
    which every real day looked like a backfill and the streak never moved."""
    import asyncio

    from app import db as app_db
    from app.social import xp as xp_mod

    _, uid = _user(api)
    future = date.today() + timedelta(days=200)

    async def run():
        pool = await app_db.get_pg()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                first = await xp_mod.record_activity_day(cur, uid, future, 3)
                second = await xp_mod.record_activity_day(cur, uid, date.today(), 3)
                state = await xp_mod.streak_state(cur, uid, date.today())
            await conn.commit()
        return first, second, state

    first, second, state = asyncio.run(run())
    assert first["current"] == 1                 # clamped to today, not banked in the future
    assert second["new_day"] is False            # same (clamped) day, so no double streak XP
    assert state["current"] == 1                 # and the streak is live, not frozen


@needs_pg
def test_stats_percentile_respects_the_hidden_anxiety_guard(api):
    """Was: /dashboard/leaderboard returned [] but the stat tile on the same
    screen still rendered the raw XP percentile."""
    import psycopg

    auth, uid = _user(api)
    api.post("/api/v1/sync", json={"events": [
        {"event_id": str(uuid.uuid4()), "event_type": "problem_attempt",
         "client_timestamp": int(time.time() * 1000), "metadata": {"is_correct": True, "time_ms": 2000}},
    ]}, headers=auth)
    with psycopg.connect(DSN) as conn:
        conn.execute(
            """INSERT INTO bkt_state_snapshots (user_id, technique_states, snapshot_reason)
               VALUES (%s::uuid, %s, 'session_end')""",
            (uid, json.dumps({"a": {"state": "fractured"}, "b": {"state": "fractured"}})),
        )
        conn.commit()
    assert api.get("/api/v1/dashboard/leaderboard", headers=auth).json() == []
    assert api.get("/api/v1/dashboard/stats", headers=auth).json()["percentile"] == 0


@needs_pg
def test_ungraded_server_checked_attempts_are_not_counted_wrong(api):
    """Was: is_correct NULL folded in as wrong, so a perfect session with
    server-checked items reported 70% accuracy."""
    auth, _ = _user(api)
    now = int(time.time() * 1000)
    events = [
        {"event_id": str(uuid.uuid4()), "event_type": "problem_attempt", "client_timestamp": now,
         "metadata": {"is_correct": True, "time_ms": 3000}} for _ in range(7)
    ] + [
        {"event_id": str(uuid.uuid4()), "event_type": "problem_attempt", "client_timestamp": now,
         "metadata": {"is_correct": None, "time_ms": 3000, "answer_check": "server_sympy",
                      "submitted_answer": "144"}} for _ in range(3)
    ]
    api.post("/api/v1/sync", json={"events": events}, headers=auth)
    stats = api.get("/api/v1/dashboard/stats", headers=auth).json()
    assert stats["questions"] == 10          # all ten were attempted
    assert stats["accuracy"] == 100          # ...but only seven were graded


# ── #5 the mock pool must honour the whole trust ladder, not just quarantine ─


@needs_pg
def test_sandbox_content_is_excluded_from_mock_pools(monkeypatch):
    """`content.servable_trust` and `session.py` both promise SANDBOX content
    "never feeds BKT or mock exams"; the mock source read only the quarantine
    rung, so a stage-7 SANDBOX verdict had no effect here."""
    import asyncio

    from app import db as app_db
    from app.mocks import sources as sources_mod
    from app.mocks.blueprints import BLUEPRINTS

    rows = [
        {"problem_id": "trusted_1", "text": "Compute 2+2", "answer_key": "4", "difficulty": 1, "skill": "arith"},
        {"problem_id": "sandbox_1", "text": "Compute 3+3", "answer_key": "6", "difficulty": 1, "skill": "arith"},
    ]

    class _Result:
        def __aiter__(self):
            async def gen():
                for r in rows:
                    yield r
            return gen()

    class _Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def run(self, *a, **k): return _Result()

    class _Driver:
        def session(self): return _Session()

    monkeypatch.setattr(app_db, "get_neo4j", lambda: _Driver())
    monkeypatch.setattr(sources_mod, "get_neo4j", lambda: _Driver(), raising=False)
    monkeypatch.setattr(sources_mod, "quarantined_ids", lambda pool: _async(set()))
    monkeypatch.setattr(sources_mod, "trust_levels", lambda pool: _async({"sandbox_1": "SANDBOX", "trusted_1": "LIVE"}))

    section = next(s for s in BLUEPRINTS["cat"].sections if s.key == "qa")
    got = asyncio.run(sources_mod.GraphSource().fetch(section, 10, "seed"))
    ids = {q["question_id"] for q in got}
    assert "trusted_1" in ids
    assert "sandbox_1" not in ids, "SANDBOX content must never be scored in a mock"


async def _async(value):
    return value
