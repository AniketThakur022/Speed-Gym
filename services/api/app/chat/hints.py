"""The hint ladder and the answer-leak filter.

RAG-EXP-01/02 hard gate: the chatbot never gives the direct answer. The ladder
uses the SolveAlong steps the content factory already verified, minus the last
step (which IS the answer), with every surface form of the final answer
redacted. `max_level` is bounded by the steps available, so a one-step
problem yields only the framing hint.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..content import extract_numeric_answer

MAX_LEVELS = 3
REDACTION = "▮"


@dataclass
class ProblemContext:
    template_id: str
    question_text: str
    technique: Optional[str] = None
    sutra: Optional[str] = None
    topic: Optional[str] = None
    steps: list[str] = field(default_factory=list)     # operation text per step, in order
    answer_key: Optional[str] = None

    @property
    def answer_numeric(self) -> Optional[float]:
        return extract_numeric_answer(self.answer_key) if self.answer_key else None


def answer_forms(answer_key: Optional[str]) -> set[str]:
    """Every string a learner could recognise the answer by."""
    forms: set[str] = set()
    if not answer_key:
        return forms
    raw = str(answer_key).strip()
    if raw:
        forms.add(raw)
    value = extract_numeric_answer(raw)
    if value is not None:
        if float(value).is_integer():
            n = int(value)
            forms.update({str(n), f"{n:,}", f"{n}.0", f"{n:.1f}", f"{n:.2f}"})
        else:
            forms.update({("%g" % value), f"{value:.2f}", f"{value:.3f}", str(value)})
        forms.add(("%g" % value))
    return {f for f in forms if f and f not in {"0", "1"} or len(raw) > 1}


def redact(text: str, forms: set[str]) -> tuple[str, bool]:
    """Replace every standalone occurrence of an answer form. Word-boundary
    aware so '12' inside '120' is left alone but '= 12' is caught."""
    if not text or not forms:
        return text, False
    changed = False
    for form in sorted(forms, key=len, reverse=True):
        pattern = r"(?<![\w.])" + re.escape(form) + r"(?![\w])"
        new = re.sub(pattern, REDACTION, text)
        if new != text:
            changed = True
            text = new
    return text, changed


def parse_steps(raw: Any) -> list[str]:
    """SolveAlong `steps`/`steps_preview` come as JSON text or lists of
    {step_num, operation, ...}; normalise to operation strings."""
    if raw is None:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return [raw]
    if isinstance(data, dict):
        data = data.get("steps") or []
    out: list[str] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            text = item.get("operation") or item.get("text") or item.get("description") or ""
        else:
            text = str(item)
        text = str(text).strip()
        if text:
            out.append(text)
    return out


def usable_steps(ctx: ProblemContext) -> list[str]:
    """Never the final step: it states the answer."""
    return ctx.steps[:-1] if len(ctx.steps) > 1 else []


def max_level(ctx: ProblemContext) -> int:
    return min(MAX_LEVELS, 1 + len(usable_steps(ctx)))


def ladder(ctx: ProblemContext, level: int) -> dict:
    lvl = max(1, min(int(level), max_level(ctx)))
    forms = answer_forms(ctx.answer_key)
    if lvl == 1:
        method = ctx.technique or ctx.sutra or ctx.topic
        hint = (f"Think about which method fits: this is a {method} problem. "
                "Start by identifying the base or structure the method works from — "
                "don't compute yet." if method else
                "Start by identifying the structure of the problem — what kind of operation "
                "is really being asked — before computing anything.")
    else:
        step = usable_steps(ctx)[lvl - 2]
        hint = f"Step {lvl - 1}: {step}"
    hint, leaked = redact(hint, forms)
    return {"level": lvl, "max_level": max_level(ctx), "hint": hint, "leak_redacted": leaked}
