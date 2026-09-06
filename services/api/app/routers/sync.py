"""Offline sync — event ingest and the keyed mutation replay.

Two endpoints, both on the frozen client contract:

* `POST /api/v1/sync` takes a batch of queued client events. Ingest fans out
  along the documented paths: A raw_events (immutable), B Postgres aggregates,
  C Neo4j edges (via the sync_outbox so a graph outage can never lose a ledger
  write), D bkt_state_snapshots on session_end.
* `POST /api/v1/sync/{key}` replays a single offline mutation (the recovered
  client's only key is `content/feedback`).

Idempotency is the whole point: a client that loses its connection mid-flush
will resend, so `event_id` is the key and re-sends are absorbed with
ON CONFLICT DO NOTHING rather than double-counting a learner's attempts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from .. import db
from ..billing.entitlement import entitlement_for
from ..security import get_current_user

router = APIRouter(prefix="/sync", tags=["sync"])

# The event registry and sampling policy live in app.telemetry; the invariant
# enforced there is that psychometric events are NEVER sampled (§11.3).
from ..telemetry import PSYCHOMETRIC_EVENTS, SamplingClass, decide  # noqa: E402
from ..social import xp as xp_mod  # noqa: E402
from ..social.policy import is_kid  # noqa: E402


class SyncEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=60)
    client_timestamp: int  # UNIX ms
    session_id: Optional[str] = None
    session_elapsed_ms: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SyncRequest(BaseModel):
    events: list[SyncEvent] = Field(default_factory=list, max_length=500)
    device_id: Optional[str] = None


KIDS_STRIPPED_METADATA = frozenset({"device_fingerprint", "device_id", "ip", "ip_address", "user_agent", "geo"})


async def _is_kid_account(conn, user_id: str) -> bool:
    row = await (
        await conn.execute("SELECT age, account_type FROM users WHERE id = %s::uuid", (user_id,))
    ).fetchone()
    return bool(row and is_kid(row[0]))


async def _current_dau(pool) -> int:
    """DAU from the KPI matview. Any failure returns 0, which DISABLES UI
    sampling — losing a little UI volume is the safe direction; sampling on a
    wrong number is not."""
    try:
        async with pool.connection() as conn:
            row = await (
                await conn.execute("SELECT value FROM kpi_dashboard_core WHERE metric = 'dau'")
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:  # noqa: BLE001
        return 0


async def _offline_entitlement(pool, user_id: str, tier: str) -> dict:
    """HMAC-signed entitlement the client verifies locally with a grace window.

    The horizon is the real subscription period end (billing.entitlement), so a
    paid learner offline for a week keeps Pro. UX only — the server re-validates
    on every online action, so a forged token buys nothing but a broken client.
    """
    async with pool.connection() as conn:
        return await entitlement_for(conn, user_id, tier)


@router.post("")
async def sync_events(body: SyncRequest, user: dict = Depends(get_current_user)) -> dict:
    """Ingest a batch of client events (4-path write) and re-sign entitlement."""
    pool = await db.get_pg()
    if not body.events:
        return {
            "accepted": 0,
            "duplicates": 0,
            "entitlement": await _offline_entitlement(pool, user["id"], user["tier"]),
        }

    accepted = 0
    sampled_out = 0
    minimized = 0
    unknown_types: set[str] = set()
    session_ends: list[SyncEvent] = []
    dau = await _current_dau(pool)
    xp_awarded = 0
    active_days: dict = {}

    async with pool.connection() as conn:
        kid = await _is_kid_account(conn, user["id"])
        device_id = None if kid else body.device_id
        async with conn.cursor() as cur:
            for event in body.events:
                decision = decide(event.event_type, user["id"], event.event_id, dau)
                if not decision.known:
                    unknown_types.add(event.event_type)
                    # Ingested at 100% but marked, so the registry gap is
                    # visible in the ledger rather than silently swallowed.
                    event.metadata = {**event.metadata, "_registry_unknown": True}
                if decision.sampled_out:
                    sampled_out += 1
                    continue
                if kid:
                    # COPPA (FAM-05/SEC-08) "minimise tracking": engagement/UI
                    # telemetry is never stored for a child; psychometric
                    # events are the service itself and stay. Device and
                    # network identifiers are stripped from what is kept.
                    if decision.sampling is SamplingClass.UI:
                        minimized += 1
                        continue
                    event.metadata = {
                        k: v for k, v in event.metadata.items()
                        if k not in KIDS_STRIPPED_METADATA
                    }

                # PATH A — immutable event stream. event_id makes the resend of
                # a partially-flushed batch a no-op instead of a double count.
                await cur.execute(
                    """INSERT INTO raw_events (event_id, user_id, session_id, event_type,
                           client_timestamp, session_elapsed_ms, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (
                        event.event_id,
                        user["id"],
                        event.session_id,
                        event.event_type,
                        event.client_timestamp,
                        event.session_elapsed_ms,
                        json.dumps(event.metadata),
                    ),
                )
                inserted = (cur.rowcount or 0) == 1
                accepted += 1 if inserted else 0

                # XP + streak from the SAME accepted events (idempotent on
                # event_id via the ledger; a resend cannot pay twice).
                if inserted:
                    # client_timestamp is unvalidated device time; never let it
                    # run the streak into the future (see xp.record_activity_day).
                    day = min(
                        datetime.fromtimestamp(event.client_timestamp / 1000, tz=timezone.utc).date(),
                        datetime.now(timezone.utc).date(),
                    )
                    if event.event_type == "problem_attempt":
                        active_days[day] = active_days.get(day, 0) + 1
                        if event.metadata.get("is_correct") is True:
                            xp_awarded += await xp_mod.award(cur, user["id"], "practice_correct", event.event_id)
                    elif event.event_type == "session_end":
                        active_days.setdefault(day, 0)
                        xp_awarded += await xp_mod.award(cur, user["id"], "session_complete", event.event_id)

                # PATH C — graph writes go through the outbox inside this same
                # transaction; a worker drains it, so Neo4j being down delays
                # the edge but never loses the ledger row.
                if event.event_type in {"problem_attempt", "problem_solved", "session_end"}:
                    await cur.execute(
                        """INSERT INTO sync_outbox (user_id, event_id, event_type, payload)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (event_id) DO NOTHING""",
                        (user["id"], event.event_id, event.event_type, json.dumps(event.metadata)),
                    )

                if event.event_type == "session_end":
                    session_ends.append(event)

            # Streak days, once per (user, day) per batch.
            for day, problems in sorted(active_days.items()):
                state = await xp_mod.record_activity_day(cur, user["id"], day, problems)
                if state["new_day"]:
                    xp_awarded += await xp_mod.award(cur, user["id"], "streak_day", day.isoformat())

            # PATH B — aggregates. Derived from the events just accepted.
            for event in session_ends:
                if not event.session_id:
                    continue
                await cur.execute(
                    """UPDATE sessions
                       SET status = 'completed', ended_at = NOW(),
                           session_elapsed_ms = COALESCE(%s, session_elapsed_ms)
                       WHERE id = %s::uuid AND user_id = %s::uuid""",
                    (event.session_elapsed_ms, event.session_id, user["id"]),
                )

            # PATH D — BKT snapshot rollup at session end.
            for event in session_ends:
                states = event.metadata.get("technique_states")
                if not states:
                    continue
                await cur.execute(
                    """INSERT INTO bkt_state_snapshots
                           (user_id, session_id, technique_states, snapshot_reason, device_id)
                       VALUES (%s, %s::uuid, %s, 'session_end', %s)""",
                    (user["id"], event.session_id, json.dumps(states), device_id),
                )

        await conn.commit()

    return {
        "accepted": accepted,
        "duplicates": len(body.events) - accepted - sampled_out,
        "sampled_out": sampled_out,
        "minimized": minimized,
        "xp_awarded": xp_awarded,
        "psychometric": sum(1 for e in body.events if e.event_type in PSYCHOMETRIC_EVENTS),
        "unknown_event_types": sorted(unknown_types),
        "entitlement": await _offline_entitlement(pool, user["id"], user["tier"]),
    }


@router.post("/{key:path}")
async def replay_mutation(
    body: dict,
    key: str = Path(description="Mutation key, e.g. content/feedback"),
    user: dict = Depends(get_current_user),
) -> dict:
    """Replay one queued offline mutation. Unknown keys are refused rather than
    silently accepted, so a client bug surfaces instead of dropping data."""
    if key != "content/feedback":
        raise HTTPException(status_code=404, detail=f"unknown sync key: {key}")

    template_id = body.get("templateId")
    if not template_id:
        raise HTTPException(status_code=422, detail="templateId is required")

    pool = await db.get_pg()
    async with pool.connection() as conn:
        await conn.execute(
            """INSERT INTO content_feedback
                   (user_id, template_id, trust_status, reason, comment, domain, reported_at)
               VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s / 1000.0))""",
            (
                user["id"],
                template_id,
                body.get("trustStatus"),
                body.get("reason"),
                body.get("comment"),
                body.get("domain"),
                body.get("reportedAt") or 0,
            ),
        )
        await conn.commit()
    return {"status": "accepted", "key": key}
