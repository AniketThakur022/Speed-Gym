"""Liveness (/health — no dependencies) and readiness (/ready — all 3 DBs)."""

import asyncio

from fastapi import APIRouter, Response

from ..config import get_settings
from .. import db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "version": settings.version}


async def _check_postgres() -> str:
    pool = await db.get_pg()
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
    return "healthy"


async def _check_neo4j() -> str:
    driver = db.get_neo4j()
    await driver.verify_connectivity()
    return "healthy"


async def _check_redis() -> str:
    client = db.get_redis()
    await client.ping()
    return "healthy"


@router.get("/ready")
async def ready(response: Response) -> dict:
    results = {}
    for name, check in (("postgres", _check_postgres), ("neo4j", _check_neo4j), ("redis", _check_redis)):
        try:
            results[name] = await asyncio.wait_for(check(), timeout=3.0)
        except Exception as exc:  # noqa: BLE001 — readiness reports, never raises
            results[name] = f"unavailable: {type(exc).__name__}"
    all_up = all(v == "healthy" for v in results.values())
    response.status_code = 200 if all_up else 503
    return {"status": "ready" if all_up else "degraded", "checks": results}
