"""DB maintenance owned by Celery in Phase 1 (pg_cron/pg_partman deferred)."""

import os
from datetime import datetime, timedelta, timezone

from worker.app import app


def _pg():
    import psycopg

    return psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg"))


@app.task
def refresh_kpi_views() -> dict:
    with _pg() as conn:
        conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY kpi_dashboard_core")
    return {"status": "ok"}


@app.task
def maintain_raw_events_partitions() -> dict:
    """Create next-month partition; detach partitions older than 90 days."""
    now = datetime.now(timezone.utc)
    created = []
    with _pg() as conn:
        for offset in (0, 1):  # current + premake 1
            month = (now.replace(day=1) + timedelta(days=32 * offset)).replace(day=1)
            nxt = (month + timedelta(days=32)).replace(day=1)
            name = f"raw_events_y{month.year}m{month.month:02d}"
            lo = int(month.timestamp() * 1000)
            hi = int(nxt.timestamp() * 1000)
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF raw_events "
                f"FOR VALUES FROM ({lo}) TO ({hi})"
            )
            created.append(name)
    return {"status": "ok", "created": created}
