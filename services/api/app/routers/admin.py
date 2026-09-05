"""Admin surface and the runtime config clients read at session start.

Two very different audiences share this module:

* `GET /api/config` is read by every client on session start. It is
  UNAUTHENTICATED by design — it must answer during an incident, including for a
  client whose token has expired, because it carries the emergency kill-switch.
  It therefore exposes flag STATES only, never thresholds, secrets or counts.
* `/api/admin/*` is operator-only. `problem_health_scores` now decides what
  reaches a learner, so changing it is a privileged, audited action.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import db
from .. import flags as flags_service
from ..content import reset_quarantine_cache
from ..security import get_current_user
from ..telemetry import DAU_SAMPLING_THRESHOLD, UI_SAMPLE_KEEP_ONE_IN, registry_snapshot

router = APIRouter(tags=["admin"])

TRUST_LEVELS = ["LIVE", "TRUSTED", "SANDBOX", "QUARANTINED_SOFT", "QUARANTINED_HARD"]


async def require_admin(request: Request, user: dict = Depends(get_current_user)) -> dict:
    """Admin is a property of the account, checked against the database on every
    call — not a claim carried in the JWT, which would keep working for the life
    of a token after access is revoked."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute("SELECT is_admin FROM users WHERE id = %s::uuid", (user["id"],))
        ).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=403, detail="admin access required")
    return user


# ── Runtime config / kill-switch ────────────────────────────────────────────


@router.get("/api/config")
async def runtime_config() -> dict:
    """Feature flags and kill-switches, read by clients at session start.

    Fails OPEN to an all-disabled config: if this endpoint cannot reach the
    database it returns every flag off rather than erroring, because a client
    that cannot read the config must not conclude that a dark-launched feature
    is enabled.
    """
    snap, degraded = await flags_service.snapshot()
    return {
        "flags": {
            name: {"enabled": f["enabled"], "rollout_pct": f["rollout_pct"]}
            for name, f in sorted(snap.items())
        },
        "degraded": degraded,
    }


# ── Content trust admin ─────────────────────────────────────────────────────


class TrustOverride(BaseModel):
    trust_level: str = Field(description="One of LIVE/TRUSTED/SANDBOX/QUARANTINED_SOFT/QUARANTINED_HARD")
    reason: str = Field(min_length=3, max_length=500)


@router.get("/api/admin/content/trust")
async def list_trust(
    level: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    _: dict = Depends(require_admin),
) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        if level:
            rows = await (
                await conn.execute(
                    """SELECT content_id, trust_level, health_score, exposure_count, updated_at
                       FROM problem_health_scores WHERE trust_level = %s
                       ORDER BY updated_at DESC LIMIT %s""",
                    (level, limit),
                )
            ).fetchall()
        else:
            rows = await (
                await conn.execute(
                    """SELECT content_id, trust_level, health_score, exposure_count, updated_at
                       FROM problem_health_scores ORDER BY updated_at DESC LIMIT %s""",
                    (limit,),
                )
            ).fetchall()
        totals = await (
            await conn.execute(
                "SELECT trust_level, count(*) FROM problem_health_scores GROUP BY trust_level"
            )
        ).fetchall()
    return {
        "totals": {row[0]: row[1] for row in totals},
        "items": [
            {
                "content_id": r[0],
                "trust_level": r[1],
                "health_score": float(r[2]) if r[2] is not None else None,
                "exposure_count": r[3],
                "updated_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ],
    }


@router.get("/api/admin/content/trust/{content_id}")
async def trust_detail(content_id: str, _: dict = Depends(require_admin)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT content_id, trust_level, updated_at FROM problem_health_scores WHERE content_id = %s",
                (content_id,),
            )
        ).fetchone()
        history = await (
            await conn.execute(
                """SELECT previous_level, new_level, reason, changed_at
                   FROM content_trust_overrides WHERE content_id = %s
                   ORDER BY changed_at DESC LIMIT 50""",
                (content_id,),
            )
        ).fetchall()
        gates = await (
            await conn.execute(
                """SELECT gate, passed, details, verifier_version, created_at
                   FROM content_validation_log WHERE content_id = %s
                   ORDER BY created_at DESC LIMIT 50""",
                (content_id,),
            )
        ).fetchall()
    if row is None and not history and not gates:
        raise HTTPException(status_code=404, detail="no trust record for that content id")
    return {
        "content_id": content_id,
        # A missing row is not an error: it means the ladder has no opinion, and
        # the serving default applies.
        "trust_level": row[1] if row else None,
        "updated_at": row[2].isoformat() if row and row[2] else None,
        "overrides": [
            {"from": h[0], "to": h[1], "reason": h[2], "at": h[3].isoformat() if h[3] else None}
            for h in history
        ],
        "gate_history": [
            {
                "gate": g[0],
                "passed": g[1],
                "details": g[2],
                "verifier_version": g[3],
                "at": g[4].isoformat() if g[4] else None,
            }
            for g in gates
        ],
    }


@router.post("/api/admin/content/trust/{content_id}")
async def override_trust(
    content_id: str, body: TrustOverride, admin: dict = Depends(require_admin)
) -> dict:
    """Manually set a content item's trust level.

    A reason is REQUIRED, not optional: this changes what learners are shown,
    and an unexplained override is indistinguishable from a mistake when someone
    reviews it later.
    """
    if body.trust_level not in TRUST_LEVELS:
        raise HTTPException(status_code=422, detail=f"trust_level must be one of {TRUST_LEVELS}")

    pool = await db.get_pg()
    async with pool.connection() as conn:
        previous = await (
            await conn.execute(
                "SELECT trust_level FROM problem_health_scores WHERE content_id = %s", (content_id,)
            )
        ).fetchone()
        await conn.execute(
            """INSERT INTO problem_health_scores (content_id, trust_level, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (content_id) DO UPDATE
                 SET trust_level = EXCLUDED.trust_level, updated_at = NOW()""",
            (content_id, body.trust_level),
        )
        await conn.execute(
            """INSERT INTO content_trust_overrides
                   (content_id, previous_level, new_level, reason, changed_by)
               VALUES (%s, %s, %s, %s, %s::uuid)""",
            (content_id, previous[0] if previous else None, body.trust_level, body.reason, admin["id"]),
        )
        await conn.commit()

    # Make it visible in this process at once; other workers pick it up within
    # the cache TTL.
    reset_quarantine_cache()
    return {
        "content_id": content_id,
        "previous_level": previous[0] if previous else None,
        "trust_level": body.trust_level,
    }


# ── Feature flags ───────────────────────────────────────────────────────────


class FlagUpdate(BaseModel):
    enabled: bool
    rollout_pct: Optional[int] = Field(default=None, ge=0, le=100)


@router.get("/api/admin/flags")
async def list_flags(_: dict = Depends(require_admin)) -> dict:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT flag_name, enabled, rollout_pct, description, updated_by, updated_at
                   FROM feature_flags ORDER BY flag_name"""
            )
        ).fetchall()
    return {
        "flags": [
            {
                "flag_name": r[0],
                "enabled": r[1],
                "rollout_pct": r[2],
                "description": r[3],
                "updated_by": r[4],
                "updated_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    }


@router.post("/api/admin/flags/{flag_name}")
async def set_flag(flag_name: str, body: FlagUpdate, admin: dict = Depends(require_admin)) -> dict:
    """Flip a flag. Phase-2 activation is a flag flip, not a redeploy, and the
    same path is the emergency kill-switch — so only KNOWN flags may be set;
    inventing one here would create a flag nothing reads."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        existing = await (
            await conn.execute("SELECT flag_name FROM feature_flags WHERE flag_name = %s", (flag_name,))
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=404, detail=f"unknown flag: {flag_name}")
        await conn.execute(
            """UPDATE feature_flags
               SET enabled = %s,
                   rollout_pct = COALESCE(%s, rollout_pct),
                   updated_by = %s, updated_at = NOW()
               WHERE flag_name = %s""",
            (body.enabled, body.rollout_pct, admin["email"], flag_name),
        )
        await conn.commit()
    # The kill-switch must bite within seconds: drop the caches now.
    await flags_service.invalidate()
    return {"flag_name": flag_name, "enabled": body.enabled}


# ── KPI views ───────────────────────────────────────────────────────────────


@router.post("/api/admin/kpi/refresh")
async def refresh_kpi(_: dict = Depends(require_admin)) -> dict:
    """Refresh the KPI matview on demand. Celery beat does this every 15 minutes;
    this exists so an operator does not have to wait for the next tick."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        try:
            await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_dashboard_core")
        except Exception:  # noqa: BLE001 — CONCURRENTLY needs a populated view
            await conn.execute("REFRESH MATERIALIZED VIEW kpi_dashboard_core")
        await conn.commit()
        rows = await (await conn.execute("SELECT metric, value FROM kpi_dashboard_core")).fetchall()
    return {"refreshed": True, "metrics": {r[0]: float(r[1]) if r[1] is not None else None for r in rows}}


@router.get("/api/admin/kpi")
async def read_kpi(_: dict = Depends(require_admin)) -> dict:
    """Current KPI matview values (refreshed by Celery every 15 min)."""
    pool = await db.get_pg()
    async with pool.connection() as conn:
        rows = await (await conn.execute("SELECT metric, value FROM kpi_dashboard_core")).fetchall()
    return {"metrics": {r[0]: float(r[1]) if r[1] is not None else None for r in rows}}


@router.get("/api/admin/telemetry/registry")
async def telemetry_registry(_: dict = Depends(require_admin)) -> dict:
    """The event registry and the sampling policy, as the ingest path applies it.

    Read-only by design: the policy is code, not config, so nobody can flip
    psychometric events into the sampleable class from a dashboard.
    """
    return {
        "policy": {
            "dau_sampling_threshold": DAU_SAMPLING_THRESHOLD,
            "ui_sample_keep_one_in": UI_SAMPLE_KEEP_ONE_IN,
            "never_sampled_classes": [
                "psychometric_never_sampled",
                "conversion_never_sampled",
                "ops_never_sampled",
            ],
        },
        "events": registry_snapshot(),
    }
