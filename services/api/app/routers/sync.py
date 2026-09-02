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
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from .. import db
from ..config import get_settings
from ..security import get_current_user

router = APIRouter(prefix="/sync", tags=["sync"])

# Events that drive mastery are never sampled or dropped (architecture §11.3).
PSYCHOMETRIC_EVENTS = {
    "problem_attempt",
    "problem_solved",
    "trap_triggered",
    "bkt_state_snapshot",
    "session_start",
    "session_end",
    "calibration_completed",
}


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


def _offline_entitlement(user_id: str, tier: str) -> dict:
    """HMAC-signed entitlement the client verifies locally with a 3-day grace.

    UX only — the server re-validates on every online action, so a forged token
    buys nothing but a broken client.
    """
    import hashlib
    import hmac

    settings = get_settings()
    expires_at = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp())
    payload = f"{user_id}:{expires_at}"
    signature = hmac.new(
        settings.offline_token_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return {"tier": tier, "expires_at": expires_at, "signature": signature}


@router.post("")
async def sync_events(body: SyncRequest, user: dict = Depends(get_current_user)) -> dict:
    """Ingest a batch of client events (4-path write) and re-sign entitlement."""
    if not body.events:
        return {
            "accepted": 0,
            "duplicates": 0,
            "entitlement": _offline_entitlement(user["id"], user["tier"]),
        }

    pool = await db.get_pg()
    accepted = 0
    session_ends: list[SyncEvent] = []

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            for event in body.events:
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
                accepted += cur.rowcount or 0

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
                    (user["id"], event.session_id, json.dumps(states), body.device_id),
                )

        await conn.commit()

    return {
        "accepted": accepted,
        "duplicates": len(body.events) - accepted,
        "psychometric": sum(1 for e in body.events if e.event_type in PSYCHOMETRIC_EVENTS),
        "entitlement": _offline_entitlement(user["id"], user["tier"]),
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
