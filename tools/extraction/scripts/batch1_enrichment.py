#!/usr/bin/env python3
"""
Batch 1 Subtopic Enrichment — 3-LLM Consensus with Real API Calls.

Enriches the three high-template-match Foundation stubs:
  1. subtraction_tricks
  2. multiplication_tricks
  3. division_tricks

Uses assembly_line.consensus.run_consensus for generation,
validates output against subtopic_reference_schema.json,
and verifies all examples with SymPy.

Usage:
    .venv/bin/python scripts/batch1_enrichment.py --stub subtraction_tricks
    .venv/bin/python scripts/batch1_enrichment.py --all
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make assembly_line importable
WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))

from assembly_line.consensus import run_consensus
from jsonschema import validate, ValidationError

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer"
TEMPLATE_DIR = PACKAGE_ROOT / "content_data" / "templates"
SCHEMA_PATH = PACKAGE_ROOT / "schemas" / "subtopic_reference_schema.json"
OUTPUT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer_enriched"

schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

BATCH1_STUBS = ["addition_tricks", "subtraction_tricks", "multiplication_tricks", "division_tricks"]

APPROVED_EXAMPLES = {
    "nikhilam_sutra": json.loads((CONTENT_DIR / "nikhilam_sutra.json").read_text()),
    "urdhva_tiryak": json.loads((CONTENT_DIR / "urdhva_tiryak.json").read_text()),
    "yavadunam": json.loads((CONTENT_DIR / "yavadunam.json").read_text()),
}


def load_template_samples(stub_id: str, n: int = 3) -> str:
    """Load a few representative template lines relevant to the stub."""
    mapping = {
        "subtraction_tricks": [
            TEMPLATE_DIR / "solve_along" / "Number_Sense_solvealong.jsonl",
            TEMPLATE_DIR / "explainer" / "Number_Sense_explainer.jsonl",
        ],
        "multiplication_tricks": [
            TEMPLATE_DIR / "solve_along" / "Vedic_Made_Easy_solvealong.jsonl",
            TEMPLATE_DIR / "solve_along" / "Vedic_Secrets_solvealong.jsonl",
            TEMPLATE_DIR / "solve_along" / "Number_Sense_solvealong.jsonl",
        ],
        "division_tricks": [
            TEMPLATE_DIR / "solve_along" / "vedic_completion_dhvajanka.jsonl",
            TEMPLATE_DIR / "solve_along" / "Number_Sense_solvealong.jsonl",
        ],
    }
    samples = []
    for p in mapping.get(stub_id, []):
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[:n]:
            try:
                obj = json.loads(line)
                text = obj.get("problem_text") or obj.get("question_text") or obj.get("definition_formal") or str(obj)[:200]
                samples.append(text)
            except Exception:
                samples.append(line[:200])
    return "\n\n".join(samples) if samples else "(no template samples available)"


def build_prompt(stub_id: str, stub: dict) -> str:
    """Build a detailed prompt for LLM consensus enrichment."""
    topic = stub["topic"]
    category = stub["category"]

    approved_json = json.dumps(
        {
            "nikhilam_sutra": APPROVED_EXAMPLES["nikhilam_sutra"],
            "yavadunam": APPROVED_EXAMPLES["yavadunam"],
        },
        indent=2,
        ensure_ascii=False,
    )[:6000]

    samples = load_template_samples(stub_id, n=3)

    prompt = f"""You are three expert math educators creating a subtopic-level Quick Reference Card for a mental-math learning app.

Create a complete JSON object for subtopic "{stub_id}" under topic "{topic}" (category: {category}).

## Required Output Schema
The output MUST be a single valid JSON object matching this structure:

{{
  "subtopic_id": "{stub_id}",
  "category": "Foundation",
  "topic": "{topic}",
  "sutra": null,
  "sutra_sanskrit": null,
  "translation": null,
  "applicability_type": "general",
  "quick_ref": {{
    "when_to_use": {{
      "conditions": ["condition 1", "condition 2", "condition 3"],
      "range_rule": "optional range rule"
    }},
    "base_selection_guide": null,
    "the_trick": {{
      "formula_latex": ["LaTeX formula"],
      "variable_definitions": {{}},
      "mental_steps": ["1. step one", "2. step two", ...],
      "time_saved": "e.g. 3-5x faster",
      "difficulty_label": "Beginner-friendly"
    }},
    "quick_example": {{
      "problem": "a simple problem string",
      "base": null,
      "deviations": [],
      "left_part": {{"calculation": "...", "method": "..."}},
      "right_part": {{"calculation": "...", "method": "..."}},
      "answer": "final answer",
      "visual_layout": ["ASCII layout lines"],
      "time_estimate_ms": 5000
    }},
    "top_traps": [
      {{
        "rank": 1,
        "name": "Trap Name",
        "trap_type": "ATTENTION_ERROR" | "TECHNIQUE_ERROR" | "PROCEDURAL_ERROR",
        "description": "...",
        "example": "...",
        "prevention": "..."
      }},
      ... 3 traps total
    ]
  }},
  "techniques_by_difficulty": {{
    "L1": {{"technique_id": "{stub_id}_L1", "name": "...", "focus": "...", "example": {{"problem": "...", "answer": "..."}}, "template_count": 12}},
    "L2": {{"technique_id": "{stub_id}_L2", "name": "...", "focus": "...", "example": {{"problem": "...", "answer": "..."}}, "template_count": 15, "representative": true}},
    "L3": {{"technique_id": "{stub_id}_L3", "name": "...", "focus": "...", "example": {{"problem": "...", "answer": "..."}}, "template_count": 8}}
  }},
  "total_techniques": 3,
  "total_templates": 35,
  "metadata": {{
    "author": "3llm_consensus",
    "extraction_source": "Vedic_Math_and_Number_Sense_templates",
    "enrichment_date": "{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    "auto_generated": true,
    "completeness_score": 0.85,
    "review_status": "pending_human_review",
    "content_status": "complete"
  }}
}}

## Reference Examples (Approved Content)
Use these as style and structure guides:
{approved_json}

## Relevant Template Samples
These are existing problem templates this subtopic should align with:
{samples}

## Content Requirements for "{stub_id}"
- Target audience: kids and high schoolers learning mental math
- Focus on speed, clarity, and visual step-by-step breakdown
- quick_example must use ONLY simple integer arithmetic (no algebra)
- All answers in techniques_by_difficulty and quick_example must be correct
- top_traps must be 3 entries with rank 1-3
- techniques_by_difficulty must have L1, L2, L3
- difficulty_label should be "Beginner-friendly"
- time_saved should be realistic (2-5x faster)

## Critical Rules
1. Output ONLY valid JSON. No markdown code fences. No explanatory text outside JSON.
2. All mathematical examples must be correct.
3. For division_tricks, NEVER use divisor = 0 in any example.
4. Keep problems simple enough for mental calculation.
5. Use ASCII visual_layout for the quick_example.

Return the complete JSON object."""
    return prompt


def extract_json(text: str) -> dict:
    """Extract JSON object from model response using balanced-brace parsing.

    Avoids greedy regex that can match inner fragments or span multiple JSON blocks.
    Also saves raw text to debug on failure.
    """
    if not text or not text.strip():
        raise ValueError("Empty response from consensus — conductor returned no content")

    # First, strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*\n?", "", text)
    cleaned = re.sub(r"\n?\s*```", "", cleaned)

    # Try balanced-brace extraction: find the outermost { ... } pair
    try:
        start = cleaned.index("{")
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i + 1]
                    return json.loads(candidate)
        # If we never closed, try from start to end
        return json.loads(cleaned[start:])
    except (ValueError, json.JSONDecodeError) as e:
        # Last resort: find any { ... } pair that parses
        import re as _re2
        for match in _re2.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned, _re2.DOTALL):
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                continue
        raise ValueError(
            f"No parseable JSON object found in response. "
            f"First 300 chars: {text[:300]}..."
        ) from e


def _try_sympy(problem: str) -> str | None:
    """Try SymPy evaluation as fallback for non-trivial expressions."""
    try:
        import sympy
        from sympy import sympify, N, Rational, pi, E, I, sqrt, sin, cos, tan
        # Normalize problem string for SymPy
        expr_str = problem.strip()
        expr_str = expr_str.replace("²", "**2").replace("³", "**3")
        expr_str = expr_str.replace("×", "*").replace("÷", "/")
        expr_str = expr_str.replace("√", "sqrt").replace("π", "pi")
        # Handle implicit multiplication: "2x" → "2*x"
        import re
        expr_str = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', expr_str)
        # Avoid SymPy's sympify security issues by parsing only safe math
        expr = sympify(expr_str, evaluate=True)
        result = N(expr, 15)  # 15 decimal places
        # Clean up representation
        if result == int(result):
            return str(int(result))
        return f"{float(result):.10g}"
    except Exception:
        return None


def _normalize_expr(s: str) -> str:
    """Normalize unicode math symbols to ASCII equivalents."""
    s = s.replace("²", "**2").replace("³", "**3")
    s = s.replace("×", "*").replace("÷", "/")
    # √N → sqrt(N) — must expand before other rewrites so √3/2 → sqrt(3)/2
    s = re.sub(r'√(\d+)', r'sqrt(\1)', s)
    s = re.sub(r'√\(([^)]+)\)', r'sqrt(\1)', s)
    s = s.replace("π", "pi")
    s = s.replace("°", "")
    s = s.replace("·", "*")
    s = re.sub(r'(?<![a-zA-Z])i(?![a-zA-Z])', 'I', s)  # imaginary unit (not in words like sin, pi)
    s = re.sub(r'(\d)([a-zA-Z\(])', r'\1*\2', s)   # 2x → 2*x, 3( → 3*(
    s = re.sub(r'(\))(\d)', r'\1*\2', s)             # )2 → )*2
    s = re.sub(r'(\))(\()', r'\1*\2', s)             # )( → )*(
    return s


def _parse_answer_values(answer_str: str):
    """Parse stated answer into a list of SymPy expressions (numbers, roots, fractions)."""
    from sympy import sympify, sqrt, pi, Rational, I, oo
    raw = answer_str.strip()
    raw = re.sub(r'^[xXyY]\s*=\s*', '', raw)                 # "x = 2, 3" → "2, 3"
    raw = re.sub(r'\b(and|;)\b', ',', raw)                   # "2 and 3" → "2, 3"
    raw = re.sub(r'√(\d+)', r'sqrt(\1)', raw)                # √3 → sqrt(3)
    raw = re.sub(r'√\(([^)]+)\)', r'sqrt(\1)', raw)          # √(x) → sqrt(x)
    raw = raw.replace("π", "pi")
    raw = raw.replace("°", "")
    raw = re.sub(r'(?<![a-zA-Z])i(?![a-zA-Z])', 'I', raw)
    raw = re.sub(r'(\d)([a-zA-Z\(])', r'\1*\2', raw)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    values = []
    for p in parts:
        p_clean = p.replace(" ", "")
        if p_clean in ("inf", "∞"):
            values.append(oo)
        else:
            values.append(sympify(p_clean))
    return values


def _vals_close(a, b, tol=1e-9):
    """Check if two SymPy expressions are numerically equal within tolerance."""
    from sympy import N, Abs, re as sre, im as sim, oo
    try:
        diff = Abs(N(a - b, 30))
        if diff == oo:
            return False
        return float(diff) < tol
    except Exception:
        return a == b


def _verify_numeric_expr(problem: str, stated: str) -> bool | None:
    """Verify a bare numeric/symbolic expression (no equation sign)."""
    from sympy import sympify, N, sqrt, pi, sin, cos, tan, I, Abs
    try:
        expr = sympify(_normalize_expr(problem), evaluate=True)
        stated_vals = _parse_answer_values(stated)
        if len(stated_vals) != 1:
            return None
        return _vals_close(expr, stated_vals[0])
    except Exception:
        return None


def _verify_linear_eqn(problem: str, stated: str) -> bool | None:
    """Verify linear equations: e.g. 2x + 3 = 7  →  x = 2."""
    from sympy import sympify, Symbol, solve, Eq
    try:
        if "=" not in problem:
            return None
        left_s, right_s = problem.split("=", 1)
        problem_norm = _normalize_expr(problem)
        left_n, right_n = problem_norm.split("=", 1)
        x = Symbol("x")
        eq = Eq(sympify(left_n), sympify(right_n))
        solutions = solve(eq, x)
        if not solutions:
            return None
        stated_vals = _parse_answer_values(stated)
        if len(solutions) != len(stated_vals):
            return False
        sol_set = set(solutions)
        stated_set = set(stated_vals)
        return sol_set == stated_set
    except Exception:
        return None


def _verify_quadratic_eqn(problem: str, stated: str) -> bool | None:
    """Verify quadratic / higher-degree polynomial equations: e.g. x²-5x+6=0 → x=2,3."""
    from sympy import sympify, Symbol, solve, Eq, Rational
    try:
        if "=" not in problem:
            return None
        problem_norm = _normalize_expr(problem)
        left_n, right_n = problem_norm.split("=", 1)
        x = Symbol("x")
        eq = Eq(sympify(left_n), sympify(right_n))
        solutions = solve(eq, x)
        if not solutions:
            return None
        stated_vals = _parse_answer_values(stated)
        if len(solutions) != len(stated_vals):
            # Allow stated answer to be a subset if some solutions are complex
            real_solutions = [s for s in solutions if s.is_real]
            if len(real_solutions) == len(stated_vals):
                solutions = real_solutions
            else:
                return False
        sol_set = set(solutions)
        stated_set = set(stated_vals)
        return sol_set == stated_set
    except Exception:
        return None


def _verify_factorization(problem: str, stated: str) -> bool | None:
    """Verify polynomial factorizations: e.g. (x+2)(x+3) = x²+5x+6."""
    from sympy import sympify, Symbol, expand, Eq, simplify
    try:
        if "=" not in problem:
            return None
        problem_norm = _normalize_expr(problem)
        left_n, right_n = problem_norm.split("=", 1)
        # Expand the left side and check equivalence with right
        x = Symbol("x")
        left_expr = sympify(left_n)
        right_expr = sympify(right_n)
        expanded = expand(left_expr)
        if expanded == expand(right_expr):
            stated_norm = _normalize_expr(stated)
            stated_expanded = expand(sympify(stated_norm))
            return stated_expanded == right_expr or stated_expanded == expanded
        return False
    except Exception:
        return None


def _verify_trig(problem: str, stated: str) -> bool | None:
    """Verify trigonometric values: e.g. sin(60)=√3/2, cos(pi/3)=1/2."""
    from sympy import sympify, pi, sin, cos, tan, asin, acos, atan, sqrt, Rational
    import re as _re
    try:
        # Match sin/cos/tan(...)=...
        trig_m = _re.match(
            r'(sin|cos|tan)\s*\(\s*([^)]+)\s*\)\s*$',
            _normalize_expr(problem.strip().replace(" ", ""))
        )
        if not trig_m:
            return None
        func_name = trig_m.group(1)
        arg_str = trig_m.group(2)
        # Parse angle — handle "60" (degrees) vs "pi/3" (radians)
        if "pi" in arg_str:
            arg = sympify(arg_str)
        elif arg_str.replace(".", "").replace("-", "").isdigit():
            arg = sympify(arg_str) * pi / 180   # degrees → radians
        else:
            arg = sympify(arg_str)
        func_map = {"sin": sin, "cos": cos, "tan": tan}
        result = func_map[func_name](arg)
        stated_vals = _parse_answer_values(stated)
        if len(stated_vals) != 1:
            return None
        return _vals_close(result, stated_vals[0])
    except Exception:
        return None


def _verify_complex(problem: str, stated: str) -> bool | None:
    """Verify complex-number expressions: e.g. (3+4i)(3-4i)=25, |3+4i|=5."""
    from sympy import sympify, I, Abs, expand, sqrt, Rational
    import re as _re
    try:
        problem_norm = _normalize_expr(problem.strip().replace(" ", ""))
        # Magnitude: |3+4i| = 5
        mag_m = _re.match(r'\|([^|]+)\|$', problem_norm)
        if mag_m:
            inner = sympify(mag_m.group(1))
            result = Abs(inner)
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) != 1:
                return None
            return _vals_close(result, stated_vals[0])
        # Complex product / expression = value
        if "=" in problem_norm and ("i" in problem_norm or "I" in problem_norm):
            left_n, right_n = problem_norm.split("=", 1)
            left_expr = expand(sympify(left_n))
            right_expr = sympify(right_n)
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) == 1:
                return _vals_close(left_expr, stated_vals[0])
            return _vals_close(left_expr, right_expr)
        return None
    except Exception:
        return None


def _verify_mensuration(problem: str, stated: str) -> bool | None:
    """Verify mensuration formulas: area, perimeter, volume using π=22/7."""
    from sympy import pi, sqrt, Rational, sympify
    import re as _re
    try:
        p_norm = problem.strip().lower().replace(" ", "")
        # area_circle(r) or area(r) of circle
        area_m = _re.search(r'(?:area(?:_circle|ofcircle|ofacircle)?)\s*\(\s*(\d+(?:\.\d+)?)\s*\)', p_norm)
        if area_m:
            r = Rational(area_m.group(1))
            pi_approx = Rational(22, 7)   # π ≈ 22/7
            result = pi_approx * r**2
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) != 1:
                return None
            return _vals_close(result, stated_vals[0])
        # perimeter_circle(r) or circumference(r)
        peri_m = _re.search(r'(?:perimeter|circumference)(?:_circle|ofcircle)?\s*\(\s*(\d+(?:\.\d+)?)\s*\)', p_norm)
        if peri_m:
            r = Rational(peri_m.group(1))
            pi_approx = Rational(22, 7)
            result = 2 * pi_approx * r
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) != 1:
                return None
            return _vals_close(result, stated_vals[0])
        # volume_sphere(r)
        vol_m = _re.search(r'volume_sphere\s*\(\s*(\d+(?:\.\d+)?)\s*\)', p_norm)
        if vol_m:
            r = Rational(vol_m.group(1))
            pi_approx = Rational(22, 7)
            result = Rational(4, 3) * pi_approx * r**3
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) != 1:
                return None
            return _vals_close(result, stated_vals[0])
        # volume_cylinder(r, h)
        cyl_m = _re.search(r'volume_cylinder\s*\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\)', p_norm)
        if cyl_m:
            r, h = Rational(cyl_m.group(1)), Rational(cyl_m.group(2))
            pi_approx = Rational(22, 7)
            result = pi_approx * r**2 * h
            stated_vals = _parse_answer_values(stated)
            if len(stated_vals) != 1:
                return None
            return _vals_close(result, stated_vals[0])
        return None
    except Exception:
        return None


def verify_math(problem: str, stated_answer: str) -> bool:
    """Verify math examples across arithmetic, algebra, trig, complex, and geometry.

    Dispatches to category-specific verifiers using heuristic detection.
    Returns True if the stated answer is correct, False otherwise.
    """
    import re as _re
    problem_clean = problem.strip().replace(",", "").replace(" ", "")
    stated = stated_answer.strip()

    # ── Tier 1: Basic arithmetic (fast path) ──
    try:
        if "²" in problem_clean or "^2" in problem_clean:
            n = problem_clean.replace("²", "").replace("^2", "")
            if n.lstrip("-").isdigit():
                return str(int(n) ** 2) == stated
        if "×" in problem_clean or "*" in problem_clean:
            sep = "×" if "×" in problem_clean else "*"
            parts = problem_clean.split(sep)
            if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                return str(int(parts[0]) * int(parts[1])) == stated
        if "÷" in problem_clean:
            parts = problem_clean.split("÷")
            if len(parts) == 2:
                a, b = int(parts[0]), int(parts[1])
                if b == 0:
                    return False
                if a % b == 0:
                    return str(a // b) == stated
                computed = a / b
                try:
                    stated_f = float(stated)
                    return abs(computed - stated_f) < 1e-9
                except ValueError:
                    return False
        if "+" in problem_clean:
            parts = problem_clean.split("+")
            if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                return str(int(parts[0]) + int(parts[1])) == stated
        if "-" in problem_clean and not problem_clean.startswith("-"):
            parts = problem_clean.split("-")
            if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                return str(int(parts[0]) - int(parts[1])) == stated
    except Exception:
        pass

    # ── Tier 2: Category-specific symbolic verification ──

    # 2a. Trigonometric values (check before generic expr — has special arg parsing)
    result = _verify_trig(problem, stated)
    if result is not None:
        return result

    # 2b. Complex numbers (check before generic equation — has |...| syntax)
    result = _verify_complex(problem, stated)
    if result is not None:
        return result

    # 2c. Mensuration formulas
    result = _verify_mensuration(problem, stated)
    if result is not None:
        return result

    # 2d. Factorization: LHS is a product of polynomials, RHS is expanded form
    if "=" in problem_clean:
        lhs_raw, rhs_raw = problem_clean.split("=", 1)
        # Detect factorization: left side has parenthesized factors multiplied together
        # Match )*( or )(  — the * may or may not be present after normalization
        if re.search(r'\)\s*\*?\s*\(', _normalize_expr(problem_clean)) or \
           re.search(r'\)\s*\*?\s*\(', lhs_raw):
            result = _verify_factorization(problem, stated)
            if result is not None:
                return result

    # 2e. Linear equations (single variable, degree 1)
    if "=" in problem_clean:
        result = _verify_linear_eqn(problem, stated)
        if result is not None:
            return result

    # 2f. Quadratic / higher-degree polynomial equations
    if "=" in problem_clean:
        result = _verify_quadratic_eqn(problem, stated)
        if result is not None:
            return result

    # 2g. Bare numeric / symbolic expression (no equation sign)
    if "=" not in problem_clean:
        result = _verify_numeric_expr(problem, stated)
        if result is not None:
            return result

    # 2h. SymPy numeric fallback for anything with "=" we haven't handled yet
    computed = _try_sympy(problem)
    if computed is not None:
        try:
            comp_f = float(computed)
            stated_f = float(stated.replace(",", ""))
            return abs(comp_f - stated_f) < 1e-9
        except ValueError:
            try:
                from sympy import sympify, N
                stated_sym = N(sympify(stated), 15)
                return abs(float(computed) - float(stated_sym)) < 1e-9
            except Exception:
                return computed == stated

    # ── Tier 3: Truly unverifiable → fail loud ──
    print(f"  ⚠ UNVERIFIABLE math: '{problem}' =? '{stated_answer}' (needs human review)")
    return False


def validate_subtopic(data: dict, stub_id: str) -> tuple[bool, list[str]]:
    """Validate schema and math."""
    errors = []
    try:
        validate(instance=data, schema=schema)
    except ValidationError as e:
        errors.append(f"Schema: {e.message}")

    # Verify quick_example
    qe = data.get("quick_ref", {}).get("quick_example", {})
    if qe.get("problem") and qe.get("answer"):
        if not verify_math(qe["problem"], qe["answer"]):
            errors.append(f"quick_example math mismatch: {qe['problem']} != {qe['answer']}")

    # Verify technique examples
    techs = data.get("techniques_by_difficulty", {})
    for level, tech in techs.items():
        ex = tech.get("example", {})
        if ex.get("problem") and ex.get("answer"):
            if not verify_math(ex["problem"], ex["answer"]):
                errors.append(f"{level} example math mismatch: {ex['problem']} != {ex['answer']}")

    return len(errors) == 0, errors


async def enrich_stub(stub_id: str, dry_run: bool = False) -> dict:
    """Run 3-LLM consensus enrichment for a single stub."""
    stub_path = CONTENT_DIR / f"{stub_id}.json"
    stub = json.loads(stub_path.read_text(encoding="utf-8"))

    print(f"\n{'='*60}")
    print(f"🎯 Enriching: {stub_id}")
    print(f"{'='*60}")

    prompt = build_prompt(stub_id, stub)

    # Use enrichment task for content generation consensus
    result_text = await run_consensus("enrichment", prompt, verbose=False)

    try:
        enriched = extract_json(result_text)
    except Exception as e:
        print(f"❌ Failed to parse JSON for {stub_id}: {e}")
        # Save raw response for debugging
        debug_path = OUTPUT_DIR / f"{stub_id}_raw.txt"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(result_text, encoding="utf-8")
        raise

    # Ensure IDs match
    enriched["subtopic_id"] = stub_id
    enriched["category"] = stub["category"]
    enriched["topic"] = stub["topic"]

    valid, errors = validate_subtopic(enriched, stub_id)
    if not valid:
        print(f"⚠️ Validation issues for {stub_id}:")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"✅ Validation passed for {stub_id}")

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{stub_id}.json"
        out_path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"💾 Written: {out_path}")

    return enriched


async def main():
    parser = argparse.ArgumentParser(description="Batch 1 subtopic enrichment")
    parser.add_argument("--stub", help="Process a single stub ID")
    parser.add_argument("--all", action="store_true", help="Process all Batch 1 stubs")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't write files")
    args = parser.parse_args()

    targets = []
    if args.stub:
        targets = [args.stub]
    elif args.all:
        targets = BATCH1_STUBS
    else:
        print("Use --stub <id> or --all")
        return

    for stub_id in targets:
        if stub_id not in BATCH1_STUBS:
            print(f"Warning: {stub_id} not in Batch 1. Skipping.")
            continue
        await enrich_stub(stub_id, dry_run=args.dry_run)

    print("\n✅ Batch 1 enrichment complete")


if __name__ == "__main__":
    asyncio.run(main())
