"""CI-safe API tests — no databases required (clients are lazy)."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_ok_without_databases():
    with TestClient(create_app()) as client:
        res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "vmsg-api"


def test_ready_reports_every_dependency_consistently():
    """Readiness must report all three DBs and agree with its own status code,
    whether or not a dev stack happens to be running."""
    with TestClient(create_app()) as client:
        res = client.get("/ready")
    body = res.json()
    assert set(body["checks"]) == {"postgres", "neo4j", "redis"}
    all_healthy = all(v == "healthy" for v in body["checks"].values())
    assert (res.status_code, body["status"]) == (
        (200, "ready") if all_healthy else (503, "degraded")
    )
