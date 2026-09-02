"""Practice reads — Neo4j "GPS" routes (live labels: :Skill, :Problem)."""

from fastapi import APIRouter, HTTPException, Query

from .. import db

router = APIRouter(prefix="/api/practice", tags=["practice"])


@router.get("/techniques")
async def list_techniques(limit: int = Query(default=100, le=500)) -> dict:
    try:
        driver = db.get_neo4j()
        async with driver.session() as session:
            result = await session.run(
                """MATCH (s:Skill)
                   OPTIONAL MATCH (s)-[:PREREQUISITE_OF]->(p:Problem)
                   WITH s, count(p) AS problem_count
                   RETURN s.name AS name, s.topic AS topic, s.sub_topic AS sub_topic,
                          s.is_root AS is_root, problem_count
                   ORDER BY problem_count DESC LIMIT $limit""",
                limit=limit,
            )
            records = [dict(r) async for r in result]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(exc).__name__}")
    return {"techniques": records}


@router.get("/problems")
async def list_problems(
    technique: str | None = None,
    topic: str | None = None,
    limit: int = Query(default=20, le=100),
) -> dict:
    where = ["p.question_text IS NOT NULL"]
    params: dict = {"limit": limit}
    if technique:
        where.append("p.technique = $technique")
        params["technique"] = technique
    if topic:
        where.append("p.topic = $topic")
        params["topic"] = topic
    query = (
        "MATCH (p:Problem) WHERE "
        + " AND ".join(where)
        + """ RETURN p.template_id AS template_id, p.question_text AS question_text,
               p.answer_key AS answer_key, p.difficulty AS difficulty,
               p.technique AS technique, p.topic AS topic,
               p.validation_status AS validation_status
          LIMIT $limit"""
    )
    try:
        driver = db.get_neo4j()
        async with driver.session() as session:
            result = await session.run(query, **params)
            records = [dict(r) async for r in result]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"graph unavailable: {type(exc).__name__}")
    return {"problems": records}
