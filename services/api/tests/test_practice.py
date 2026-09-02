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


def test_mastery_is_keyed_on_a_graph_skill_not_a_corpus_label(client):
    """Only 14 of 368 corpus `technique` labels match a :Skill name, so keying
    mastery on them accumulates state the graph can never join back. Items must
    carry a `skill` from the existing PREREQUISITE_OF edge, and anything without
    one must be excluded from mastery rather than falling back to a label."""
    res = client.get("/api/v1/practice/session", params={"size": 10})
    assert res.status_code == 200
    items = res.json()["items"]
    assert items

    for item in items:
        assert "skill" in item
        if item["skill"] is None:
            assert item["feeds_mastery"] is False
        # Display labels are passed through verbatim, never turned into an id.
        assert "topic" in item and "technique" in item


def test_most_served_problems_resolve_a_skill(client):
    """98.4% of answerable problems reach a :Skill today; if a change dropped
    that to near zero, mastery would silently stop accumulating."""
    res = client.get("/api/v1/practice/session", params={"size": 20})
    items = res.json()["items"]
    tier1 = [i for i in items if i["source"] == "tier1_static"]
    assert tier1
    with_skill = [i for i in tier1 if i["skill"]]
    assert len(with_skill) / len(tier1) >= 0.8
