"""Daily token budget per learner (UTC day) + the cost ledger."""

from __future__ import annotations

from datetime import date


async def usage_today(cur, user_id: str, day: date) -> dict:
    await cur.execute(
        "SELECT requests, hint_requests, llm_requests, input_tokens, output_tokens FROM chat_usage WHERE user_id = %s::uuid AND day = %s",
        (user_id, day),
    )
    row = await cur.fetchone()
    if not row:
        return {"requests": 0, "hint_requests": 0, "llm_requests": 0, "input_tokens": 0, "output_tokens": 0}
    return dict(zip(("requests", "hint_requests", "llm_requests", "input_tokens", "output_tokens"), row))


async def record(cur, user_id: str, day: date, *, mode: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    await cur.execute(
        """INSERT INTO chat_usage (user_id, day, requests, hint_requests, llm_requests, input_tokens, output_tokens)
           VALUES (%s::uuid, %s, 1, %s, %s, %s, %s)
           ON CONFLICT (user_id, day) DO UPDATE SET
             requests = chat_usage.requests + 1,
             hint_requests = chat_usage.hint_requests + EXCLUDED.hint_requests,
             llm_requests = chat_usage.llm_requests + EXCLUDED.llm_requests,
             input_tokens = chat_usage.input_tokens + EXCLUDED.input_tokens,
             output_tokens = chat_usage.output_tokens + EXCLUDED.output_tokens,
             updated_at = NOW()""",
        (user_id, day, 1 if mode == "hint_ladder" else 0, 1 if mode == "llm" else 0, input_tokens, output_tokens),
    )


def remaining(usage: dict, budget: int) -> int:
    return max(0, budget - int(usage["input_tokens"]) - int(usage["output_tokens"]))
