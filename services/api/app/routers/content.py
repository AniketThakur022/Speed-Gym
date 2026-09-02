"""Topic Browser content reads (Postgres extraction-layer tables)."""

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter(prefix="/api", tags=["content"])


@router.get("/topics")
async def list_topics() -> dict:
    try:
        pool = await db.get_pg()
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    """SELECT topic, COUNT(*) AS problems,
                              COUNT(DISTINCT sub_topic) AS subtopics
                       FROM problems
                       WHERE topic IS NOT NULL
                       GROUP BY topic
                       ORDER BY problems DESC"""
                )
            ).fetchall()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"ledger unavailable: {type(exc).__name__}")
    return {
        "topics": [
            {"topic": r[0], "problems": r[1], "subtopics": r[2]} for r in rows
        ]
    }
