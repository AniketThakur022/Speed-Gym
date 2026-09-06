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
    step_numbers: list[int] = field(default_factory=list)  # matching step_num, for segmenting
    answer_key: Optional[str] = None

    @property
    def answer_numeric(self) -> Optional[float]:
        return extract_numeric_answer(self.answer_key) if self.answer_key else None


# Numeric literals inside an answer key, e.g. "a = 12 and b = 0.4" or "£2,556".
_LITERAL = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _numeric_forms(value: float) -> set[str]:
    forms: set[str] = set()
    if float(value).is_integer():
        n = int(value)
        forms.update({str(n), f"{n:,}", f"{n}.0", f"{n:.1f}", f"{n:.2f}"})
    else:
        forms.update({("%g" % value), f"{value:.2f}", f"{value:.3f}", str(value)})
    forms.add(("%g" % value))
    return forms


def answer_forms(answer_key: Optional[str]) -> set[str]:
    """Every string a learner could recognise the answer by.

    Most live answer keys do NOT parse to a single number — 80.6% of the
    :Problem nodes carrying an answer_key are multi-part ("a = 12 and b = 0.4"),
    carry units or currency ("£2,556", "117.5 cm³"), or hold several parts
    ("(a) 2^6 = 64 (b) 3^4 = 81"). For those, `extract_numeric_answer` returns
    None, and adding only the verbatim key made `redact` a no-op: no hint or
    model output ever contains the whole key, so the bare answer NUMBER went
    straight to the learner. So every numeric literal in the key is a form too.

    0 and 1 are excluded when they were not the whole key: they appear in
    almost any explanation, and redacting them would destroy the hint while
    protecting nothing a learner could not already guess.
    """
    forms: set[str] = set()
    if not answer_key:
        return forms
    raw = str(answer_key).strip()
    if not raw:
        return forms
    forms.add(raw)

    value = extract_numeric_answer(raw)
    if value is not None:
        forms |= _numeric_forms(value)
    else:
        for match in _LITERAL.findall(raw):
            cleaned = match.replace(",", "")
            try:
                literal = float(cleaned)
            except ValueError:
                continue
            if abs(literal) <= 1 and float(literal).is_integer():
                continue          # bare 0/1: too common to redact, nothing to protect
            forms.add(match)      # as written, e.g. "2,556"
            forms |= _numeric_forms(literal)

    return {f for f in forms if f and (f not in {"0", "1"} or len(raw) == 1)}


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


def parse_step_records(raw: Any) -> tuple[list[str], list[int]]:
    """`parse_steps` plus the step_num of each entry (0 when absent)."""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return ([raw], [0]) if raw else ([], [])
    if isinstance(data, dict):
        data = data.get("steps") or []
    texts: list[str] = []
    numbers: list[int] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            text = item.get("operation") or item.get("text") or item.get("description") or ""
            try:
                num = int(item.get("step_num") or item.get("step") or 0)
            except (TypeError, ValueError):
                num = 0
        else:
            text, num = str(item), 0
        text = str(text).strip()
        if text:
            texts.append(text)
            numbers.append(num)
    return texts, numbers


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


def segment_steps(steps: list[str], numbers: Optional[list[int]] = None) -> list[list[str]]:
    """Split a step list into its worked examples.

    :SolveAlong nodes are PAGE-level: `steps_preview` concatenates the steps of
    several worked examples, and `step_num` restarts at 1 for each — true of
    491 of 791 live nodes (62.1%). Without segmenting, "drop the last step"
    withheld only the final example's answer and left every earlier example's
    answer-bearing step in place.
    """
    if not steps:
        return []
    if not numbers or len(numbers) != len(steps):
        return [list(steps)]
    segments: list[list[str]] = []
    current: list[str] = []
    previous: Optional[int] = None
    for text, num in zip(steps, numbers):
        if previous is not None and num <= previous and current:
            segments.append(current)
            current = []
        current.append(text)
        previous = num
    if current:
        segments.append(current)
    return segments


def usable_steps(ctx: ProblemContext) -> list[str]:
    """Never a final step: each worked example's last step states its answer.

    Applied per example, not once over the whole concatenated list — see
    `segment_steps`. Anything still containing a surface form of this problem's
    answer is dropped outright: a mid-example step can state the result too
    ("108 - 93 = 15"), and these strings are handed to the model as verified
    working, so filtering them here is what keeps the answer out of the prompt.
    """
    segments = segment_steps(ctx.steps, ctx.step_numbers)
    kept: list[str] = []
    for segment in segments:
        if len(segment) > 1:
            kept.extend(segment[:-1])
    forms = answer_forms(ctx.answer_key)
    if not forms:
        return kept
    return [s for s in kept if not redact(s, forms)[1]]


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
