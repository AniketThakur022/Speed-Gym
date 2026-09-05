"""Internal API — consumed only by the Node game server over loopback.

Not part of the public `/api/v1` surface: these endpoints hand out problem
ANSWERS and per-user ability estimates, so they are guarded by a shared
`X-Internal-Key` and, by default, refuse any caller that is not loopback.

Bot fields never cross this boundary outward: `is_bot`/`bot_persona` are stored
but stripped from anything a client could reach.
"""

from __future__ import annotations

import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..content import extract_numeric_answer, quarantined_ids
from ..glicko2 import Rating, seed_rating, update_match
from ..social.policy import kids_policy

router = APIRouter(prefix="/internal", tags=["internal"])

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


async def require_internal(request: Request, x_internal_key: str = Header(default="")) -> None:
    settings = get_settings()
    client_host = request.client.host if request.client else ""
    if settings.internal_api_require_loopback and client_host not in LOOPBACK:
        raise HTTPException(status_code=403, detail="internal API is loopback-only")
    if not secrets.compare_digest(x_internal_key, settings.internal_api_key):
        raise HTTPException(status_code=403, detail="bad internal key")


class UserContextRequest(BaseModel):
    user_id: str


class ProblemBatchRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=50)
    difficulty_range: Optional[list[float]] = None
    technique_ids: Optional[list[str]] = None


class PlayerResult(BaseModel):
    user_id: str
    is_bot: bool = False
    final_rank: int
    final_score: int
    problems_attempted: int = 0
    problems_correct: int = 0
    accuracy_pct: float = 0
    avg_time_ms: float = 0
    position_points: int = 0
    accuracy_bonus: int = 0
    theta_u_snapshot: Optional[float] = None
    cluster_snapshot: Optional[str] = None


class MatchCompleteRequest(BaseModel):
    match_id: str
    mode: str = "accuracy_duel"
    topology: str = "online"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    results: list[PlayerResult]


@router.post("/user/context", dependencies=[Depends(require_internal)])
async def user_context(body: UserContextRequest) -> dict:
    """Ability and rating context the game server needs to seed a match."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT u.id, u.age, COALESCE(p.theta, 0) AS theta,
                          p.behavioral_cluster, e.rating, e.rating_deviation, e.volatility,
                          u.account_type, u.taunts_enabled
                   FROM users u
                   LEFT JOIN user_cognitive_profiles p ON p.user_id = u.id
                   LEFT JOIN player_elo_ratings e ON e.user_id = u.id
                   WHERE u.id = %s::uuid""",
                (body.user_id,),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown user")

    _, age, theta, cluster, rating, rd, volatility, account_type, taunts_ok = row
    theta = float(theta or 0)
    policy = kids_policy(age, account_type or "standard")
    return {
        "user_id": body.user_id,
        "theta_u": theta,
        "cluster": cluster or "balanced",
        # None when unknown: the game server treats unknown age as bot-ineligible
        # (COPPA gate), and defaulting to an adult here would defeat that.
        "age_group": age,
        "account_type": account_type or "standard",
        "kids_mode": policy["kids_mode"],
        "bots_allowed": policy["bots_enabled"],
        "taunts_enabled": policy["taunts_enabled"] and bool(taunts_ok),
        "elo": int(rating) if rating is not None else int(seed_rating(theta).rating),
        "rating_deviation": int(rd) if rd is not None else 350,
        "volatility": float(volatility) if volatility is not None else 0.06,
    }


@router.post("/game/problem-batch", dependencies=[Depends(require_internal)])
async def problem_batch(body: ProblemBatchRequest) -> dict:
    """Problems WITH answers, for server-authoritative scoring.

    Only answer-checkable, verified items are returned: the duel is decided by
    exact comparison, so an item whose answer needs a SymPy round-trip cannot be
    scored inside a round timer.
    """
    low, high = (body.difficulty_range or [1, 5])[:2] if body.difficulty_range else (1, 5)

    # This route feeds live duels, so it must apply the SAME content guards as
    # the practice session builder. It previously used a bare MATCH with no
    # skill-edge requirement, which put edge-less problems and
    # factory-quarantined items into the duel pool — the practice loop refused
    # exactly those, so the backend was enforcing opposite rules on two serving
    # paths.
    pool = await db.get_pg()
    excluded = await quarantined_ids(pool)

    filters = [
        "p.question_text IS NOT NULL AND trim(p.question_text) <> ''",
        "p.answer_key IS NOT NULL",
        "p.validation_status IN ['verified_L1','verified_L2']",
        "NOT p.template_id IN $excluded",
    ]
    params: dict[str, Any] = {"limit": body.count * 6, "excluded": sorted(excluded)}
    if body.technique_ids:
        filters.append("p.technique IN $technique_ids")
        params["technique_ids"] = body.technique_ids

    query = (
        "MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem) WHERE "
        + " AND ".join(filters)
        + """ WITH DISTINCT p
              RETURN p.template_id AS problem_id, p.question_text AS problem_text,
                     p.answer_key AS answer_key, p.difficulty AS difficulty
              ORDER BY rand() LIMIT $limit"""
    )
    try:
        driver = db.get_neo4j()
        async with driver.session() as neo:
            result = await neo.run(query, **params)
            candidates = [dict(record) async for record in result]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(exc).__name__}")

    problems = []
    for candidate in candidates:
        answer = extract_numeric_answer(candidate.get("answer_key"))
        if answer is None:
            continue
        difficulty = candidate.get("difficulty") or 1
        if not (low <= float(difficulty) <= high + 1):
            continue
        problems.append(
            {
                "problem_id": candidate["problem_id"],
                "problem_text": candidate["problem_text"],
                "answer": ("%g" % answer),
                "difficulty": float(difficulty),
                "renderer_type": "latex",
            }
        )
        if len(problems) >= body.count:
            break

    if not problems:
        raise HTTPException(status_code=404, detail="no answer-checkable problems in range")
    return {"problems": problems}


@router.post("/match/complete", dependencies=[Depends(require_internal)])
async def match_complete(body: MatchCompleteRequest) -> dict:
    """Persist a finished match and return the Glicko-2 rating changes.

    The game server emits `match_ended` only after this returns, because the
    payload's elo_change comes from here.
    """
    pool = await db.get_pg()
    human_results = [r for r in body.results if not r.is_bot]

    async with pool.connection() as conn:
        await conn.execute(
            """INSERT INTO game_matches (match_id, mode, topology, status, duration_ms)
               VALUES (%s, %s, %s, 'completed', %s)
               ON CONFLICT (match_id) DO NOTHING""",
            (body.match_id, body.mode, body.topology, body.duration_ms),
        )

        # Load current ratings, seeding from ability for first-time players.
        ratings: dict[str, Rating] = {}
        before: dict[str, int] = {}
        for result in human_results:
            row = await (
                await conn.execute(
                    """SELECT rating, rating_deviation, volatility
                       FROM player_elo_ratings WHERE user_id = %s::uuid""",
                    (result.user_id,),
                )
            ).fetchone()
            if row is None:
                seeded = seed_rating(result.theta_u_snapshot or 0.0)
                ratings[result.user_id] = seeded
            else:
                ratings[result.user_id] = Rating(
                    rating=float(row[0]), rd=float(row[1]), volatility=float(row[2])
                )
            before[result.user_id] = int(ratings[result.user_id].rating)

        ranks = {r.user_id: r.final_rank for r in human_results}
        updated = update_match(ratings, ranks) if len(ratings) > 1 else ratings

        elo_updates = []
        for result in body.results:
            new_rating = updated.get(result.user_id)
            elo_after = int(new_rating.rating) if new_rating else None
            elo_before = before.get(result.user_id)
            elo_change = (elo_after - elo_before) if (elo_after and elo_before) else None

            await conn.execute(
                """INSERT INTO player_match_results
                       (match_id, user_id, is_bot, final_rank, final_score,
                        position_points, accuracy_bonus, problems_attempted,
                        problems_correct, accuracy_pct, avg_time_ms,
                        elo_before, elo_after, elo_change, theta_u_snapshot,
                        cluster_snapshot)
                   VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (match_id, user_id) DO NOTHING""",
                (
                    body.match_id,
                    result.user_id if not result.is_bot else None,
                    result.is_bot,
                    result.final_rank,
                    result.final_score,
                    result.position_points,
                    result.accuracy_bonus,
                    result.problems_attempted,
                    result.problems_correct,
                    result.accuracy_pct,
                    int(result.avg_time_ms),
                    elo_before,
                    elo_after,
                    elo_change,
                    result.theta_u_snapshot,
                    result.cluster_snapshot,
                ),
            )

            if new_rating and not result.is_bot:
                won = result.final_rank == 1
                await conn.execute(
                    """INSERT INTO player_elo_ratings
                           (user_id, mode, rating, rating_deviation, volatility,
                            matches_played, wins, losses, updated_at)
                       VALUES (%s::uuid, %s, %s, %s, %s, 1, %s, %s, NOW())
                       ON CONFLICT (user_id) DO UPDATE SET
                           rating = EXCLUDED.rating,
                           rating_deviation = EXCLUDED.rating_deviation,
                           volatility = EXCLUDED.volatility,
                           matches_played = player_elo_ratings.matches_played + 1,
                           wins = player_elo_ratings.wins + EXCLUDED.wins,
                           losses = player_elo_ratings.losses + EXCLUDED.losses,
                           updated_at = NOW()""",
                    (
                        result.user_id,
                        body.mode,
                        int(new_rating.rating),
                        int(new_rating.rd),
                        round(new_rating.volatility, 5),
                        1 if won else 0,
                        0 if won else 1,
                    ),
                )
                # is_bot / bot_persona are never echoed back outward.
                elo_updates.append(
                    {
                        "user_id": result.user_id,
                        "elo_before": elo_before,
                        "elo_after": elo_after,
                        "elo_change": elo_change,
                        "rating_deviation": int(new_rating.rd),
                    }
                )

        # Social side-effects (block 5): XP, streak day, achievements, taunt.
        # Everything here is idempotent on match_id, and nothing about bots
        # leaves this function except a halved XP award.
        async with conn.cursor() as cur:
            social = await _social_after_match(cur, body, human_results, updated)
        await conn.commit()

    return {"match_id": body.match_id, "elo_updates": elo_updates, "persisted": True, "social": social}


async def _social_after_match(cur, body: MatchCompleteRequest, human_results: list, ratings: dict) -> dict:
    from ..social import achievements as ach
    from ..social import xp as xp_mod
    from ..social.policy import taunt_decision
    from ..social.taunts import build_context, select_taunt

    any_bot = any(r.is_bot for r in body.results)
    out: dict[str, dict] = {}
    for result in human_results:
        uid = result.user_id
        won = result.final_rank == 1
        entry: dict = {"xp_awarded": 0, "achievements_unlocked": [], "taunt": None}

        reason = "duel_win" if won else "duel_loss"
        delta = xp_mod.XP_RULES[reason] // 2 if any_bot else xp_mod.XP_RULES[reason]
        entry["xp_awarded"] += await xp_mod.award(cur, uid, reason, body.match_id, delta)
        day = await xp_mod.record_activity_day(cur, uid, xp_mod.utc_today(), result.problems_attempted)
        if day["new_day"]:
            entry["xp_awarded"] += await xp_mod.award(cur, uid, "streak_day", xp_mod.utc_today().isoformat())

        await cur.execute(
            """SELECT final_rank FROM player_match_results
               WHERE user_id = %s::uuid ORDER BY created_at DESC LIMIT 30""",
            (uid,),
        )
        recent = [r[0] for r in await cur.fetchall()]
        win_streak = 0
        for rank in recent:
            if rank == 1:
                win_streak += 1
            else:
                break
        loss_streak = 0
        for rank in recent:
            if rank != 1:
                loss_streak += 1
            else:
                break
        await cur.execute(
            "SELECT matches_played, rating FROM player_elo_ratings WHERE user_id = %s::uuid", (uid,)
        )
        elo_row = await cur.fetchone()
        stats = {
            "won": won, "mode": body.mode, "win_streak": win_streak,
            "matches_played": int(elo_row[0]) if elo_row else 1,
            "elo": int(elo_row[1]) if elo_row else 0,
            "accuracy_pct": float(result.accuracy_pct or 0), "duration_ms": body.duration_ms,
        }
        entry["achievements_unlocked"] = await ach.unlock(cur, uid, ach.evaluate(stats))

        # Taunt: SOC-15/16 gates, then a stable pick for this match.
        await cur.execute(
            """SELECT u.age, p.behavioral_cluster, u.taunts_enabled, u.display_name
               FROM users u LEFT JOIN user_cognitive_profiles p ON p.user_id = u.id WHERE u.id = %s::uuid""",
            (uid,),
        )
        prow = await cur.fetchone()
        age, cluster, opted_in, _name = prow if prow else (None, None, True, None)
        await cur.execute(
            """SELECT COUNT(*) FROM player_match_results r
               WHERE r.user_id = %s::uuid AND r.match_id <> %s
                 AND r.created_at > COALESCE((SELECT MAX(shown_at) FROM taunt_log WHERE user_id = %s::uuid), '-infinity')""",
            (uid, body.match_id, uid),
        )
        since_last = int((await cur.fetchone())[0])
        allowed, why = taunt_decision(age, cluster, since_last, loss_streak, bool(opted_in))
        if allowed:
            opp = next((r for r in body.results if r.user_id != uid), None)
            opp_name = "Your opponent"
            if opp is not None and not opp.is_bot:
                await cur.execute("SELECT display_name FROM users WHERE id = %s::uuid", (opp.user_id,))
                nrow = await cur.fetchone()
                opp_name = (nrow[0] if nrow and nrow[0] else None) or "Your opponent"
            ctx = build_context(
                won=won,
                my_correct=int(result.problems_correct), opp_correct=int(opp.problems_correct) if opp else 0,
                my_attempted=int(result.problems_attempted),
                my_time_ms=int(result.avg_time_ms or 0), opp_time_ms=int(opp.avg_time_ms or 0) if opp else 0,
                my_accuracy=float(result.accuracy_pct or 0), opp_accuracy=float(opp.accuracy_pct or 0) if opp else 0.0,
                traps_triggered=int(getattr(result, "traps_triggered", 0) or 0),
                opponent_name=opp_name,
            )
            taunt = select_taunt(ctx, body.match_id)
            if taunt:
                await cur.execute(
                    """INSERT INTO taunt_log (user_id, match_id, taunt_id, text) VALUES (%s::uuid, %s, %s, %s)
                       ON CONFLICT (user_id, match_id) DO NOTHING""",
                    (uid, body.match_id, taunt["id"], taunt["text"]),
                )
                entry["taunt"] = taunt
        else:
            entry["taunt_suppressed"] = why
        out[uid] = entry
    return out


@router.get("/game/leaderboard", dependencies=[Depends(require_internal)])
async def leaderboard(mode: str = "accuracy_duel", limit: int = 50) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT e.user_id, u.display_name, e.rating, e.matches_played, e.wins
                   FROM player_elo_ratings e JOIN users u ON u.id = e.user_id
                   WHERE e.mode = %s ORDER BY e.rating DESC LIMIT %s""",
                (mode, min(limit, 200)),
            )
        ).fetchall()
    return {
        "leaderboard": [
            {
                "user_id": str(row[0]),
                "display_name": row[1],
                "elo": row[2],
                "matches_played": row[3],
                "wins": row[4],
            }
            for row in rows
        ]
    }
