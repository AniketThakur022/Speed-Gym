"""Lazy database clients — nothing connects at import time, so the app (and
its CI-safe tests) start with no databases present. First use opens the pool.
"""

from __future__ import annotations

from typing import Any, Optional

from .config import get_settings

_pg_pool: Optional[Any] = None
_neo4j_driver: Optional[Any] = None
_redis_client: Optional[Any] = None


async def get_pg():
    global _pg_pool
    if _pg_pool is None:
        from psycopg_pool import AsyncConnectionPool

        settings = get_settings()
        _pg_pool = AsyncConnectionPool(settings.database_url, min_size=1, max_size=10, open=False)
        await _pg_pool.open()
    return _pg_pool


def get_neo4j():
    global _neo4j_driver
    if _neo4j_driver is None:
        from neo4j import AsyncGraphDatabase

        settings = get_settings()
        _neo4j_driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
    return _neo4j_driver


def get_redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis

        settings = get_settings()
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_all() -> None:
    global _pg_pool, _neo4j_driver, _redis_client
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
    if _neo4j_driver is not None:
        await _neo4j_driver.close()
        _neo4j_driver = None
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
