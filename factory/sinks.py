#!/usr/bin/env python3
"""Delivery sinks for the factory run lanes.

File artifacts are ALWAYS written (run audit trail). When the stack is up, the
DB/Redis sink additionally lands each delivered item in the Ledger and the warm
tray — that is the operative store the app reads. Drivers are lazy-imported and
any connection failure degrades loudly (report flag), never silently.

Ledger (Postgres `generated_problems`): one row per delivered item,
  generation_hash = params_hash (UNIQUE — DB-level dedup, ON CONFLICT DO NOTHING),
  sympy_validated = stage-3 exact recomputation passed,
  validation_result = {"trust", "consensus", "stages": "1-6_pass"},
  target_time_seconds = delivery.expected_time.

Warm tray (Redis, 24h TTL per the factory PDF):
  factory:tray:<sub_topic>     RPUSH of full zod-valid delivery JSON, EXPIRE 24h
  factory:seen:<params_hash>   dedup marker, EX 86400 (auditor stage-6 window)
"""

import json
import os
import uuid

PG_DSN = os.environ.get("VMSG_PG_DSN", "postgresql://vmsg:vmsg@localhost:5432/vmsg")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TRAY_TTL = 86400


class DbSink:
    """Raises on construction if either store is unreachable — caller falls back."""

    def __init__(self):
        import psycopg
        import redis
        self.pg = psycopg.connect(PG_DSN, autocommit=False)
        self.r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3)
        self.r.ping()

    def write(self, rows: list[dict], run_id: str, lane: str) -> dict:
        inserted = dup_db = 0
        cur = self.pg.cursor()
        for row in rows:
            d, trust, h = row["delivery"], row["trust"], row["params_hash"]
            ex = d["examples"][0]
            cur.execute(
                """INSERT INTO generated_problems
                   (id, template_id, parameters, problem_text, answer, difficulty_level,
                    target_time_seconds, sympy_validated, validation_result, generation_hash,
                    use_count, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,NOW())
                   ON CONFLICT (generation_hash) DO NOTHING""",
                (str(uuid.uuid4()), d["id"],
                 json.dumps({"sub_topic": row["sub_topic"], "run_id": run_id, "lane": lane}),
                 ex["problem_statement"], ex.get("answer"), d["difficulty"],
                 d["expected_time"], True,
                 json.dumps({"trust": trust, "consensus": "pending", "stages": "1-6_pass"}),
                 h))
            if cur.rowcount:
                inserted += 1
                pipe = self.r.pipeline()
                pipe.rpush(f"factory:tray:{row['sub_topic']}", json.dumps(
                    {"trust": trust, "template": d}, ensure_ascii=False))
                pipe.expire(f"factory:tray:{row['sub_topic']}", TRAY_TTL)
                pipe.set(f"factory:seen:{h}", 1, ex=TRAY_TTL)
                pipe.execute()
            else:
                dup_db += 1
        self.pg.commit()
        pool = {k.decode().split(":", 2)[2]: self.r.llen(k)
                for k in self.r.scan_iter("factory:tray:*")}
        return {"sink": "db", "inserted": inserted, "duplicate_in_db": dup_db,
                "tray_depth": pool}

    def close(self):
        self.pg.close()


def deliver(rows: list[dict], run_id: str, lane: str) -> dict:
    """Best-effort DB/Redis landing; loud file-only fallback."""
    if os.environ.get("VMSG_FORCE_FILE_SINK") == "1":
        return {"sink": "file_only", "reason": "VMSG_FORCE_FILE_SINK=1"}
    try:
        sink = DbSink()
    except Exception as e:
        return {"sink": "file_only", "reason": f"stack_unreachable: {e.__class__.__name__}: {e}"}
    try:
        return sink.write(rows, run_id, lane)
    finally:
        sink.close()
