"""Feature-flag service — Postgres-backed, Redis-cached, deterministic rollout.

This is the mechanism behind two promises: Phase-2 features stay DARK until a
coordinated flag flip (not a redeploy), and any feature — or the ad engine —
can be killed within seconds. Everything that is gate-able reads through here.

Semantics:
* A flag is ON for a user when `enabled` AND (`rollout_pct` = 100 OR the
  user's stable bucket < rollout_pct). Bucketing is SHA-256(user_id:flag), so
  a learner stays in or out of a rollout across requests and processes.
* With no user (anonymous / server-side job) only a full rollout counts as on.
* Reads come from a Redis snapshot of the whole table (TTL 5 s), with a
  process-local fallback of the same TTL when Redis is down. Postgres is only
  hit on a cache miss, so `/api/config` and every gated route stay cheap.
* If the database cannot be read at all the answer is "every flag off": a
  client or route that cannot read the config must never conclude a dark
  feature is enabled (fail closed = dark).
* Flipping a flag calls `invalidate()`, so the change is visible on the next
  request in this process and within the TTL everywhere else.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException

from . import db
from .security import get_current_user

CACHE_TTL_SECONDS = 5.0
REDIS_KEY = "flags:snapshot"

_local: dict[str, Any] = {"at": 0.0, "flags": None}


def bucket(user_id: str, flag_name: str) -> int:
    digest = hashlib.sha256(f"{user_id}:{flag_name}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def _decide(flag: Optional[dict], user_id: Optional[str]) -> bool:
    if not flag or not flag.get("enabled"):
        return False
    pct = int(flag.get("rollout_pct") if flag.get("rollout_pct") is not None else 100)
    if pct >= 100:
        return True
    if pct <= 0 or not user_id:
        return False
    return bucket(user_id, flag["name"]) < pct


async def _load_from_db() -> Optional[dict[str, dict]]:
    try:
        pool = await db.get_pg()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute("SELECT flag_name, enabled, rollout_pct FROM feature_flags")
            ).fetchall()
    except Exception:  # noqa: BLE001
        return None
    return {r[0]: {"name": r[0], "enabled": bool(r[1]), "rollout_pct": r[2]} for r in rows}


async def snapshot() -> tuple[dict[str, dict], bool]:
    """All flags + a `degraded` marker (True when served from a fallback)."""
    now = time.monotonic()
    if _local["flags"] is not None and now - _local["at"] < CACHE_TTL_SECONDS:
        return _local["flags"], False

    redis = None
    try:
        redis = db.get_redis()
        cached = await redis.get(REDIS_KEY)
        if cached:
            flags = json.loads(cached)
            _local.update(at=now, flags=flags)
            return flags, False
    except Exception:  # noqa: BLE001
        redis = None

    flags = await _load_from_db()
    if flags is None:
        # Fail closed: everything dark. Do NOT cache the failure, so recovery
        # is immediate.
        return {}, True

    _local.update(at=now, flags=flags)
    if redis is not None:
        try:
            await redis.set(REDIS_KEY, json.dumps(flags), ex=int(CACHE_TTL_SECONDS) or 1)
        except Exception:  # noqa: BLE001
            pass
    return flags, False


async def flag_enabled(flag_name: str, user_id: Optional[str] = None) -> bool:
    flags, _ = await snapshot()
    return _decide(flags.get(flag_name), user_id)


async def invalidate() -> None:
    """Called after a flip. Local cache first, then Redis; a Redis failure is
    not fatal because the TTL bounds the staleness anyway."""
    _local.update(at=0.0, flags=None)
    try:
        await db.get_redis().delete(REDIS_KEY)
    except Exception:  # noqa: BLE001
        pass


def require_flag(flag_name: str):
    """Route dependency: 404 when the feature is dark for this user.

    404, not 403: a dark feature should look like it does not exist, so the
    response never confirms what is being dark-launched.
    """

    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if not await flag_enabled(flag_name, user["id"]):
            raise HTTPException(status_code=404, detail="not found")
        return user

    return _dep
