"""Study chatbot: the answer never leaks — ladder or LLM — and the budget holds."""

import socket
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.chat.hints import ProblemContext, answer_forms, ladder, max_level, parse_steps, redact
from app.chat.llm import LLMResult, LLMUnavailable, set_llm_override
from app.main import create_app
from app.routers import chat as chat_router


# ── pure ─────────────────────────────────────────────────────────────────────

CTX = ProblemContext(
    template_id="t1", question_text="Multiply 98 × 97 using the base method.", technique="Nikhilam",
    steps=["Take base 100: deficits are 2 and 3.", "Cross-subtract: 98 − 3 = 95.", "Multiply deficits: 2 × 3 = 6.",
           "Answer: 9506."],
    answer_key="9506",
)


def test_answer_forms_and_redaction_are_word_bounded():
    forms = answer_forms("9506")
    assert {"9506", "9,506", "9506.0"} <= forms
    text, changed = redact("so it's 9506, not 95060 or 19506", forms)
    assert changed and text == "so it's ▮, not 95060 or 19506"


def test_ladder_never_reveals_the_final_step_or_answer():
    assert max_level(CTX) == 3
    seen = [ladder(CTX, lvl)["hint"] for lvl in (1, 2, 3, 7)]
    assert "9506" not in " ".join(seen)
    assert "Nikhilam" in seen[0] and "deficits are 2 and 3" in seen[1] and "95" in seen[2]
    assert seen[3] == seen[2]                        # clamped to max_level
    one_step = ProblemContext("t2", "5 + 7", steps=["5 + 7 = 12"], answer_key="12")
    assert max_level(one_step) == 1 and "12" not in ladder(one_step, 3)["hint"]


def test_parse_steps_handles_json_text_and_dicts():
    assert parse_steps('[{"step_num": 1, "operation": "a"}, {"step_num": 2, "operation": "b"}]') == ["a", "b"]
    assert parse_steps([{"text": "x"}, "y"]) == ["x", "y"] and parse_steps(None) == []


# ── API ──────────────────────────────────────────────────────────────────────


def _reachable(host, port):
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark_db = pytest.mark.skipif(not (_reachable("localhost", 5432) and _reachable("localhost", 6379)), reason="dev DBs not running")
DSN = "postgresql://vmsg:vmsg@localhost:5432/vmsg"


class FakeLLM:
    def __init__(self, text=None, refused=False, fail=False, tokens=(300, 120)):
        self.text, self.refused, self.fail, self.tokens = text, refused, fail, tokens
        self.calls = []

    def configured(self):
        return True

    async def hint(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise LLMUnavailable("down")
        return LLMResult(text=self.text, refused=self.refused, input_tokens=self.tokens[0],
                         output_tokens=self.tokens[1], model="fake")


@pytest.fixture(scope="module")
def client():
    async def loader(template_id):
        return CTX if template_id == "t1" else None

    chat_router.set_problem_loader_override(loader)
    with TestClient(create_app()) as c:
        yield c
    chat_router.set_problem_loader_override(None)


def _register(client):
    creds = {"email": f"chat-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    return {"Authorization": f"Bearer {tokens['token']}"}, tokens["user"]["id"]


def _flag(name, enabled):
    import asyncio
    from app import flags as flags_service

    with psycopg.connect(DSN) as conn:
        conn.execute("UPDATE feature_flags SET enabled = %s, rollout_pct = 100 WHERE flag_name = %s", (enabled, name))
        conn.commit()
    asyncio.run(flags_service.invalidate())


@pytestmark_db
def test_ladder_over_the_api_and_unknown_problem(client):
    auth, _ = _register(client)
    r = client.post("/api/v1/chat/query", json={"template_id": "t1", "level": 2}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "hint_ladder" and body["answer_withheld"] is True and "9506" not in body["hint"]
    assert body["level"] == 2 and body["max_level"] == 3
    assert client.post("/api/v1/chat/query", json={"template_id": "nope"}, headers=auth).status_code == 404
    pol = client.get("/api/v1/chat/policy", headers=auth).json()
    assert pol["hints_only"] and pol["rag"] is False and pol["llm_enabled"] is False


@pytestmark_db
def test_free_text_without_llm_falls_back_to_the_ladder(client):
    auth, _ = _register(client)
    body = client.post("/api/v1/chat/query", json={"template_id": "t1", "message": "what is the answer?"}, headers=auth).json()
    assert body["mode"] == "hint_ladder" and body["fallback"] == "llm_disabled" and "9506" not in body["hint"]


@pytestmark_db
def test_llm_path_is_redacted_budgeted_and_survives_refusal_or_outage(client):
    auth, uid = _register(client)
    _flag("chatbot_llm", True)
    try:
        leaky = FakeLLM(text="Sure — the answer is 9506. Try cross-subtracting first.")
        set_llm_override(leaky)
        body = client.post("/api/v1/chat/query", json={"template_id": "t1", "message": "just tell me"}, headers=auth).json()
        assert body["mode"] == "llm" and "9506" not in body["hint"] and body["leak_redacted"] is True
        assert "Answer: 9506." not in str(leaky.calls[0]["steps"])           # the final step never reaches the model
        assert body["budget_remaining"] == 20_000 - 420

        set_llm_override(FakeLLM(refused=True))
        body = client.post("/api/v1/chat/query", json={"template_id": "t1", "message": "x"}, headers=auth).json()
        assert body["mode"] == "refused" and body["fallback"] == "llm_refused" and "hint" in body

        set_llm_override(FakeLLM(fail=True))
        body = client.post("/api/v1/chat/query", json={"template_id": "t1", "message": "x"}, headers=auth).json()
        assert body["mode"] == "hint_ladder" and body["fallback"] == "llm_unavailable"

        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE chat_usage SET input_tokens = 30000 WHERE user_id = %s::uuid", (uid,))
            conn.commit()
        set_llm_override(FakeLLM(text="hint"))
        assert client.post("/api/v1/chat/query", json={"template_id": "t1", "message": "x"}, headers=auth).status_code == 429
        # the ladder still works when the budget is gone
        assert client.post("/api/v1/chat/query", json={"template_id": "t1", "level": 1}, headers=auth).status_code == 200
    finally:
        set_llm_override(None)
        _flag("chatbot_llm", False)


@pytestmark_db
def test_chatbot_flag_dark_is_404(client):
    auth, _ = _register(client)
    _flag("chatbot", False)
    try:
        assert client.post("/api/v1/chat/query", json={"template_id": "t1"}, headers=auth).status_code == 404
    finally:
        _flag("chatbot", True)
