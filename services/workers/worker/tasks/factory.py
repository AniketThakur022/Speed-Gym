"""Content-factory entry points — beat-scheduled task names wired to the
RAG-owned lanes in factory/runs.py (contract shared 2026-09-02, RAG commit
a11a842). Lanes run file-sink until the MERGE window, then swap to DB/Redis
sinks without touching lane logic. Batch-only, zero runtime consumers.

Imports are lazy so the worker boots even if the factory package is absent
(e.g. a stripped deployment); worker/app.py pins CWD to the repo root, which
the lanes' relative data/factory/ paths require.
"""

from worker.app import app


@app.task(name="factory.nightly_run")
def nightly_factory_run() -> dict:
    """Nightly window (00:00 UTC): T2 generation → 7-stage audit → adapter →
    zod-validated delivery → run report."""
    from factory.runs import nightly_run

    return nightly_run()


@app.task(name="factory.hourly_run")
def hourly_factory_run() -> dict:
    """Hourly window (:15): pool check (<50 → make 100) via the T1–T5 ladder;
    T4/T5 stay gated offline until their dependencies exist."""
    from factory.runs import hourly_run

    return hourly_run()
