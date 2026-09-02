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


def test_ready_reports_degraded_without_databases():
    with TestClient(create_app()) as client:
        res = client.get("/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert set(body["checks"]) == {"postgres", "neo4j", "redis"}
