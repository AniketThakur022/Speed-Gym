"""VMSG Celery app — all async/nightly work runs here, never in the game loop.

Beat schedule mirrors the architecture's job list; pg_cron equivalents run
here in Phase 1 (FIX #5: pg_cron deferred to Phase-2a infra).
"""

import os
import sys
from pathlib import Path

from celery import Celery
from celery.schedules import crontab

# The RAG factory lanes (factory/runs.py) import as top-level `factory.*` and
# use repo-relative data/factory/ paths — this worker is repo-scoped by design.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

app = Celery(
    "vmsg",
    broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    include=["worker.tasks.content", "worker.tasks.maintenance", "worker.tasks.factory"],
)

app.conf.timezone = "UTC"
app.conf.beat_schedule = {
    # Content factory (RAG-owned pipeline; task-name contract shared 2026-09-02)
    "factory-nightly-run": {
        "task": "factory.nightly_run",
        "schedule": crontab(minute=0, hour=0),
    },
    "factory-hourly-run": {
        "task": "factory.hourly_run",
        "schedule": crontab(minute=15),
    },
    # Parametric pre-warming: 100 problems/pattern at 00:00 UTC (GEN cache)
    "prewarm-generated-problems": {
        "task": "worker.tasks.content.prewarm_generated_problems",
        "schedule": crontab(minute=0, hour=0),
    },
    # Nightly content validation sweep (trust-ladder recompute)
    "nightly-content-validation": {
        "task": "worker.tasks.content.validate_content",
        "schedule": crontab(minute=30, hour=0),
    },
    # KPI matview refresh — pg_cron's job, run app-side in Phase 1
    "refresh-kpi-dashboard": {
        "task": "worker.tasks.maintenance.refresh_kpi_views",
        "schedule": 15 * 60,
    },
    # raw_events partition maintenance — pg_partman's job, run app-side
    "raw-events-partition-maintenance": {
        "task": "worker.tasks.maintenance.maintain_raw_events_partitions",
        "schedule": crontab(minute=0, hour=3),
    },
}
