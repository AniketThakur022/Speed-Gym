#!/usr/bin/env python3
"""
Remediate the 5 stubborn subtopics that scored 0.0 during Phase 1C enrichment.

Strategy:
  1. calendar_calculations, mensuration: unwrap nested JSON wrapper and re-score.
  2. chalana_kalanabhyam, gunita_samuccayah, sopantyadvayam: use a hybrid prompt
     with manually-authored seed examples to guide the consensus model.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))

from topic_browser_full_package.scripts.subtopic_explainer_generator import (
    _extract_json_from_response,
    OUTPUT_DIR,
    CONTENT_DIR,
)
from assembly_line.consensus import run_consensus

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("remediate")


def unwrap_and_save(subtopic_id: str) -> dict:
    """Unwrap a JSON file that was wrapped under {subtopic_id: {content}}.

    Some enriched files have extra top-level keys (metadata, subtopic_id) in
    addition to the wrapper key. Detect wrapper by looking for a dict that
    contains quick_ref and techniques_by_difficulty.
    """
    path = OUTPUT_DIR / f"{subtopic_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, val in data.items():
        if isinstance(val, dict) and "quick_ref" in val and "techniques_by_difficulty" in val:
            unwrapped = val.copy()
            unwrapped.setdefault("subtopic_id", subtopic_id)
            # Preserve top-level metadata if it exists and inner doesn't have it
            if "metadata" in data and "metadata" not in unwrapped:
                unwrapped["metadata"] = data["metadata"]
            path.write_text(json.dumps(unwrapped, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info(f"  Unwrapped {subtopic_id} from key '{key}': keys={list(unwrapped.keys())}")
            return unwrapped
    log.info(f"  {subtopic_id}: no wrapper found, leaving as-is")
    return data


HYBRID_SEEDS = {
    "chalana_kalanabhyam": {
        "sutra": "Calana-Kalanābhyām",
        "sutra_sanskrit": "चलनकलनाभ्याम्",
        "translation": "By the Calculus",
        "summary": (
            "Calana-Kalanābhyām (Sutra #9) uses differential calculus for polynomial "
            "factorization. For a polynomial P(x), if a linear factor (x-a) divides P, "
            "then P(a)=0. Higher multiplicities can be detected by successive derivatives."
        ),
        "examples": [
            {
                "problem": "Factorize x² - 5x + 6 using Calana-Kalanābhyām",
                "derivative": "D = 2x - 5",
                "answer": "(x - 2)(x - 3)",
                "explanation": "Roots are x=2,3 from quadratic formula; derivative 2x-5 equals zero at x=2.5 (midpoint of roots)."
            },
            {
                "problem": "Factorize x³ - 6x² + 11x - 6",
                "derivative": "D1 = 3x² - 12x + 11",
                "answer": "(x - 1)(x - 2)(x - 3)",
                "explanation": "P(1)=P(2)=P(3)=0; first derivative vanishes between repeated roots if any."
            },
            {
                "problem": "Solve 7x² - 11x - 7 = 0 using the differential relation",
                "derivative": "D = 14x - 11",
                "answer": "x = (11 ± √317)/14",
                "explanation": "Tirthaji's example: 14x - 11 = ±√317 gives the roots directly."
            },
        ],
        "traps": [
            "Forgetting to verify roots by substitution in the original polynomial.",
            "Assuming a single derivative zero guarantees a factor — check multiplicity.",
            "Applying to polynomials whose roots are irrational without proper handling.",
        ],
    },
    "gunita_samuccayah": {
        "sutra": "Gunitasamuccayaḥ Samuccayagunitaḥ",
        "sutra_sanskrit": "गुणितसमुच्चयः समुच्चयगुणितः",
        "translation": "The Product of the Sum is the Sum of the Product",
        "summary": (
            "Gunita-samuccayah is a verification corollary: the sum of coefficients of a "
            "product equals the product of the sums of coefficients of its factors. "
            "It is NOT a factorization method — use it to check answers after factorization "
            "or multiplication. Distinction: Gunaka-samuccayah is for multiplication, "
            "Gunita-samuccayah is for verification."
        ),
        "examples": [
            {
                "problem": "Verify (x + 7)(x + 9) = x² + 16x + 63",
                "answer": "Verified",
                "explanation": "Sum of coefficients of factors: (1+7)(1+9)=8×10=80. Sum of coefficients of product: 1+16+63=80."
            },
            {
                "problem": "Verify (x + 1)(x + 2)(x + 3) = x³ + 6x² + 11x + 6",
                "answer": "Verified",
                "explanation": "(1+1)(1+2)(1+3)=2×3×4=24; product sum=1+6+11+6=24."
            },
            {
                "problem": "Find missing factor: (x + 2)(x + ?) = x² + 7x + 10",
                "answer": "x + 5",
                "explanation": "Product coefficient sum = 18; first factor sum = 3; missing factor sum = 6 ⇒ x+5."
            },
        ],
        "traps": [
            "Using Gunita-samuccayah as the primary factorization method instead of verification.",
            "Sign errors: for (x - 3), coefficient sum is 1 + (-3) = -2, not 4.",
            "Confusing with Gunaka-samuccayah (multiplication technique).",
        ],
    },
    "sopantyadvayam": {
        "sutra": "Sopāntyadvayamantyam",
        "sutra_sanskrit": "सोपान्त्यद्वयमन्त्यं",
        "translation": "The Ultimate and Twice the Penultimate",
        "summary": (
            "Sopāntyadvayamantyam (Sutra #13) gives a shortcut for equations of the form "
            "(x + a)(x + b) = (x + c)(x + d). Instead of expanding both sides, use "
            "x = (cd - ab) / ((a + b) - (c + d)). For expansion (x+a)(x+b), the result is "
            "x² + x(a+b) + ab."
        ),
        "examples": [
            {
                "problem": "Solve (x + 2)(x + 3) = (x + 4)(x - 1)",
                "answer": "x = -5",
                "explanation": "ab=6, cd=-4, (a+b)=5, (c+d)=3. x = (-4 - 6)/(5 - 3) = -10/2 = -5."
            },
            {
                "problem": "Expand (x + 4)(x + 5)",
                "answer": "x² + 9x + 20",
                "explanation": "a+b=9, ab=20 ⇒ x² + 9x + 20."
            },
            {
                "problem": "Factorize x² + 13x + 42",
                "answer": "(x + 6)(x + 7)",
                "explanation": "Find a,b with a+b=13 and ab=42 ⇒ 6 and 7."
            },
        ],
        "traps": [
            "Sign errors with negative constants in (x - a)(x - b).",
            "Applying to non-(x+a)(x+b) forms without rewriting first.",
            "Confusing with Gunita-samuccayah, which is a verification rule.",
        ],
    },
}


def build_hybrid_prompt(subtopic_id: str, stub: dict, seed: dict) -> str:
    """Build a prompt that injects manual seed content for zero-template Vedic sutras."""
    topic = stub.get("topic", "Vedic Math")
    category = stub.get("category", "Foundation")
    seed_json = json.dumps(seed, indent=2, ensure_ascii=False)
    template = """You are a math educator creating a Quick Reference Card for the subtopic '{subtopic_id}'.

## Subtopic Info
- Topic: {topic}
- Category: {category}
- Sutra: {sutra}
- Sanskrit: {sanskrit}
- Translation: {translation}
- Applicability: pattern_based

## Manually-Authored Seed Content (MUST be preserved and expanded)
{seed_json}

## Required Output
Return a COMPLETE JSON object at the ROOT level matching this exact structure. Replace the example values with content for '{subtopic_id}'. Do NOT omit any section.

{{
  "subtopic_id": "{subtopic_id}",
  "category": "{category}",
  "topic": "{topic}",
  "sutra": "{sutra}",
  "sutra_sanskrit": "{sanskrit}",
  "translation": "{translation}",
  "applicability_type": "pattern_based",
  "quick_ref": {{
    "when_to_use": {{
      "conditions": ["condition 1", "condition 2", "condition 3"],
      "range_rule": "describe the domain"
    }},
    "base_selection_guide": "when to use this technique",
    "the_trick": {{
      "formula_latex": ["formula 1", "formula 2"],
      "variable_definitions": [
        {{"symbol": "x", "meaning": "description"}},
        {{"symbol": "a", "meaning": "description"}}
      ],
      "mental_steps": ["step 1", "step 2", "step 3"],
      "time_saved": "2-3x faster than expanding",
      "difficulty_label": "Intermediate"
    }},
    "quick_example": {{
      "problem": "simple problem",
      "answer": "answer",
      "visual_layout": ["line 1", "line 2", "line 3"],
      "time_estimate_ms": 20000
    }},
    "top_traps": [
      {{"rank": 1, "name": "Trap One", "trap_type": "sign_error", "description": "...", "example": "...", "why_it_happens": "...", "prevention": "..."}},
      {{"rank": 2, "name": "Trap Two", "trap_type": "form_misapplication", "description": "...", "example": "...", "why_it_happens": "...", "prevention": "..."}},
      {{"rank": 3, "name": "Trap Three", "trap_type": "confusion", "description": "...", "example": "...", "why_it_happens": "...", "prevention": "..."}}
    ]
  }},
  "techniques_by_difficulty": {{
    "L1": [{{"technique_id": "{subtopic_id}_l1", "name": "Basic name", "focus": "focus", "example": {{"problem": "...", "answer": "..."}}, "template_count": 3}}],
    "L2": [{{"technique_id": "{subtopic_id}_l2", "name": "Standard name", "focus": "focus", "example": {{"problem": "...", "answer": "..."}}, "template_count": 4, "representative": true}}],
    "L3": [{{"technique_id": "{subtopic_id}_l3", "name": "Advanced name", "focus": "focus", "example": {{"problem": "...", "answer": "..."}}, "template_count": 3}}]
  }},
  "total_techniques": 3,
  "total_templates": 10,
  "metadata": {{
    "author": "3llm_consensus",
    "auto_generated": true,
    "enrichment_date": "2026-06-22",
    "completeness_score": 0.0,
    "review_status": "pending_human_review",
    "content_status": "complete"
  }}
}}

## Critical Rules
1. Output ONLY the JSON object — no markdown fences, no explanation text, no wrapper keys.
2. ALL root-level required keys must be present; do NOT wrap the output under "{subtopic_id}" or any other key.
3. techniques_by_difficulty is REQUIRED and must contain L1, L2, L3 arrays with at least one technique each.
4. ALL mathematical examples MUST be correct. Double-check every answer.
5. For Vedic sutras: include correct Sanskrit transliteration and English translation.
6. top_traps must have exactly 3 entries with rank 1, 2, 3.
7. Use the seed examples as a basis for the quick_example and L1/L2/L3 technique examples.

Return the complete JSON object now."""
    return template.format(
        subtopic_id=subtopic_id,
        topic=topic,
        category=category,
        sutra=seed.get('sutra'),
        sanskrit=seed.get('sutra_sanskrit'),
        translation=seed.get('translation'),
        seed_json=seed_json,
    )


async def enrich_hybrid(subtopic_id: str) -> dict:
    """Run hybrid enrichment for a zero-template Vedic sutra."""
    stub_path = CONTENT_DIR / f"{subtopic_id}.json"
    stub = json.loads(stub_path.read_text(encoding="utf-8"))
    seed = HYBRID_SEEDS[subtopic_id]
    prompt = build_hybrid_prompt(subtopic_id, stub, seed)

    log.info(f"Running hybrid enrichment for {subtopic_id}...")
    result_text = await run_consensus("enrichment", prompt, verbose=False)
    enriched = _extract_json_from_response(result_text)

    # Ensure root-level required keys
    enriched["subtopic_id"] = subtopic_id
    enriched.setdefault("category", stub.get("category", "Foundation"))
    enriched.setdefault("topic", stub.get("topic", "Vedic Math"))
    enriched.setdefault("sutra", seed["sutra"])
    enriched.setdefault("sutra_sanskrit", seed["sutra_sanskrit"])
    enriched.setdefault("translation", seed["translation"])
    enriched.setdefault("applicability_type", "pattern_based")

    out_path = OUTPUT_DIR / f"{subtopic_id}.json"
    out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"  Saved hybrid enrichment to {out_path}")
    return enriched


def is_complete_enrichment(path: Path) -> bool:
    """Check whether an enriched file has the required schema sections."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        isinstance(data, dict)
        and "quick_ref" in data
        and "techniques_by_difficulty" in data
        and isinstance(data.get("techniques_by_difficulty"), dict)
        and all(k in data["techniques_by_difficulty"] for k in ("L1", "L2", "L3"))
    )


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: unwrap wrapper files
    for sid in ("calendar_calculations", "mensuration"):
        unwrap_and_save(sid)

    # Step 2: hybrid enrichment for zero-template Vedic sutras
    # Skip files that are already complete; re-run only incomplete ones.
    for sid in ("chalana_kalanabhyam", "gunita_samuccayah", "sopantyadvayam"):
        out_path = OUTPUT_DIR / f"{sid}.json"
        if is_complete_enrichment(out_path):
            log.info(f"  {sid}: already complete, skipping")
            continue
        try:
            asyncio.run(enrich_hybrid(sid))
        except Exception as e:
            log.error(f"  Hybrid enrichment failed for {sid}: {e}")
            raise

    log.info("Remediation complete.")


if __name__ == "__main__":
    main()
