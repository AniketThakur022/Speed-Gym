#!/usr/bin/env python3
"""
Shared enrichment utilities used by both enrichment_launcher.py and
subtopic_explainer_generator.py.

This module reduces duplication between the two enrichment pipelines by
providing common JSON extraction, completeness scoring, and validation logic.
"""
import json
import re
from typing import Optional


def extract_json(text: str, subtopic_id: str = "") -> dict:
    """Robust JSON extraction from LLM output.

    Prefers the LARGEST valid JSON object, which tends to be the final
    synthesis after any reasoning/analysis text. Also unwraps the common
    wrapper pattern {"subtopic_id": {<full content>}}.
    """
    if not text or not text.strip():
        raise ValueError("Empty response")

    cleaned = re.sub(r"```(?:json)?\s*\n?", "", text)
    cleaned = re.sub(r"\n?\s*```", "", cleaned)

    valid_jsons: list[tuple[int, dict]] = []
    for start_idx in [m.start() for m in re.finditer(r"\{", cleaned)]:
        depth = 0
        try:
            for i in range(start_idx, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start_idx:i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                valid_jsons.append((len(candidate), obj))
                        except json.JSONDecodeError:
                            pass
                        break
        except Exception:
            continue

    if not valid_jsons:
        raise ValueError(f"No parseable JSON in response (len={len(text)}). "
                         f"Sample: {text[:300]}...")

    valid_jsons.sort(key=lambda x: x[0], reverse=True)
    result = valid_jsons[0][1]

    # Unwrap wrapper pattern: {"subtopic_id": {<full content>}}
    if isinstance(result, dict):
        for key, val in result.items():
            if isinstance(val, dict) and "quick_ref" in val and "techniques_by_difficulty" in val:
                val.setdefault("subtopic_id", key)
                return val
    return result


def compute_completeness_score(data: dict, verified: bool = True) -> float:
    """Compute a 0.0–1.0 completeness score for an enriched subtopic."""
    score = 0.0
    qr = data.get("quick_ref", {})

    conditions = qr.get("when_to_use", {}).get("conditions", [])
    if conditions and conditions != ["Content coming soon"]:
        score += 0.1

    trick = qr.get("the_trick", {})
    if trick.get("formula_latex"):
        score += 0.1
    if trick.get("mental_steps"):
        score += 0.1

    qe = qr.get("quick_example", {})
    if qe.get("problem") and qe.get("answer"):
        score += 0.1
    if qe.get("visual_layout"):
        score += 0.1

    if qr.get("top_traps") and len(qr["top_traps"]) > 0:
        score += 0.1

    techs = data.get("techniques_by_difficulty", {})
    if techs:
        score += 0.1
        if len(techs) >= 2:
            score += 0.05
        if data.get("total_templates", 0) > 0:
            score += 0.05

    if data.get("sutra"):
        score += 0.05
    if data.get("sutra_sanskrit"):
        score += 0.05

    if verified:
        score = min(1.0, score + 0.05)

    return round(min(1.0, score), 2)


def validate_enriched(data: dict, stub_id: str) -> tuple[bool, list[str]]:
    """Validate an enriched subtopic against the expected schema."""
    errors = []

    for f in ["subtopic_id", "category", "topic", "quick_ref"]:
        if f not in data:
            errors.append(f"Missing required: {f}")

    qr = data.get("quick_ref", {})
    if not qr.get("when_to_use", {}).get("conditions"):
        errors.append("quick_ref.when_to_use.conditions missing")

    trick = qr.get("the_trick", {})
    if not trick.get("formula_latex"):
        errors.append("the_trick.formula_latex missing")
    if not trick.get("mental_steps"):
        errors.append("the_trick.mental_steps missing")

    qe = qr.get("quick_example", {})
    if not qe.get("problem") or not qe.get("answer"):
        errors.append("quick_example problem/answer missing")

    traps = qr.get("top_traps", [])
    if len(traps) < 3:
        errors.append(f"top_traps has {len(traps)} entries, need 3")

    techs = data.get("techniques_by_difficulty", {})
    if not techs:
        errors.append("techniques_by_difficulty empty")
    for lvl in ["L1", "L2", "L3"]:
        if lvl not in techs:
            errors.append(f"Missing {lvl}")

    return len(errors) == 0, errors
