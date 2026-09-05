"""Social batch jobs: daily-challenge generation and ghost expiry.

The daily selection is the API's own pure function (imported from the API
package so the worker and every API node agree without coordination); the
insert is ON CONFLICT DO NOTHING, so whichever ran first wins.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from worker.app import REPO_ROOT, app

_API_ROOT = Path(REPO_ROOT) / "services" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


def _pg():
    import psycopg

    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg"))


@app.task(name="social.generate_daily_challenge")
def generate_daily_challenge(for_date: str | None = None) -> dict:
    from neo4j import GraphDatabase

    from app.social.daily import DAILY_POOL_CYPHER, pick_problems, seed_for

    day = date.fromisoformat(for_date) if for_date else date.today()
    with _pg() as conn:
        if conn.execute("SELECT 1 FROM daily_challenges WHERE challenge_date = %s", (day,)).fetchone():
            return {"status": "exists", "date": day.isoformat()}
        excluded = [
            r[0] for r in conn.execute(
                "SELECT content_id FROM problem_health_scores WHERE trust_level LIKE 'QUARANTINED%%'"
            ).fetchall()
        ]
        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password")),
        )
        with driver.session() as neo:
            candidates = [dict(r) for r in neo.run(DAILY_POOL_CYPHER, excluded=sorted(excluded))]
        driver.close()
        picked = pick_problems(candidates, day)
        if not picked:
            return {"status": "no_candidates", "date": day.isoformat()}
        problems = [{k: v for k, v in p.items() if k != "answer"} for p in picked]
        answers = [p["answer"] for p in picked]
        conn.execute(
            """INSERT INTO daily_challenges (challenge_date, domain, problems, answers, seed)
               VALUES (%s, 'vedic-math', %s, %s, %s) ON CONFLICT (challenge_date) DO NOTHING""",
            (day, json.dumps(problems), json.dumps(answers), seed_for(day)),
        )
        conn.commit()
    return {"status": "generated", "date": day.isoformat(), "problems": len(problems)}


@app.task(name="social.expire_ghosts")
def expire_ghosts() -> dict:
    with _pg() as conn:
        n = conn.execute("DELETE FROM ghost_sessions WHERE expires_at < NOW()").rowcount
        conn.commit()
    return {"status": "ok", "deleted": n}
