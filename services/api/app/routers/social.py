"""Social — `/api/v1/social/*` (architecture §9.2 Phase-1 basic social).

Friends + QR pairing, ghost recordings + async races, the daily challenge,
achievements, post-match taunts, shareable clips, and the per-user kids
policy. Every surface except `/policy` sits behind a feature flag; kids-mode
restrictions are NOT flags.
"""

from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .. import db
from ..content import quarantined_ids
from ..flags import require_flag
from ..security import get_current_user, qr_signature
from ..social import achievements as ach
from ..social import daily as daily_mod
from ..social import xp as xp_mod
from ..social.guard import leaderboard_mode
from ..social.policy import is_kid, kids_policy

router = APIRouter(prefix="/social", tags=["social"])

QR_TTL_SECONDS = 300
GHOST_MAX_PROBLEMS = 50


# ── helpers ──────────────────────────────────────────────────────────────────


async def _profile(conn, user_id: str) -> dict:
    row = await (
        await conn.execute(
            """SELECT u.age, u.account_type, u.taunts_enabled, fs.session_cap_minutes
               FROM users u LEFT JOIN family_seats fs ON fs.child_user_id = u.id
               WHERE u.id = %s::uuid""",
            (user_id,),
        )
    ).fetchone()
    age, account_type, taunts, cap = row if row else (None, "standard", True, None)
    return {"age": age, "account_type": account_type, "taunts_enabled": bool(taunts), "session_cap": cap}


async def _require_not_kid(conn, user_id: str, what: str) -> dict:
    p = await _profile(conn, user_id)
    if is_kid(p["age"]):
        raise HTTPException(status_code=403, detail=f"{what} is parent-managed in kids mode")
    return p


async def _friend_ids(conn, user_id: str) -> set[str]:
    rows = await (
        await conn.execute(
            """SELECT CASE WHEN requester_id = %s::uuid THEN addressee_id ELSE requester_id END
               FROM friendships WHERE status = 'accepted' AND (requester_id = %s::uuid OR addressee_id = %s::uuid)""",
            (user_id, user_id, user_id),
        )
    ).fetchall()
    return {str(r[0]) for r in rows}


async def _befriend(cur, a: str, b: str, source: str) -> dict:
    """Accepted friendship a<->b, idempotent. Returns {friendship_id, new}."""
    await cur.execute(
        """INSERT INTO friendships (requester_id, addressee_id, status, source, accepted_at)
           VALUES (%s::uuid, %s::uuid, 'accepted', %s, NOW())
           ON CONFLICT DO NOTHING RETURNING id""",
        (a, b, source),
    )
    row = await cur.fetchone()
    if row is None:
        await cur.execute(
            """UPDATE friendships SET status = 'accepted', accepted_at = COALESCE(accepted_at, NOW())
               WHERE LEAST(requester_id, addressee_id) = LEAST(%s::uuid, %s::uuid)
                 AND GREATEST(requester_id, addressee_id) = GREATEST(%s::uuid, %s::uuid)
                 AND status <> 'blocked' RETURNING id""",
            (a, b, a, b),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="cannot befriend: blocked")
        new = False
    else:
        new = True
    fid = str(row[0])
    for uid in (a, b):
        await xp_mod.award(cur, uid, "friend_added", fid)
        await ach.unlock(cur, uid, ["first_friend"])
    return {"friendship_id": fid, "new": new}


# ── policy ───────────────────────────────────────────────────────────────────


@router.get("/policy")
async def policy(user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        p = await _profile(conn, user["id"])
    out = kids_policy(p["age"], p["account_type"], p["session_cap"])
    out["taunts_enabled"] = out["taunts_enabled"] and p["taunts_enabled"]
    return out


# ── friends ──────────────────────────────────────────────────────────────────


class FriendRequest(BaseModel):
    email: EmailStr


class FriendRespond(BaseModel):
    friendship_id: str
    action: Literal["accept", "decline", "block"]


class FriendRemove(BaseModel):
    friendship_id: str


class QrRedeem(BaseModel):
    code: str = Field(min_length=8, max_length=64)
    sig: str


@router.get("/friends")
async def friends(user: dict = Depends(require_flag("social_friends"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT f.id, f.requester_id, f.addressee_id, f.status, f.source, f.accepted_at,
                          ru.display_name, au.display_name
                   FROM friendships f
                   JOIN users ru ON ru.id = f.requester_id JOIN users au ON au.id = f.addressee_id
                   WHERE (f.requester_id = %s::uuid OR f.addressee_id = %s::uuid) AND f.status <> 'blocked'
                   ORDER BY f.created_at DESC""",
                (user["id"], user["id"]),
            )
        ).fetchall()
    accepted, incoming, outgoing = [], [], []
    for fid, req, addr, status, source, acc, rname, aname in rows:
        mine_is_requester = str(req) == user["id"]
        other_id, other_name = (str(addr), aname) if mine_is_requester else (str(req), rname)
        entry = {"friendship_id": str(fid), "user_id": other_id, "name": other_name or "Learner", "source": source}
        if status == "accepted":
            accepted.append({**entry, "since": acc.isoformat() if acc else None})
        elif mine_is_requester:
            outgoing.append(entry)
        else:
            incoming.append(entry)
    return {"friends": accepted, "incoming": incoming, "outgoing": outgoing}


@router.post("/friends/request")
async def friend_request(body: FriendRequest, user: dict = Depends(require_flag("social_friends"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_not_kid(conn, user["id"], "friending")
        target = await (
            await conn.execute("SELECT id, age FROM users WHERE email = %s", (body.email.lower(),))
        ).fetchone()
        if target is None or str(target[0]) == user["id"]:
            raise HTTPException(status_code=404, detail="no such learner")
        if is_kid(target[1]):
            raise HTTPException(status_code=403, detail="that account is parent-managed")
        try:
            row = await (
                await conn.execute(
                    """INSERT INTO friendships (requester_id, addressee_id) VALUES (%s::uuid, %s::uuid)
                       RETURNING id""",
                    (user["id"], str(target[0])),
                )
            ).fetchone()
        except Exception:  # noqa: BLE001 — unique pair
            await conn.rollback()
            raise HTTPException(status_code=409, detail="a request or friendship already exists")
        await conn.commit()
    return {"friendship_id": str(row[0]), "status": "pending"}


@router.post("/friends/respond")
async def friend_respond(body: FriendRespond, user: dict = Depends(require_flag("social_friends"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_not_kid(conn, user["id"], "friending")
        row = await (
            await conn.execute(
                "SELECT requester_id, addressee_id, status FROM friendships WHERE id = %s::uuid",
                (body.friendship_id,),
            )
        ).fetchone()
        if row is None or str(row[1]) != user["id"] or row[2] != "pending":
            raise HTTPException(status_code=404, detail="no pending request with that id")
        async with conn.cursor() as cur:
            if body.action == "accept":
                await _befriend(cur, str(row[0]), user["id"], "request")
            elif body.action == "block":
                await cur.execute("UPDATE friendships SET status = 'blocked' WHERE id = %s::uuid", (body.friendship_id,))
            else:
                await cur.execute("DELETE FROM friendships WHERE id = %s::uuid", (body.friendship_id,))
        await conn.commit()
    return {"friendship_id": body.friendship_id, "status": {"accept": "accepted", "block": "blocked", "decline": "declined"}[body.action]}


@router.post("/friends/remove")
async def friend_remove(body: FriendRemove, user: dict = Depends(require_flag("social_friends"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        res = await conn.execute(
            """DELETE FROM friendships WHERE id = %s::uuid
               AND (requester_id = %s::uuid OR addressee_id = %s::uuid)""",
            (body.friendship_id, user["id"], user["id"]),
        )
        await conn.commit()
    if (res.rowcount or 0) == 0:
        raise HTTPException(status_code=404, detail="no such friendship")
    return {"friendship_id": body.friendship_id, "status": "removed"}


@router.post("/friends/qr/generate")
async def qr_generate(user: dict = Depends(require_flag("social_friends"))) -> dict:
    """Show this to a friend in person: 300-s TTL, one-time, HMAC-signed."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_not_kid(conn, user["id"], "QR pairing")
    code = secrets.token_urlsafe(16)
    await db.get_redis().set(f"friend:pair:{code}", user["id"], ex=QR_TTL_SECONDS)
    return {"code": code, "sig": qr_signature("friend:" + code), "expiresIn": QR_TTL_SECONDS}


@router.post("/friends/qr/redeem")
async def qr_redeem(body: QrRedeem, user: dict = Depends(require_flag("social_friends"))) -> dict:
    if body.sig != qr_signature("friend:" + body.code):
        raise HTTPException(status_code=400, detail="bad signature")
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_not_kid(conn, user["id"], "QR pairing")
        redis = db.get_redis()
        key = f"friend:pair:{body.code}"
        owner = await redis.get(key)
        if not owner:
            raise HTTPException(status_code=410, detail="code expired or already used")
        if owner == user["id"]:
            # Rejected WITHOUT consuming the code: scanning your own QR by
            # mistake must not burn it for the friend standing next to you.
            raise HTTPException(status_code=400, detail="that is your own code")
        if (await redis.delete(key)) == 0:
            raise HTTPException(status_code=410, detail="code expired or already used")
        async with conn.cursor() as cur:
            out = await _befriend(cur, owner, user["id"], "qr")
        await conn.commit()
    return {**out, "status": "accepted"}


# ── ghosts ───────────────────────────────────────────────────────────────────


class GhostCreate(BaseModel):
    domain: str = Field(default="vedic-math", max_length=20)
    skill: Optional[str] = Field(default=None, max_length=160)
    problem_ids: list[str] = Field(min_length=1, max_length=GHOST_MAX_PROBLEMS)
    answer_times_ms: list[int]
    correct: list[bool]
    trap_triggers: list[str] = Field(default_factory=list)
    is_public: bool = False


class GhostRace(BaseModel):
    time_ms: int = Field(ge=1)
    correct: int = Field(ge=0)


@router.post("/ghosts")
async def ghost_create(body: GhostCreate, user: dict = Depends(require_flag("social_ghosts"))) -> dict:
    n = len(body.problem_ids)
    if len(body.answer_times_ms) != n or len(body.correct) != n:
        raise HTTPException(status_code=422, detail="problem_ids, answer_times_ms and correct must align")
    if any(t <= 0 for t in body.answer_times_ms):
        raise HTTPException(status_code=422, detail="answer times must be positive")
    pool = await db.get_pg()
    async with pool.connection() as conn:
        p = await _profile(conn, user["id"])
        is_public = body.is_public and not is_kid(p["age"])   # kids' ghosts are never public
        row = await (
            await conn.execute(
                """INSERT INTO ghost_sessions
                       (user_id, domain, skill, problem_ids, answer_times_ms, correct, trap_triggers,
                        total_time_ms, problems_correct, is_public)
                   VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id, expires_at""",
                (
                    user["id"], body.domain, body.skill, json.dumps(body.problem_ids),
                    json.dumps(body.answer_times_ms), json.dumps(body.correct), json.dumps(body.trap_triggers),
                    sum(body.answer_times_ms), sum(1 for c in body.correct if c), is_public,
                ),
            )
        ).fetchone()
        await conn.commit()
    return {"ghost_id": str(row[0]), "is_public": is_public, "expires_at": row[1].isoformat()}


@router.get("/ghosts")
async def ghosts(user: dict = Depends(require_flag("social_ghosts"))) -> dict:
    """Mine, my friends' (named), and public ones (anonymous — a ghost records
    problems and times, never identity)."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        friend_ids = await _friend_ids(conn, user["id"])
        rows = await (
            await conn.execute(
                """SELECT g.id, g.user_id, g.domain, g.skill, jsonb_array_length(g.problem_ids),
                          g.total_time_ms, g.problems_correct, g.is_public, g.created_at, u.display_name
                   FROM ghost_sessions g JOIN users u ON u.id = g.user_id
                   WHERE g.expires_at > NOW()
                     AND (g.user_id = %s::uuid OR g.is_public OR g.user_id = ANY(%s::uuid[]))
                   ORDER BY g.created_at DESC LIMIT 50""",
                (user["id"], list(friend_ids)),
            )
        ).fetchall()
    out = []
    for gid, owner, domain, skill, n, total_ms, correct, public, created, name in rows:
        owner = str(owner)
        if owner == user["id"]:
            who = "You"
        elif owner in friend_ids:
            who = name or "Friend"
        else:
            who = "Anonymous"
        out.append({
            "ghost_id": str(gid), "owner": who, "domain": domain, "skill": skill, "problems": n,
            "total_time_ms": total_ms, "problems_correct": correct, "is_public": public,
            "created_at": created.isoformat(),
        })
    return {"ghosts": out}


@router.post("/ghosts/{ghost_id}/race")
async def ghost_race(ghost_id: str, body: GhostRace, user: dict = Depends(require_flag("social_ghosts"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        friend_ids = await _friend_ids(conn, user["id"])
        row = await (
            await conn.execute(
                """SELECT user_id, total_time_ms, problems_correct, is_public, problem_ids, answer_times_ms
                   FROM ghost_sessions WHERE id = %s::uuid AND expires_at > NOW()""",
                (ghost_id,),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no such ghost")
        owner = str(row[0])
        if not (owner == user["id"] or row[3] or owner in friend_ids):
            raise HTTPException(status_code=404, detail="no such ghost")
        won = body.correct > row[2] or (body.correct == row[2] and body.time_ms < row[1])
        race = await (
            await conn.execute(
                """INSERT INTO ghost_races (ghost_id, challenger_id, challenger_time_ms, challenger_correct, won)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s) RETURNING id""",
                (ghost_id, user["id"], body.time_ms, body.correct, won),
            )
        ).fetchone()
        xp = 0
        if won and owner != user["id"]:
            async with conn.cursor() as cur:
                xp = await xp_mod.award(cur, user["id"], "ghost_race_win", str(race[0]))
        await conn.commit()
    return {
        "race_id": str(race[0]), "won": won, "xp_awarded": xp,
        "ghost": {"total_time_ms": row[1], "problems_correct": row[2], "answer_times_ms": row[5]},
    }


# ── daily challenge ──────────────────────────────────────────────────────────


class DailySubmit(BaseModel):
    answers: list[Optional[str]] = Field(min_length=1, max_length=daily_mod.PROBLEMS_PER_DAY)
    total_time_ms: int = Field(ge=1)


async def _today(conn) -> dict:
    pool = await db.get_pg()
    try:
        challenge = await daily_mod.ensure_today(conn, db.get_neo4j(), await quarantined_ids(pool), xp_mod.utc_today())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"daily challenge unavailable: {type(exc).__name__}")
    if challenge is None:
        raise HTTPException(status_code=503, detail="no servable problems for today's challenge")
    return challenge


@router.get("/daily")
async def daily(user: dict = Depends(require_flag("daily_challenge"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        ch = await _today(conn)
        mine = await (
            await conn.execute(
                """SELECT problems_correct, problems_total, total_time_ms, score, submitted_at
                   FROM daily_challenge_attempts WHERE user_id = %s::uuid AND challenge_date = %s""",
                (user["id"], xp_mod.utc_today()),
            )
        ).fetchone()
    return {
        "date": ch["date"],
        "problems": ch["problems"],            # never the answers
        "submitted": None if mine is None else {
            "problems_correct": mine[0], "problems_total": mine[1], "total_time_ms": mine[2],
            "score": mine[3], "submitted_at": mine[4].isoformat(),
        },
    }


@router.post("/daily/submit")
async def daily_submit(body: DailySubmit, user: dict = Depends(require_flag("daily_challenge"))) -> dict:
    today = xp_mod.utc_today()
    pool = await db.get_pg()
    async with pool.connection() as conn:
        ch = await _today(conn)
        answers = ch["answers"]
        if len(body.answers) != len(answers):
            raise HTTPException(status_code=422, detail=f"expected {len(answers)} answers")
        correct = sum(1 for s, e in zip(body.answers, answers) if daily_mod.is_correct(s, float(e)))
        total = len(answers)
        sc = daily_mod.score(correct, total, body.total_time_ms)
        try:
            row = await (
                await conn.execute(
                    """INSERT INTO daily_challenge_attempts
                           (challenge_date, user_id, problems_correct, problems_total, total_time_ms, score)
                       VALUES (%s, %s::uuid, %s, %s, %s, %s) RETURNING id""",
                    (today, user["id"], correct, total, body.total_time_ms, sc),
                )
            ).fetchone()
        except Exception:  # noqa: BLE001 — one attempt per day
            await conn.rollback()
            raise HTTPException(status_code=409, detail="already submitted today")
        rank_row = await (
            await conn.execute(
                """SELECT rnk FROM (SELECT user_id, RANK() OVER (ORDER BY score DESC, submitted_at) rnk
                                    FROM daily_challenge_attempts WHERE challenge_date = %s) t
                   WHERE user_id = %s::uuid""",
                (today, user["id"]),
            )
        ).fetchone()
        rank = int(rank_row[0]) if rank_row else None
        async with conn.cursor() as cur:
            xp = await xp_mod.award(cur, user["id"], "daily_challenge_complete", today.isoformat())
            xp += await xp_mod.award(cur, user["id"], "daily_challenge_correct", today.isoformat(),
                                     xp_mod.XP_RULES["daily_challenge_correct"] * correct) if correct else 0
            day = await xp_mod.record_activity_day(cur, user["id"], today, total)
            if day["new_day"]:
                xp += await xp_mod.award(cur, user["id"], "streak_day", today.isoformat())
            fresh = await ach.unlock(cur, user["id"], ach.evaluate({"daily_rank": rank}))
        await conn.commit()
    return {
        "attempt_id": str(row[0]), "problems_correct": correct, "problems_total": total,
        "score": sc, "rank": rank, "xp_awarded": xp, "achievements_unlocked": fresh,
        "streak": {"current": day["current"], "longest": day["longest"]},
    }


@router.get("/daily/leaderboard")
async def daily_leaderboard(user: dict = Depends(require_flag("daily_challenge"))) -> dict:
    today = xp_mod.utc_today()
    pool = await db.get_pg()
    async with pool.connection() as conn:
        p = await _profile(conn, user["id"])
        mode, reason = await leaderboard_mode(conn, user["id"], is_kid(p["age"]))
        rows = await (
            await conn.execute(
                """SELECT a.user_id, u.display_name, a.score, a.problems_correct, a.total_time_ms,
                          RANK() OVER (ORDER BY a.score DESC, a.submitted_at) AS rnk, COUNT(*) OVER () AS total
                   FROM daily_challenge_attempts a JOIN users u ON u.id = a.user_id
                   WHERE a.challenge_date = %s ORDER BY rnk LIMIT 200""",
                (today,),
            )
        ).fetchall()
    total = int(rows[0][6]) if rows else 0
    me = next((r for r in rows if str(r[0]) == user["id"]), None)
    my_rank = int(me[5]) if me else None
    pct = xp_mod.percentile(my_rank, total)
    if mode == "hidden":
        return {"date": today.isoformat(), "mode": mode, "reason": reason, "entries": [], "me": None}
    mine = None if me is None else {"rank": my_rank, "score": me[2], "percentile": pct}
    if mode == "percentile_only":
        return {"date": today.isoformat(), "mode": mode, "reason": reason, "entries": [], "me": mine, "participants": total}
    entries = [
        {"rank": int(r[5]), "name": "You" if str(r[0]) == user["id"] else (r[1] or "Learner"),
         "score": r[2], "problems_correct": r[3], "total_time_ms": r[4]}
        for r in rows[:10]
    ]
    return {"date": today.isoformat(), "mode": mode, "entries": entries, "me": mine, "participants": total}


# ── achievements & taunts ────────────────────────────────────────────────────


@router.get("/achievements")
async def achievements(user: dict = Depends(get_current_user)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            unlocked = await ach.unlocked_for(cur, user["id"])
    return {
        "achievements": [
            {"key": k, **{kk: vv for kk, vv in v.items()}, "unlocked_at": unlocked.get(k)}
            for k, v in ach.ACHIEVEMENTS.items()
        ],
        "unlocked_count": len(unlocked),
    }


@router.get("/taunts/{match_id}")
async def taunt_for_match(match_id: str, user: dict = Depends(require_flag("social_taunts"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT taunt_id, text, shown_at FROM taunt_log WHERE user_id = %s::uuid AND match_id = %s",
                (user["id"], match_id),
            )
        ).fetchone()
    return {"match_id": match_id, "taunt": None if row is None else {"id": row[0], "text": row[1], "shown_at": row[2].isoformat()}}


# ── clips (dual consent, anonymised opponent — SOC-18) ───────────────────────


class ClipCreate(BaseModel):
    match_id: str = Field(max_length=40)


async def _clip_row(conn, clip_id: str):
    return await (
        await conn.execute(
            """SELECT id, match_id, owner_id, opponent_id, owner_consent, opponent_consent, status, payload, created_at
               FROM clips WHERE id = %s::uuid""",
            (clip_id,),
        )
    ).fetchone()


def _clip_public(row, viewer_id: str) -> dict:
    cid, match_id, owner, opp, oc, pc, status, payload, created = row
    return {
        "clip_id": str(cid), "match_id": match_id, "status": status,
        "you_are": "owner" if str(owner) == viewer_id else "opponent",
        "owner_consent": oc, "opponent_consent": pc,
        # The opponent is never named in a clip; the owner is "You" only to themselves.
        "players": ["You" if str(owner) == viewer_id else "Player", "Opponent"],
        "payload": payload, "created_at": created.isoformat(),
    }


@router.post("/clips")
async def clip_create(body: ClipCreate, user: dict = Depends(require_flag("social_clips"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await _require_not_kid(conn, user["id"], "clips")
        rows = await (
            await conn.execute(
                """SELECT user_id, is_bot, final_rank, problems_correct, problems_attempted, avg_time_ms
                   FROM player_match_results WHERE match_id = %s""",
                (body.match_id,),
            )
        ).fetchall()
        mine = next((r for r in rows if r[0] and str(r[0]) == user["id"]), None)
        if mine is None:
            raise HTTPException(status_code=404, detail="you did not play that match")
        others = [r for r in rows if not (r[0] and str(r[0]) == user["id"])]
        opponent = next((r for r in others if r[0] and not r[1]), None)
        # A human opponent must consent; otherwise nothing is disclosed and the
        # clip is ready at once (never say why).
        opp_id = str(opponent[0]) if opponent else None
        payload = {
            "match_id": body.match_id,
            "you": {"rank": mine[2], "correct": mine[3], "attempted": mine[4], "avg_time_ms": mine[5]},
            "opponent": {"rank": others[0][2], "correct": others[0][3], "attempted": others[0][4]} if others else None,
        }
        try:
            row = await (
                await conn.execute(
                    """INSERT INTO clips (match_id, owner_id, opponent_id, opponent_consent, status, payload)
                       VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s) RETURNING id""",
                    (body.match_id, user["id"], opp_id, opp_id is None, "pending" if opp_id else "ready", json.dumps(payload)),
                )
            ).fetchone()
        except Exception:  # noqa: BLE001
            await conn.rollback()
            raise HTTPException(status_code=409, detail="you already made a clip of that match")
        await conn.commit()
        clip = await _clip_row(conn, str(row[0]))
    return _clip_public(clip, user["id"])


@router.post("/clips/{clip_id}/consent")
async def clip_consent(clip_id: str, user: dict = Depends(require_flag("social_clips"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _clip_row(conn, clip_id)
        if row is None or (row[3] is None or str(row[3]) != user["id"]):
            raise HTTPException(status_code=404, detail="no clip awaiting your consent")
        await conn.execute(
            "UPDATE clips SET opponent_consent = TRUE, status = CASE WHEN status = 'revoked' THEN status ELSE 'ready' END WHERE id = %s::uuid",
            (clip_id,),
        )
        await conn.commit()
        row = await _clip_row(conn, clip_id)
    return _clip_public(row, user["id"])


@router.post("/clips/{clip_id}/revoke")
async def clip_revoke(clip_id: str, user: dict = Depends(require_flag("social_clips"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _clip_row(conn, clip_id)
        if row is None or user["id"] not in {str(row[2]), str(row[3]) if row[3] else ""}:
            raise HTTPException(status_code=404, detail="no such clip")
        await conn.execute("UPDATE clips SET status = 'revoked' WHERE id = %s::uuid", (clip_id,))
        await conn.commit()
        row = await _clip_row(conn, clip_id)
    return _clip_public(row, user["id"])


@router.get("/clips/{clip_id}")
async def clip_get(clip_id: str, user: dict = Depends(require_flag("social_clips"))) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await _clip_row(conn, clip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such clip")
    party = user["id"] in {str(row[2]), str(row[3]) if row[3] else ""}
    if row[6] != "ready" and not party:
        raise HTTPException(status_code=404, detail="no such clip")
    if row[6] == "revoked" and not party:
        raise HTTPException(status_code=404, detail="no such clip")
    return _clip_public(row, user["id"])
