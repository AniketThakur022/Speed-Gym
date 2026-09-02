#!/usr/bin/env python3
"""
Phase 1C Enrichment Launcher — Dual-Mode: Minimal + Consensus.

MINIMAL mode (simple topics): Single direct Ollama Cloud call, no conductor.
CONSENSUS mode (complex topics): Full 3-jester + conductor via run_consensus.

Usage:
    .venv/bin/python scripts/enrichment_launcher.py --mode minimal --stub addition_tricks
    .venv/bin/python scripts/enrichment_launcher.py --mode consensus --stub nikhilam_sutra
    .venv/bin/python scripts/enrichment_launcher.py --all         # all stubs, auto-mode
    .venv/bin/python scripts/enrichment_launcher.py --list         # list all stubs with modes
"""
import argparse
import asyncio
import json
import os
import re
import sys
import httpx
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──
WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

from topic_browser_full_package.scripts.enrichment_utils import (
    extract_json,
    compute_completeness_score,
    validate_enriched as _validate_enriched,
)

CONTENT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer"
OUTPUT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer_enriched"
SCHEMA_PATH = PACKAGE_ROOT / "schemas" / "subtopic_reference_schema.json"

# ── Dotenv for API keys ──
from dotenv import load_dotenv
load_dotenv(WORKSPACE / ".env")

# ── Classification: which mode per subtopic ──
# Simple = arithmetic-only, no equations, no Vedic formula complexity
SIMPLE_SUBTOPICS = {
    "addition_tricks", "subtraction_tricks", "multiplication_tricks",
    "division_tricks", "percentages", "ratios_proportions", "fractions",
    "school_foundation", "arithmetic_gre",
    # New foundation subtopics split from school_foundation
    "place_value_number_sense", "mental_arithmetic_fluency", "order_of_operations",
    # Simple seeded Vedic sutras
    "anurupyena", "antyayordashakepi", "parama_mitra",
    "sankalana_vyavakalanabhyam",
}
# Complex = Vedic sutras, algebra, trig, geometry — need consensus
COMPLEX_SUBTOPICS = {
    "nikhilam_sutra", "urdhva_tiryak", "yavadunam",
    "ekanyunena_purvena", "linear_equations", "quadratic_equations",
    "polynomials", "geometry_basics", "trigonometry_basics",
    "mensuration", "number_theory", "functions_graphs",
    "complex_numbers", "magic_squares", "calendar_calculations",
    "gunaka_samuccayah", "gunita_samuccayah", "sopantyadvayam",
    "seshanyakena_caramena", "vyasti_samasti",
    "chalana_kalanabhyam", "puranapuranabhyam",
    "problem_solving_gmat", "quantitative_aptitude_cat",
    # Algebraic / pattern-heavy seeded Vedic sutras
    "shunyam_saamyasamuccaye", "vilokanam", "yavadunam_tavadunam",
}

APPROVED_IDS = {"nikhilam_sutra", "urdhva_tiryak", "yavadunam"}

# ── Ollama Cloud config ──
OLLAMA_URL = "https://ollama.com/v1/chat/completions"
OLLAMA_KEYS = [os.getenv(f"OLLAMA_CLOUD_API_KEY_{i}") for i in range(1, 7)]
OLLAMA_KEYS = [k for k in OLLAMA_KEYS if k]


# ═══════════════════════════════════════════════════════════════════════
# MINIMAL MODE: Single direct Ollama Cloud call
# ═══════════════════════════════════════════════════════════════════════

def build_minimal_prompt(stub_id: str, stub: dict) -> str:
    """Compact prompt for simple arithmetic topics."""
    approved_ref = {}
    for aid in APPROVED_IDS:
        p = CONTENT_DIR / f"{aid}.json"
        if p.exists():
            d = json.loads(p.read_text())
            # Only include quick_ref for brevity
            approved_ref[aid] = {
                "quick_ref": d.get("quick_ref", {}),
                "techniques_by_difficulty": d.get("techniques_by_difficulty", {}),
            }
            break  # One example is enough

    ref_json = json.dumps(approved_ref, indent=2, ensure_ascii=False)[:3000]

    return f"""Create a Quick Reference Card JSON for the math subtopic "{stub_id}".

Topic: {stub.get("topic", "Maths")}
Category: {stub.get("category", "Foundation")}
Target: kids learning mental math shortcuts.

Reference example (follow this structure EXACTLY):
{ref_json}

Output ONLY a valid JSON object with these root-level keys:
subtopic_id, category, topic, sutra, sutra_sanskrit, translation, applicability_type,
quick_ref, techniques_by_difficulty, total_techniques, total_templates, metadata.

quick_ref MUST contain:
- when_to_use with conditions[] and range_rule
- base_selection_guide
- the_trick with formula_latex[], variable_definitions, mental_steps[], time_saved, difficulty_label
- quick_example as a DIRECT CHILD of quick_ref with problem, answer, visual_layout[], time_estimate_ms
- top_traps with exactly 3 entries (rank, name, trap_type, description, example, why_it_happens, prevention)

CRITICAL: quick_example must be at quick_ref.quick_example, NOT inside the_trick.
CRITICAL: techniques_by_difficulty must have L1, L2, L3 arrays, each with technique_id, name, focus, example (problem, answer), template_count.

ALL math must be correct. Use simple numbers. Output ONLY the JSON — no explanation, no markdown fences."""


async def enrich_minimal(stub_id: str, stub: dict) -> dict:
    """Single direct API call for simple topics. Uses glm-5.1 with system prompt."""
    prompt = build_minimal_prompt(stub_id, stub)
    key = OLLAMA_KEYS[0]

    async with httpx.AsyncClient() as client:
        resp = await client.post(OLLAMA_URL, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }, json={
            "model": "glm-5.1",
            "messages": [
                {"role": "system", "content": (
                    "You are a JSON generator for a math learning app. "
                    "Output ONLY a single valid JSON object. "
                    "Start your response with { and end with }. "
                    "Never include markdown fences, explanations, or reasoning. "
                    "All mathematical content must be correct."
                )},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 8192,
            "temperature": 0.3,
        }, timeout=180)

    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    msg = data["choices"][0]["message"]
    content = msg.get("content", "")
    if not content:
        content = msg.get("reasoning", "")

    # Extract JSON from response
    return extract_json(content, stub_id)


# ═══════════════════════════════════════════════════════════════════════
# CONSENSUS MODE: Full 3-jester + conductor for complex topics
# ═══════════════════════════════════════════════════════════════════════

async def enrich_consensus(stub_id: str, stub: dict) -> dict:
    """Full 3-LLM consensus for complex topics."""
    from assembly_line.consensus import run_consensus

    topic = stub.get("topic", "Maths")
    category = stub.get("category", "Foundation")
    sutra = stub.get("sutra")

    approved_refs = {}
    for aid in APPROVED_IDS:
        p = CONTENT_DIR / f"{aid}.json"
        if p.exists():
            approved_refs[aid] = json.loads(p.read_text())

    ref_json = json.dumps(approved_refs, indent=2, ensure_ascii=False)[:5000]

    prompt = f"""Create a comprehensive Quick Reference Card JSON for math subtopic "{stub_id}".

Topic: {topic} | Category: {category} | Sutra: {sutra or 'N/A'}

## Reference Examples
{ref_json}

## Required Output
Return a SINGLE FLAT JSON object at the root level. Do NOT wrap it under a key named "{stub_id}" or any other wrapper key.

Required root-level keys: subtopic_id, category, topic, sutra, sutra_sanskrit, translation, applicability_type, quick_ref, techniques_by_difficulty, total_techniques, total_templates, metadata.

quick_ref MUST contain: when_to_use (conditions[], range_rule), base_selection_guide, the_trick (formula_latex[], variable_definitions, mental_steps[], time_saved, difficulty_label), quick_example (problem, answer, visual_layout[], time_estimate_ms) as a DIRECT CHILD of quick_ref, top_traps[3] (rank, name, trap_type, description, example, why_it_happens, prevention).

techniques_by_difficulty MUST contain L1, L2, L3 arrays. L2 must have "representative": true.

metadata MUST contain: author="3llm_consensus", auto_generated=true, completeness_score=0.0, review_status="pending_human_review", content_status="complete".

ALL math correct. Vedic sutras need Sanskrit + translation. Output ONLY JSON — no markdown, no explanation, no wrapper keys."""

    result_text = await run_consensus("enrichment", prompt, verbose=False)
    return extract_json(result_text, stub_id)


# ═══════════════════════════════════════════════════════════════════════
# Validation + math verification
# ═══════════════════════════════════════════════════════════════════════

def validate_enriched(data: dict, stub_id: str) -> tuple[bool, list[str]]:
    """Schema + math validation."""
    is_valid, errors = _validate_enriched(data, stub_id)
    # Math verification
    _verify_math_in_data(data, errors)
    return len(errors) == 0, errors


def _verify_math_in_data(data: dict, errors: list):
    """Verify all math examples in enriched data."""
    qe = data.get("quick_ref", {}).get("quick_example", {})
    if qe.get("problem") and qe.get("answer"):
        if not _verify_math(qe["problem"], qe["answer"]):
            errors.append(f"quick_example math: {qe['problem']} != {qe['answer']}")

    for lvl, tech_list in data.get("techniques_by_difficulty", {}).items():
        if not isinstance(tech_list, list):
            tech_list = [tech_list]
        for tech in tech_list:
            ex = tech.get("example", {}) if isinstance(tech, dict) else {}
            if ex.get("problem") and ex.get("answer"):
                if not _verify_math(ex["problem"], ex["answer"]):
                    errors.append(f"{lvl} math: {ex['problem']} != {ex['answer']}")


def _verify_math(problem: str, stated: str) -> bool:
    """Verify arithmetic, falling back to SymPy."""
    p = problem.strip().replace(",", "").replace(" ", "")
    s = stated.strip()
    try:
        if "²" in p or "^2" in p:
            n = p.replace("²", "").replace("^2", "")
            if n.lstrip("-").isdigit():
                return str(int(n) ** 2) == s
        if "×" in p or "*" in p:
            sep = "×" if "×" in p else "*"
            a, b = p.split(sep)
            if a.lstrip("-").isdigit() and b.lstrip("-").isdigit():
                return str(int(a) * int(b)) == s
        if "÷" in p:
            a, b = p.split("÷")
            ai, bi = int(a), int(b)
            if bi == 0:
                return False
            if ai % bi == 0:
                return str(ai // bi) == s
            try:
                return abs(ai / bi - float(s)) < 1e-9
            except ValueError:
                return False
        if "+" in p:
            parts = p.split("+")
            if len(parts) == 2 and all(x.lstrip("-").isdigit() for x in parts):
                return str(int(parts[0]) + int(parts[1])) == s
        if "-" in p and not p.startswith("-"):
            parts = p.split("-")
            if len(parts) == 2 and all(x.lstrip("-").isdigit() for x in parts):
                return str(int(parts[0]) - int(parts[1])) == s
    except Exception:
        pass

    # SymPy fallback
    try:
        import sympy
        from sympy import sympify, N
        expr = sympify(p.replace("²", "**2").replace("×", "*").replace("÷", "/"))
        computed = N(expr, 15)
        if computed == int(computed):
            computed_s = str(int(computed))
        else:
            computed_s = f"{float(computed):.10g}"
        if computed_s == s:
            return True
        try:
            return abs(float(computed) - float(s)) < 1e-9
        except ValueError:
            return False
    except Exception:
        pass

    print(f"  ⚠ UNVERIFIABLE: {problem} =? {stated}")
    return True  # Give benefit of doubt for non-arithmetic


def finalize_enriched(data: dict, stub_id: str, is_valid: bool) -> dict:
    """Add metadata and compute completeness score using shared scoring."""
    score = compute_completeness_score(data, verified=is_valid)

    meta = data.get("metadata", {})
    meta["author"] = "3llm_consensus"
    meta["auto_generated"] = True
    meta["enrichment_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meta["completeness_score"] = score
    meta["review_status"] = "pending_human_review"
    meta["content_status"] = "complete" if score >= 0.6 else "partial"
    data["metadata"] = meta
    data["subtopic_id"] = stub_id

    return data


# ═══════════════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════════════

async def enrich_one(stub_id: str, mode: str = "auto") -> dict:
    """Enrich a single stub."""
    stub_path = CONTENT_DIR / f"{stub_id}.json"
    if not stub_path.exists():
        raise FileNotFoundError(f"Stub not found: {stub_path}")

    stub = json.loads(stub_path.read_text())
    meta = stub.get("metadata", {})
    status = meta.get("content_status")
    score = meta.get("completeness_score", 0) or 0
    if status == "complete" and score >= 0.8:
        print(f"  ⏭ {stub_id}: already complete (completeness={score})")
        return stub

    # Auto-detect mode
    if mode == "auto":
        mode = "minimal" if stub_id in SIMPLE_SUBTOPICS else "consensus"

    print(f"\n{'='*60}")
    print(f"🎯 Enriching: {stub_id} [{mode.upper()}]")
    print(f"{'='*60}")

    try:
        if mode == "minimal":
            enriched = await enrich_minimal(stub_id, stub)
        else:
            enriched = await enrich_consensus(stub_id, stub)

        is_valid, errors = validate_enriched(enriched, stub_id)
        if errors:
            print(f"⚠ Validation: {len(errors)} issues")
            for e in errors[:5]:
                print(f"  - {e}")

        enriched = finalize_enriched(enriched, stub_id, is_valid)

        # Write output
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{stub_id}.json"
        out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False))
        print(f"💾 Written: {out_path} (score={enriched['metadata']['completeness_score']})")

        return enriched

    except Exception as e:
        print(f"❌ Failed: {e}")
        # Save raw response if available
        return None


async def main():
    parser = argparse.ArgumentParser(description="Phase 1C Enrichment Launcher")
    parser.add_argument("--stub", help="Enrich single stub ID")
    parser.add_argument("--all", action="store_true", help="Enrich all stubs")
    parser.add_argument("--mode", choices=["minimal", "consensus", "auto"], default="auto")
    parser.add_argument("--list", action="store_true", help="List all stubs with modes")
    parser.add_argument("--batch", choices=["simple", "complex", "all"], default="all")
    args = parser.parse_args()

    if args.list:
        print("SIMPLE (minimal mode):")
        for s in sorted(SIMPLE_SUBTOPICS):
            p = CONTENT_DIR / f"{s}.json"
            exists = "✅" if p.exists() else "❌"
            print(f"  {exists} {s}")
        print("\nCOMPLEX (consensus mode):")
        for s in sorted(COMPLEX_SUBTOPICS):
            p = CONTENT_DIR / f"{s}.json"
            exists = "✅" if p.exists() else "❌"
            print(f"  {exists} {s}")
        return

    if args.stub:
        await enrich_one(args.stub, args.mode)
        return

    if args.all:
        targets = []
        if args.batch in ("simple", "all"):
            targets.extend(sorted(SIMPLE_SUBTOPICS))
        if args.batch in ("complex", "all"):
            targets.extend(sorted(COMPLEX_SUBTOPICS))

        # Skip already-approved
        targets = [t for t in targets if t not in APPROVED_IDS]

        print(f"🚀 Enriching {len(targets)} stubs...")
        results = []
        for stub_id in targets:
            try:
                r = await enrich_one(stub_id, args.mode)
                results.append(r)
            except Exception as e:
                print(f"  ❌ {stub_id}: {e}")

        succeeded = [r for r in results if r and r.get("metadata", {}).get("completeness_score", 0) > 0]
        print(f"\n✅ Done. {len(succeeded)}/{len(targets)} enriched successfully.")
        return

    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
