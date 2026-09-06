"""Mock exams through the API with in-memory question pools bound at the
source seam — the engine never knows which pool served the questions."""

import socket
import uuid
from datetime import timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.mocks.sources import InMemorySource, set_source_override

DSN = "postgresql://vmsg:vmsg@localhost:5432/vmsg"


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable("localhost", 5432), reason="dev Postgres not running")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as c:
        yield c


def _pool(prefix, n, kind, skill="s"):
    items = []
    for i in range(n):
        if kind == "mcq":
            items.append({"question_id": f"{prefix}{i}", "kind": "mcq", "text": f"Q{i}?",
                          "options": [{"id": "a", "text": "yes"}, {"id": "b", "text": "no"}],
                          "correct_answer": "a", "skill": f"{skill}{i % 3}", "difficulty": 1 + i % 5})
        else:
            items.append({"question_id": f"{prefix}{i}", "kind": kind, "text": f"Compute {i}+{i}",
                          "correct_answer": str(2 * i), "skill": f"{skill}{i % 3}", "difficulty": 1 + i % 5})
    return items


@pytest.fixture
def pools():
    set_source_override("cat_varc", InMemorySource(_pool("v", 30, "mcq", "verbal")))
    set_source_override("cat_dilr", InMemorySource(_pool("d", 30, "mcq", "lr")))
    set_source_override("quant", InMemorySource(_pool("q", 40, "numeric", "arith") + _pool("m", 10, "mcq", "arith")))
    yield
    for tag in ("cat_varc", "cat_dilr", "quant", "gmat_verbal"):
        set_source_override(tag, None)


def _register(client, age=None):
    creds = {"email": f"mock-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    if age is not None:
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE users SET age = %s WHERE id = %s::uuid", (age, tokens["user"]["id"]))
            conn.commit()
    return {"Authorization": f"Bearer {tokens['token']}"}, tokens["user"]["id"]


def _configure(client, auth, exam="cat", **kw):
    res = client.post("/api/v1/mocks/configure", json={"exam": exam, **kw}, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


def test_configure_serves_the_cat_pattern_without_answers(client, pools):
    auth, _ = _register(client)
    m = _configure(client, auth)
    assert [s["key"] for s in m["sections"]] == ["varc", "dilr", "qa"]
    assert [len(s["questions"]) for s in m["sections"]] == [24, 20, 22]
    assert m["time_limit_seconds"] == 7200 and m["rules"]["negative_marking"] is True
    assert m["rules"]["ads"] == "disabled" and m["rules"]["sinking_skills"] == "deferred"
    assert all("correct_answer" not in q for s in m["sections"] for q in s["questions"])
    # difficulty ramps upward within a section
    diffs = [q["difficulty"] for q in m["sections"][2]["questions"]]
    assert diffs == sorted(diffs)


def test_missing_pool_is_an_honest_503_naming_the_pool(client, pools):
    auth, _ = _register(client)
    res = client.post("/api/v1/mocks/configure", json={"exam": "gmat"}, headers=auth)
    assert res.status_code == 503 and "gmat_verbal" in res.json()["detail"]


def test_sectional_mode_and_validation(client, pools):
    auth, _ = _register(client)
    m = _configure(client, auth, sections=["qa"], mode="sectional")
    assert [s["key"] for s in m["sections"]] == ["qa"] and m["time_limit_seconds"] == 2400
    assert client.post("/api/v1/mocks/configure", json={"exam": "cat", "sections": ["qa"]}, headers=auth).status_code == 422
    assert client.post("/api/v1/mocks/configure", json={"exam": "cat", "sections": ["nope"], "mode": "sectional"}, headers=auth).status_code == 422


def test_answer_submit_score_results_history(client, pools):
    auth, _ = _register(client)
    m = _configure(client, auth, sections=["qa"], mode="sectional")
    qs = m["sections"][0]["questions"]
    numeric = [q for q in qs if q["kind"] == "numeric"]
    # 5 correct, 2 wrong numeric (no negative), and if any mcq were served answer 1 wrong
    for q in numeric[:5]:
        n = int(q["text"].split()[1].split("+")[0])
        r = client.post("/api/v1/mocks/submit-answer", json={"mock_id": m["mock_id"], "question_id": q["question_id"], "answer": str(2 * n), "time_ms": 30000}, headers=auth)
        assert r.status_code == 200
    for q in numeric[5:7]:
        client.post("/api/v1/mocks/submit-answer", json={"mock_id": m["mock_id"], "question_id": q["question_id"], "answer": "999999", "time_ms": 10000}, headers=auth)
    assert client.post("/api/v1/mocks/submit-answer", json={"mock_id": m["mock_id"], "question_id": "not-mine", "answer": "1"}, headers=auth).status_code == 404
    assert client.get(f"/api/v1/mocks/results/{m['mock_id']}", headers=auth).status_code == 409   # answers withheld

    res = client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"], "section_times": {"qa": 1500}}, headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    sec = body["score"]["sections"][0]
    assert sec["correct"] == 5 and sec["wrong"] == 2 and sec["raw"] == 15.0 and sec["unattempted"] == 15
    assert body["score"]["max_raw"] == 66 and 0 <= body["percentile"] <= 100 and body["peers"] >= 0  # dev DB persists peers across runs
    assert body["xp_awarded"] >= 75 and body["timing"] == "server"
    assert client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"]}, headers=auth).status_code == 409

    results = client.get(f"/api/v1/mocks/results/{m['mock_id']}", headers=auth).json()
    assert results["total_score"] == 15.0 and len(results["review"]) == 22
    assert any(r["correct_answer"] is not None and r["verdict"] is True for r in results["review"])
    hist = client.get("/api/v1/mocks/history", headers=auth).json()["attempts"]
    assert hist[0]["mock_id"] == m["mock_id"] and hist[0]["total_score"] == 15.0


def test_cat_mcq_wrong_costs_one_and_percentile_uses_peers(client, pools):
    auth_a, _ = _register(client)
    auth_b, _ = _register(client)
    for auth, wrong in ((auth_a, 0), (auth_b, 3)):
        m = _configure(client, auth, sections=["varc"], mode="sectional")
        qs = m["sections"][0]["questions"]
        for i, q in enumerate(qs[:10]):
            client.post("/api/v1/mocks/submit-answer", json={"mock_id": m["mock_id"], "question_id": q["question_id"], "answer": "b" if i < wrong else "a"}, headers=auth)
        body = client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"]}, headers=auth).json()
        if wrong:
            assert body["score"]["total_raw"] == 7 * 3 - 3 * 1
            assert body["peers"] >= 1 and body["percentile"] < 100
        else:
            assert body["score"]["total_raw"] == 30


def test_late_answers_are_discarded_unless_timers_are_suppressed(client, pools):
    auth, uid = _register(client)
    m = _configure(client, auth, sections=["qa"], mode="sectional")
    q = next(x for x in m["sections"][0]["questions"] if x["kind"] == "numeric")
    with psycopg.connect(DSN) as conn:   # pretend the exam started 3 hours ago
        conn.execute("UPDATE mock_exam_attempts SET started_at = NOW() - INTERVAL '3 hours' WHERE mock_id = %s", (m["mock_id"],))
        conn.commit()
    n = int(q["text"].split()[1].split("+")[0])
    client.post("/api/v1/mocks/submit-answer", json={"mock_id": m["mock_id"], "question_id": q["question_id"], "answer": str(2 * n)}, headers=auth)
    body = client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"]}, headers=auth).json()
    assert body["late_answers_discarded"] == 1 and body["score"]["total_raw"] == 0

    kid_auth, _ = _register(client, age=11)
    m2 = _configure(client, kid_auth, sections=["qa"], mode="sectional")
    assert m2["timers_suppressed"] is True
    q2 = next(x for x in m2["sections"][0]["questions"] if x["kind"] == "numeric")
    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE mock_exam_attempts SET started_at = NOW() - INTERVAL '3 hours' WHERE mock_id = %s", (m2["mock_id"],))
        conn.commit()
    n2 = int(q2["text"].split()[1].split("+")[0])
    client.post("/api/v1/mocks/submit-answer", json={"mock_id": m2["mock_id"], "question_id": q2["question_id"], "answer": str(2 * n2)}, headers=kid_auth)
    body2 = client.post("/api/v1/mocks/submit", json={"mock_id": m2["mock_id"]}, headers=kid_auth).json()
    assert body2["late_answers_discarded"] == 0 and body2["score"]["total_raw"] == 3


def test_offline_bulk_submit_is_labelled_client_reported_and_bounded(client, pools):
    auth, _ = _register(client)
    m = _configure(client, auth, sections=["qa"], mode="sectional")
    q = next(x for x in m["sections"][0]["questions"] if x["kind"] == "numeric")
    n = int(q["text"].split()[1].split("+")[0])
    too_long = client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"], "answers": [{"question_id": q["question_id"], "answer": str(2 * n)}], "elapsed_seconds": 99999}, headers=auth)
    assert too_long.status_code == 422
    ok = client.post("/api/v1/mocks/submit", json={"mock_id": m["mock_id"], "answers": [{"question_id": q["question_id"], "answer": str(2 * n), "time_ms": 4000}], "elapsed_seconds": 1200}, headers=auth).json()
    assert ok["timing"] == "client_reported" and ok["score"]["total_raw"] == 3


def test_blueprints_report_pool_availability(client, pools):
    auth, _ = _register(client)
    bps = client.get("/api/v1/mocks/blueprints", headers=auth).json()["blueprints"]
    cat = next(b for b in bps if b["key"] == "cat")
    assert all(s["available"] for s in cat["sections"])
    gmat = next(b for b in bps if b["key"] == "gmat")
    assert next(s for s in gmat["sections"] if s["key"] == "verbal")["available"] is False
