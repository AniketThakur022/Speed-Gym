"""Optional Claude path for the study chatbot — hints only, budgeted.

The model is given the problem, the method and the verified steps WITHOUT the
final step or the answer, and a system prompt whose only job is scaffolding.
Whatever comes back still goes through the answer-leak filter. Injectable so
tests never touch the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from ..config import get_settings

SYSTEM = (
    "You are a study coach inside a maths speed-training app. The learner is working on the "
    "problem below and has asked for help.\n"
    "Hard rules, no exceptions:\n"
    "1. Never state, compute, confirm or deny the final answer, and never state the result of "
    "the last step. If asked directly for the answer, say you can't give it and offer the next hint.\n"
    "2. Give ONE hint at a time: the single next thing to think about or do, in at most three sentences.\n"
    "3. Stay on this problem and this method. No unrelated topics.\n"
    "4. If the learner's own working contains an error, point to WHERE it goes wrong, not what the "
    "right value is.\n"
    "5. Plain text, no markdown headings."
)


@dataclass
class LLMResult:
    text: Optional[str]          # None when the model refused
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    refused: bool = False


class HintLLM(Protocol):
    def configured(self) -> bool: ...
    async def hint(self, *, problem_text: str, method: Optional[str], steps: list[str],
                   prior_hint: Optional[str], user_message: str) -> LLMResult: ...


class ClaudeHintLLM:
    def __init__(self):
        self._client = None

    def configured(self) -> bool:
        return bool(get_settings().anthropic_api_key)

    def _get_client(self):
        if self._client is None:
            import anthropic

            s = get_settings()
            self._client = anthropic.AsyncAnthropic(
                api_key=s.anthropic_api_key, timeout=s.chat_llm_timeout_seconds, max_retries=1
            )
        return self._client

    async def hint(self, *, problem_text, method, steps, prior_hint, user_message) -> LLMResult:
        import anthropic

        s = get_settings()
        context = [f"Problem: {problem_text}"]
        if method:
            context.append(f"Method: {method}")
        if steps:
            context.append("Verified working (the final step is deliberately withheld):\n" +
                           "\n".join(f"- {st}" for st in steps))
        if prior_hint:
            context.append(f"Hint already given: {prior_hint}")
        context.append(f"Learner says: {user_message}")
        client = self._get_client()
        try:
            response = await client.beta.messages.create(
                model=s.chat_model,
                max_tokens=s.chat_max_output_tokens,
                system=SYSTEM,
                messages=[{"role": "user", "content": "\n\n".join(context)}],
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable("rate limited") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"api error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("connection error") from exc
        usage = getattr(response, "usage", None)
        result = LLMResult(
            text=None, model=getattr(response, "model", s.chat_model),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )
        if getattr(response, "stop_reason", None) == "refusal":
            result.refused = True
            return result
        result.text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip() or None
        return result


class LLMUnavailable(Exception):
    pass


_override: Optional[HintLLM] = None


def set_llm_override(llm: Optional[HintLLM]) -> None:
    global _override
    _override = llm


def get_llm() -> HintLLM:
    return _override if _override is not None else ClaudeHintLLM()
