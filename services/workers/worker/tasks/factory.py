"""Content-factory entry points — the two beat-scheduled task names the RAG
workstream registers its pipeline under. The names below are the CONTRACT
(shared with the RAG chat 2026-09-02); implementations are RAG-owned modules
invoked from here. Factory work is batch-only with zero runtime consumers.
"""

from worker.app import app


@app.task(name="factory.nightly_run")
def nightly_factory_run() -> dict:
    """Nightly window (00:00 UTC): 6-station ingestion, 7-stage auditor,
    trust-ladder promotion sweep, Strategy-A closure rebuild + shadow diff."""
    return {"status": "stub", "note": "RAG-owned pipeline plugs in here"}


@app.task(name="factory.hourly_run")
def hourly_factory_run() -> dict:
    """Hourly window: T1–T5 generation ladder top-ups (T3 sibling bridging,
    template refresh), bounded by the nightly audit's trust gates."""
    return {"status": "stub", "note": "RAG-owned pipeline plugs in here"}
