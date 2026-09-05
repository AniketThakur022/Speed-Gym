"""Dashboard reads — the frozen APK contract `GET /api/v1/dashboard/*`
(api-contract-v1). The recovered client only ever had mocks for these; this
is the first real implementation. Shapes mirror `apps/web/src/lib/types/dashboard.ts`.

Data sources: attempts come from the raw event ledger (`raw_events`
`problem_attempt` / `session_end` — see docs/backend/TELEMETRY.md for the
metadata contract), mastery from the latest BKT snapshot, XP/streaks from the
social tables. Everything degrades to zeros for a brand-new learner.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from .. import db
from ..security import get_current_user
from ..social import xp as xp_mod
from ..social.guard import leaderboard_mode
from ..social.policy import is_kid

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

WINDOW_DAYS = 30


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 2)


async def _attempts(conn, user_id: str, domain: Optional[str], days: Optional[int]) -> list[tuple]:
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000) if days else 0
    sql = """SELECT (metadata->>'is_correct')::boolean,
                    COALESCE((metadata->>'time_ms')::numeric, (metadata->>'total_time_ms')::numeric),
                    client_timestamp
             FROM raw_events
             WHERE user_id = %s::uuid AND event_type = 'problem_attempt' AND client_timestamp >= %s"""
    params: list[Any] = [user_id, since]
    if domain:
        sql += " AND metadata->>'domain' = %s"
        params.append(domain)
    return await (await conn.execute(sql, params)).fetchall()


async def _sessions(conn, user_id: str, domain: Optional[str], limit: int = 5) -> list[tuple]:
    sql = """SELECT metadata, client_timestamp FROM raw_events
             WHERE user_id = %s::uuid AND event_type = 'session_end'"""
    params: list[Any] = [user_id]
    if domain:
        sql += " AND metadata->>'domain' = %s"
        params.append(domain)
    sql += " ORDER BY client_timestamp DESC LIMIT %s"
    params.append(limit)
    return await (await conn.execute(sql, params)).fetchall()


async def _profile(conn, user_id: str) -> tuple[Optional[int], str]:
    row = await (
        await conn.execute("SELECT age, account_type FROM users WHERE id = %s::uuid", (user_id,))
    ).fetchone()
    return (row[0], row[1]) if row else (None, "standard")


def _relative(ts_ms: int) -> str:
    delta = datetime.now(timezone.utc) - datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    s = int(delta.total_seconds())
    if s < 60:
        return "Just now"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 2 * 86400:
        return "Yesterday"
    return f"{s // 86400}d ago"


@router.get("/topics")
async def topics(domain: Optional[str] = Query(default=None), user: dict = Depends(get_current_user)) -> list[dict]:
    """Mastery per skill from the latest BKT snapshot (client-side BKT is the
    source of truth; the snapshot is its ledger). `domain` is accepted for the
    contract; skills are not domain-tagged in the snapshot, so it is a no-op."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT technique_states FROM bkt_state_snapshots
                   WHERE user_id = %s::uuid ORDER BY created_at DESC LIMIT 1""",
                (user["id"],),
            )
        ).fetchone()
    states = row[0] if row and isinstance(row[0], dict) else {}
    items = []
    for skill, st in states.items():
        p = (st or {}).get("pLearned") if isinstance(st, dict) else None
        if p is None:
            continue
        items.append({"name": skill, "value": int(round(float(p) * 100)), "color": "primary"})
    items.sort(key=lambda t: -t["value"])
    return items[:8]


@router.get("/radar")
async def radar(user: dict = Depends(get_current_user)) -> list[dict]:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await _attempts(conn, user["id"], None, WINDOW_DAYS)
        sessions = await _sessions(conn, user["id"], None, 20)
        async with conn.cursor() as cur:
            streak = await xp_mod.streak_state(cur, user["id"], date.today())
    times = [float(r[1]) for r in rows if r[1] is not None and float(r[1]) > 0]
    total = len(rows)
    correct = sum(1 for r in rows if r[0])
    accuracy = correct / total if total else 0.0
    median = statistics.median(times) if times else 0.0
    p25 = sorted(times)[len(times) // 4] if times else 0.0
    focus = (sum(1 for t in times if t <= 1.5 * median) / len(times)) if times else 0.0
    per_session = [int((s[0] or {}).get("problems_attempted") or 0) for s in sessions]
    stamina = (sum(per_session) / len(per_session) / 25) if per_session else 0.0
    return [
        {"label": "Speed", "value": _clamp(1 - median / 60_000) if median else 0.0},
        {"label": "Logic", "value": _clamp(accuracy)},
        {"label": "Stamina", "value": _clamp(stamina)},
        {"label": "Focus", "value": _clamp(focus)},
        {"label": "Memory", "value": _clamp(streak["longest"] / 7)},
        {"label": "Reflex", "value": _clamp(1 - p25 / 20_000) if p25 else 0.0},
    ]


@router.get("/metrics")
async def metrics(user: dict = Depends(get_current_user)) -> list[dict]:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await _attempts(conn, user["id"], None, WINDOW_DAYS)
    times = [float(r[1]) for r in rows if r[1] is not None and float(r[1]) > 0]
    median = statistics.median(times) if times else 0.0
    total = len(rows)
    accuracy = (sum(1 for r in rows if r[0]) / total) if total else 0.0
    return [
        {"label": "Action Delay", "value": f"{int(median)}ms", "icon": "Zap"},
        {"label": "Focus Density", "value": f"{int(round(accuracy * 100))}%", "icon": "TrendingUp"},
    ]


@router.get("/stats")
async def stats(domain: Optional[str] = Query(default=None), user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await _attempts(conn, user["id"], domain, None)
        async with conn.cursor() as cur:
            _top, me, total_users = await xp_mod.leaderboard(cur, user["id"], 1)
    total = len(rows)
    correct = sum(1 for r in rows if r[0])
    times = [float(r[1]) for r in rows if r[1] is not None and float(r[1]) > 0]
    return {
        "accuracy": int(round(100 * correct / total)) if total else 0,
        "questions": total,
        "percentile": xp_mod.percentile(me["rank"] if me else None, total_users),
        "speed": int(round(sum(times) / len(times) / 1000)) if times else 0,
    }


@router.get("/streak")
async def streak(user: dict = Depends(get_current_user)) -> dict:
    today = date.today()
    pool = await db.get_pg()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            st = await xp_mod.streak_state(cur, user["id"], today)
            days = await xp_mod.week_days(cur, user["id"], today)
            total = await xp_mod.total_xp(cur, user["id"])
    return {"current": st["current"], "xp": total, "days": days, "labels": ["M", "T", "W", "T", "F", "S", "S"]}


@router.get("/events")
async def events(domain: Optional[str] = Query(default=None), user: dict = Depends(get_current_user)) -> list[dict]:
    """Upcoming: the daily challenge (until submitted) and pending friend requests."""
    today = date.today()
    pool = await db.get_pg()
    out: list[dict] = []
    async with pool.connection() as conn:
        done = await (
            await conn.execute(
                "SELECT 1 FROM daily_challenge_attempts WHERE user_id = %s::uuid AND challenge_date = %s",
                (user["id"], today),
            )
        ).fetchone()
        if not done:
            out.append({"title": "Daily Challenge", "time": "Today", "tag": "LIVE"})
        pending = await (
            await conn.execute(
                "SELECT COUNT(*) FROM friendships WHERE addressee_id = %s::uuid AND status = 'pending'",
                (user["id"],),
            )
        ).fetchone()
        if pending and pending[0]:
            n = int(pending[0])
            out.append({"title": f"{n} friend request{'s' if n > 1 else ''}", "time": "Now", "tag": "GROUP"})
    return out


@router.get("/leaderboard")
async def leaderboard(user: dict = Depends(get_current_user)) -> list[dict]:
    """XP leaderboard, top 10 + you, behind the anxiety guard: hidden → [],
    percentile-only (fragile state, kids) → just your row with a percentile."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        age, _ = await _profile(conn, user["id"])
        mode, _reason = await leaderboard_mode(conn, user["id"], is_kid(age))
        if mode == "hidden":
            return []
        async with conn.cursor() as cur:
            top, me, total = await xp_mod.leaderboard(cur, user["id"], 10)
    pct = xp_mod.percentile(me["rank"] if me else None, total)
    if mode == "percentile_only":
        return [{"rank": me["rank"] if me else 0, "name": "You", "xp": me["xp"] if me else 0, "me": True, "percentile": pct}]
    out = []
    seen_me = False
    for row in top:
        mine = row["user_id"] == user["id"]
        seen_me = seen_me or mine
        out.append({"rank": row["rank"], "name": "You" if mine else (row["name"] or "Learner"), "xp": row["xp"], **({"me": True} if mine else {})})
    if me and not seen_me:
        out.append({"rank": me["rank"], "name": "You", "xp": me["xp"], "me": True, "percentile": pct})
    return out


@router.get("/recent-activity")
async def recent_activity(domain: Optional[str] = Query(default=None), user: dict = Depends(get_current_user)) -> list[dict]:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await _sessions(conn, user["id"], domain, 5)
    out = []
    for meta, ts in rows:
        meta = meta or {}
        kind = str(meta.get("session_type") or "Practice").replace("_", " ").title()
        attempted = int(meta.get("problems_attempted") or 0)
        correct = int(meta.get("problems_correct") or 0)
        out.append({"label": f"{kind} session", "score": f"{correct}/{attempted}", "time": _relative(int(ts))})
    return out
