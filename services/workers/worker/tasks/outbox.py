"""sync_outbox drain — the Postgres→Neo4j bridge (write path C).

Ingest writes graph *intent* into `sync_outbox` inside the same transaction as
the ledger row. This worker turns that intent into edges. The split is what
makes a Neo4j outage survivable: edges lag, the ledger never loses a write.

Rows are only marked drained after the MERGE succeeds, and every MERGE is
idempotent, so a crash between the MERGE and the status update replays
harmlessly.
"""

import os

from worker.app import app

BATCH_SIZE = 200
MAX_ATTEMPTS = 5


def _pg():
    import psycopg

    return psycopg.connect(
        os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
    )


def _neo4j():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "vmsg-dev-password"),
        ),
    )


@app.task(name="sync.drain_outbox")
def drain_outbox() -> dict:
    drained, failed, skipped = 0, 0, 0
    skip_reasons: dict[str, int] = {}

    with _pg() as conn:
        rows = conn.execute(
            """SELECT id, user_id, event_id, event_type, payload, attempts
               FROM sync_outbox
               WHERE status = 'pending' AND attempts < %s
               ORDER BY created_at
               LIMIT %s""",
            (MAX_ATTEMPTS, BATCH_SIZE),
        ).fetchall()

        if not rows:
            return {"drained": 0, "failed": 0, "skipped": 0, "skip_reasons": {}}

        driver = _neo4j()
        try:
            with driver.session() as neo:
                for row_id, user_id, event_id, event_type, payload, attempts in rows:
                    try:
                        reason = _apply(neo, str(user_id), event_type, payload or {})
                        # A row that wrote no edge is still finished, but it is
                        # recorded as skipped WITH ITS REASON — counting it as a
                        # success would hide events silently missing the graph.
                        conn.execute(
                            """UPDATE sync_outbox
                               SET status = 'drained', drained_at = NOW(), last_error = %s
                               WHERE id = %s""",
                            (reason, row_id),
                        )
                        if reason is None:
                            drained += 1
                        else:
                            skipped += 1
                            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                    except Exception as exc:  # noqa: BLE001 — one bad row must not stall the queue
                        conn.execute(
                            """UPDATE sync_outbox
                               SET attempts = attempts + 1,
                                   last_error = %s,
                                   status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'pending' END
                               WHERE id = %s""",
                            (f"{type(exc).__name__}: {exc}"[:500], MAX_ATTEMPTS, row_id),
                        )
                        failed += 1
                    conn.commit()
        finally:
            driver.close()

    return {"drained": drained, "failed": failed, "skipped": skipped, "skip_reasons": skip_reasons}


def _apply(neo, user_id: str, event_type: str, payload: dict) -> str | None:
    """Translate one event into graph edges.

    Returns None when an edge was written, or a short reason when nothing was.
    That distinction matters: `MATCH` on a missing node produces no rows and no
    error, so without an explicit check a whole class of events would vanish
    while the outbox reported success.

    Every write is a MERGE, so a replayed row converges instead of duplicating.
    """
    if event_type in {"problem_attempt", "problem_solved"}:
        template_id = payload.get("problem_id") or payload.get("template_id")
        if not template_id:
            return "no problem_id in payload"
        summary = neo.run(
            """MERGE (u:User {user_id: $user_id})
               WITH u MATCH (p:Problem {template_id: $template_id})
               MERGE (u)-[c:COMPLETED]->(p)
               SET c.correct = $correct, c.time_ms = $time_ms, c.timestamp = datetime()""",
            user_id=user_id,
            template_id=template_id,
            correct=bool(payload.get("is_correct")),
            time_ms=payload.get("total_time_ms"),
        ).consume()
        wrote = summary.counters.relationships_created or summary.counters.properties_set
        return None if wrote else f"no :Problem with template_id={template_id}"

    if event_type == "session_end":
        states = payload.get("technique_states") or {}
        if not states:
            return "session_end carried no technique_states"
        missing: list[str] = []
        for technique_id, state in states.items():
            level = state.get("pLearned") if isinstance(state, dict) else None
            if level is None:
                continue
            summary = neo.run(
                """MERGE (u:User {user_id: $user_id})
                   WITH u MATCH (s:Skill {name: $technique_id})
                   MERGE (u)-[h:HAS_SKILL_LEVEL]->(s)
                   SET h.level = $level, h.updated_at = datetime()""",
                user_id=user_id,
                technique_id=technique_id,
                level=float(level),
            ).consume()
            if not (summary.counters.relationships_created or summary.counters.properties_set):
                missing.append(technique_id)
        return f"no :Skill named {', '.join(missing)}" if missing else None

    return f"no graph mapping for {event_type}"
