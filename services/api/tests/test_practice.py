"""Practice-read tests — verification semantics are a contract, not a detail.

Answer-verification (SymPy recomputes the result) and solution-verification
(stage-7 jester review of the walkthrough) must stay separate signals: templates
with correct answers and broken derivations exist in the corpus. Skipped when
the dev graph isn't running.
"""

import socket

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable("localhost", 7687), reason="dev Neo4j not running"
)


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def test_problems_never_expose_a_single_ambiguous_verified_field(client):
    res = client.get("/api/practice/problems", params={"limit": 5})
    assert res.status_code == 200
    problems = res.json()["problems"]
    assert problems, "seeded graph should return problems"

    for p in problems:
        # The raw graph field must not leak: it reads like a solution verdict.
        assert "validation_status" not in p
        assert p["answer_verification"] in {"verified", "flagged", "empty_answer", "unverified"}
        # Solution correctness is only established by the offline jester stage,
        # so nothing served today may claim it.
        assert p["solution_verification"] == "unverified"


def test_seeded_corpus_reports_answer_verification(client):
    res = client.get("/api/practice/problems", params={"limit": 20})
    verdicts = {p["answer_verification"] for p in res.json()["problems"]}
    assert "verified" in verdicts


def test_techniques_route_serves_the_live_skill_graph(client):
    res = client.get("/api/practice/techniques", params={"limit": 3})
    assert res.status_code == 200
    techniques = res.json()["techniques"]
    assert techniques and {"name", "problem_count"} <= set(techniques[0])
