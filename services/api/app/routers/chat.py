"""Study chatbot — `POST /api/v1/chat/query` (architecture REST catalogue).

Hints only; never the answer; NO retrieval. Level-1..3 hints come from the
problem's verified steps; a free-text question goes to Claude only when the
`chatbot_llm` flag is on AND the owner key is configured AND the learner has
daily budget left — otherwise the ladder answers. Everything is redacted
against the answer before it leaves.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..chat import budget as budget_mod
from ..chat.hints import (
    ProblemContext,
    answer_forms,
    ladder,
    max_level,
    parse_step_records,
    redact,
    usable_steps,
)
from ..chat.llm import LLMUnavailable, get_llm
from ..config import get_settings
from ..flags import flag_enabled, require_flag
from ..social import xp as xp_mod

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatQuery(BaseModel):
    template_id: str = Field(min_length=1, max_length=200)
    level: int = Field(default=1, ge=1, le=3)
    message: Optional[str] = Field(default=None, max_length=1000)
    prior_hint: Optional[str] = Field(default=None, max_length=1000)


_loader_override = None


def set_problem_loader_override(fn) -> None:
    global _loader_override
    _loader_override = fn


async def load_problem(template_id: str) -> Optional[ProblemContext]:
    """Problem text + answer from :Problem, verified steps from :SolveAlong
    (same template_id, different label — always label-qualify)."""
    if _loader_override is not None:
        return await _loader_override(template_id)
    driver = db.get_neo4j()
    async with driver.session() as neo:
        rec = await (await neo.run(
            """MATCH (p:Problem {template_id: $id})
               OPTIONAL MATCH (sa:SolveAlong {template_id: $id})
               OPTIONAL MATCH (s:Skill)-[:PREREQUISITE_OF]->(p)
               RETURN p.question_text AS text, p.answer_key AS answer, p.technique AS technique,
                      p.sutra AS sutra, p.topic AS topic, sa.steps AS steps, sa.steps_preview AS preview,
                      head(collect(s.name)) AS skill
               LIMIT 1""",
            id=template_id,
        )).single()
    if rec is None or not rec["text"]:
        return None
    steps, step_numbers = parse_step_records(rec["steps"])
    if not steps:
        steps, step_numbers = parse_step_records(rec["preview"])
    return ProblemContext(
        template_id=template_id, question_text=rec["text"], technique=rec["technique"] or rec["skill"],
        sutra=rec["sutra"], topic=rec["topic"], steps=steps, step_numbers=step_numbers,
        answer_key=rec["answer"],
    )


@router.get("/policy")
async def policy(user: dict = Depends(require_flag("chatbot"))) -> dict:
    s = get_settings()
    llm_on = await flag_enabled("chatbot_llm", user["id"]) and get_llm().configured()
    pool = await db.get_pg()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            usage = await budget_mod.usage_today(cur, user["id"], xp_mod.utc_today())
    return {
        "hints_only": True, "rag": False, "llm_enabled": llm_on, "model": s.chat_model if llm_on else None,
        "daily_token_budget": s.chat_daily_token_budget,
        "budget_remaining": budget_mod.remaining(usage, s.chat_daily_token_budget),
        "usage_today": usage,
    }


@router.post("/query")
async def query(body: ChatQuery, user: dict = Depends(require_flag("chatbot"))) -> dict:
    s = get_settings()
    try:
        ctx = await load_problem(body.template_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"content unavailable: {type(exc).__name__}")
    if ctx is None:
        raise HTTPException(status_code=404, detail="unknown problem")

    forms = answer_forms(ctx.answer_key)
    day = xp_mod.utc_today()
    pool = await db.get_pg()
    mode = "hint_ladder"
    out: dict[str, Any]
    tokens_in = tokens_out = 0
    model = None
    leak = False

    want_llm = bool(body.message and body.message.strip())
    llm_on = want_llm and await flag_enabled("chatbot_llm", user["id"]) and get_llm().configured()

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            usage = await budget_mod.usage_today(cur, user["id"], day)
            left = budget_mod.remaining(usage, s.chat_daily_token_budget)

            if llm_on and left <= 0:
                raise HTTPException(status_code=429, detail="daily chat budget exhausted; hints from the ladder remain available")

            if llm_on:
                method = ctx.technique or ctx.sutra or ctx.topic
                try:
                    res = await get_llm().hint(
                        problem_text=ctx.question_text, method=method,
                        # Redacted before they leave the server: the prompt calls
                        # these "verified working", so anything that slips an
                        # answer form through would be authoritative to the model.
                        steps=[redact(st, forms)[0] for st in usable_steps(ctx)],
                        prior_hint=body.prior_hint, user_message=body.message.strip(),
                    )
                except LLMUnavailable:
                    res = None
                if res is None:
                    out = ladder(ctx, body.level)
                    out["fallback"] = "llm_unavailable"
                elif res.refused or not res.text:
                    mode = "refused"
                    out = ladder(ctx, body.level)
                    out["fallback"] = "llm_refused"
                    tokens_in, tokens_out, model = res.input_tokens, res.output_tokens, res.model
                else:
                    mode = "llm"
                    text, leak = redact(res.text, forms)
                    tokens_in, tokens_out, model = res.input_tokens, res.output_tokens, res.model
                    out = {"level": body.level, "max_level": max_level(ctx), "hint": text, "leak_redacted": leak}
            else:
                out = ladder(ctx, body.level)
                if want_llm:
                    out["fallback"] = "llm_disabled"

            leak = bool(out.get("leak_redacted"))
            await budget_mod.record(cur, user["id"], day, mode=mode if mode != "refused" else "llm",
                                    input_tokens=tokens_in, output_tokens=tokens_out)
            await cur.execute(
                """INSERT INTO chat_log (user_id, template_id, mode, level, model, input_tokens, output_tokens, leak_redacted)
                   VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)""",
                (user["id"], body.template_id, mode, out.get("level"), model, tokens_in, tokens_out, leak),
            )
            usage = await budget_mod.usage_today(cur, user["id"], day)
        await conn.commit()

    return {
        "template_id": body.template_id,
        "mode": mode,
        "answer_withheld": True,
        **out,
        "budget_remaining": budget_mod.remaining(usage, s.chat_daily_token_budget),
    }
