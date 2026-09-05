"""Daily challenge — the same 10 problems for everyone, server-scored, never
bots (they would distort global percentiles; §9.4).

Selection is a pure function of the date over the servable pool (same guards
as the practice loop: skill edge, verified question+answer, not quarantined),
so every API node and the worker agree without coordination.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, Optional

from ..content import extract_numeric_answer

PROBLEMS_PER_DAY = 10
SPEED_BONUS_SECONDS_PER_PROBLEM = 60

DAILY_POOL_CYPHER = """
MATCH (s:Skill)-[:PREREQUISITE_OF]->(p:Problem)
WHERE p.question_text IS NOT NULL AND trim(p.question_text) <> ''
  AND p.answer_key IS NOT NULL
  AND p.validation_status IN ['verified_L1', 'verified_L2']
  AND NOT p.template_id IN $excluded
WITH DISTINCT p
RETURN p.template_id AS problem_id, p.question_text AS text,
       p.answer_key AS answer_key, p.difficulty AS difficulty
LIMIT 600
"""


def seed_for(day: date) -> str:
    return hashlib.sha256(f"daily:{day.isoformat()}".encode()).hexdigest()


def pick_problems(candidates: list[dict[str, Any]], day: date, n: int = PROBLEMS_PER_DAY) -> list[dict]:
    """Deterministic: order by sha256(seed:problem_id), keep numeric-answer items."""
    seed = seed_for(day)
    scored = []
    for c in candidates:
        answer = extract_numeric_answer(c.get("answer_key"))
        if answer is None or not c.get("problem_id"):
            continue
        h = hashlib.sha256(f"{seed}:{c['problem_id']}".encode()).hexdigest()
        scored.append((h, c, answer))
    scored.sort(key=lambda t: t[0])
    out = []
    for _, c, answer in scored[:n]:
        out.append({
            "problem_id": c["problem_id"],
            "text": c.get("text"),
            "difficulty": float(c.get("difficulty") or 1),
            "answer": answer,
        })
    return out


def is_correct(submitted: Optional[str], expected: float) -> bool:
    if submitted is None:
        return False
    value = extract_numeric_answer(str(submitted))
    if value is None:
        return False
    return abs(value - expected) <= 1e-6 * max(1.0, abs(expected))


def score(correct: int, total: int, total_time_ms: int) -> int:
    """100 per correct + a speed bonus: seconds saved under 60 s/problem, only
    when every problem was answered correctly (speed never beats accuracy)."""
    base = 100 * correct
    if total and correct == total:
        saved = total * SPEED_BONUS_SECONDS_PER_PROBLEM - total_time_ms / 1000
        base += int(max(0, saved))
    return base


async def ensure_today(conn, neo4j_driver, excluded: set[str], day: date, domain: str = "vedic-math") -> Optional[dict]:
    """Return today's challenge, generating it if missing. Idempotent across
    nodes: ON CONFLICT keeps whichever node inserted first."""
    row = await (
        await conn.execute(
            "SELECT problems, answers FROM daily_challenges WHERE challenge_date = %s", (day,)
        )
    ).fetchone()
    if row:
        return {"date": day.isoformat(), "problems": row[0], "answers": row[1]}

    async with neo4j_driver.session() as neo:
        result = await neo.run(DAILY_POOL_CYPHER, excluded=sorted(excluded))
        candidates = [dict(r) async for r in result]
    picked = pick_problems(candidates, day)
    if not picked:
        return None
    import json

    problems = [{k: v for k, v in p.items() if k != "answer"} for p in picked]
    answers = [p["answer"] for p in picked]
    await conn.execute(
        """INSERT INTO daily_challenges (challenge_date, domain, problems, answers, seed)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (challenge_date) DO NOTHING""",
        (day, domain, json.dumps(problems), json.dumps(answers), seed_for(day)),
    )
    await conn.commit()
    row = await (
        await conn.execute(
            "SELECT problems, answers FROM daily_challenges WHERE challenge_date = %s", (day,)
        )
    ).fetchone()
    return {"date": day.isoformat(), "problems": row[0], "answers": row[1]}
