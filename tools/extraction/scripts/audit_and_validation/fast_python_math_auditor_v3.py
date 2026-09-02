#!/usr/bin/env python3
"""
Jester Beta — Fast Python Math Auditor v3 (Non-LLM, LaTeX-Aware)
=================================================================
Validates solve_along templates using SymPy on extracted LaTeX.
Extracts math from $...$ inline LaTeX, computes with SymPy, compares.
Handles: integers, negatives, fractions, multi-operand, decimals.

Usage:
    python3 fast_python_math_auditor_v3.py
"""
from __future__ import annotations
import json, re, argparse
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import sympy as sp

TEMPLATES_DIR = Path("/workspace/data/enrichment/templates/solve_along")
REPORT_PATH = Path("/workspace/data/enrichment/fast_python_audit_report_v3.json")
LOG_PATH = Path("/workspace/data/enrichment/fast_python_audit_v3.log")

# ── Logging ──────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── LaTeX Extraction ─────────────────────────────────────────
def extract_latex_math(problem: str) -> str:
    r"""Extract inline math from $...$ and \[...\]. Returns cleaned LaTeX string."""
    parts = problem.split("$")
    inline = []
    text_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            inline.append(part.strip())
        else:
            text_parts.append(part)
    display = re.findall(r"\\\[(.*?)\\\]", problem, re.DOTALL)
    return " ".join(inline + display)

# ── Number extraction (fallback) ──────────────────────────────
def extract_numbers(text: str) -> List[float]:
    text = text.replace(",", "").replace("%", "")
    out = []
    for token in text.replace("$", " ").replace("\\", " ").split():
        token = token.strip(".;:!?()[]{}=")
        try:
            v = sp.sympify(token)
            # Guard: sympify can return a function or class, not a number
            if hasattr(v, 'is_number') and v.is_number:
                out.append(float(v))
        except (sp.SympifyError, TypeError, ValueError, AttributeError):
            pass
    if not out:
        nums = re.findall(r"-?\d+\.?\d*", text)
        for n in nums:
            try:
                out.append(float(sp.sympify(n)))
            except:
                pass
    return out

def extract_final_answer(text: str) -> Optional[float]:
    text = text.replace(",", "").replace("%", "")
    for pattern in [r"=\s*(-?[\d\s]+/[\d\s]+|-?[\d\s]+\.?[\d\s]*)",
                    r"(?:answer|ans)\s*[:=]?\s*(-?[\d\s]+/[\d\s]+|-?[\d\s]+\.?[\d\s]*)",
                    r"=\s*(\\frac\{[^}]+\}\{[^}]+\})"]:
        m = re.search(pattern, text, re.I)
        if m:
            try:
                return float(sp.sympify(m.group(1).replace(" ", "")))
            except:
                pass
    nums = extract_numbers(text)
    return nums[-1] if nums else None

# ── Core Validator ───────────────────────────────────────────
def validate_template(template: dict) -> dict:
    ex = template.get("examples", [{}])[0]
    problem = ex.get("problem_statement", "")
    steps = ex.get("solution", [])
    final_text = ex.get("final_answer", "")
    tech = template.get("concept", {}).get("technique_name", "UNKNOWN")

    latex = extract_latex_math(problem)
    latex_available = bool(latex.strip())

    # --- Primary: SymPy on LaTeX ---
    expected = None
    latex_error = None
    if latex_available:
        try:
            # Clean LaTeX for SymPy: remove \frac wrappers, handle basic operators
            cleaned = latex.replace("\\times", "*").replace("\\cdot", "*").replace("\\div", "/")
            # Let SymPy try to parse it directly
            expr = sp.sympify(cleaned)
            if expr.is_number:
                expected = float(expr)
            else:
                expected = None
                latex_error = "SymPy returned non-numeric expression"
        except Exception as e:
            expected = None
            latex_error = f"SymPy parse error: {type(e).__name__}: {e}"

    # --- Fallback: regex number extraction ---
    if expected is None:
        nums = extract_numbers(problem)
        final_num = extract_final_answer(final_text)
        op_type, expected = detect_operation(problem, nums)
    else:
        final_num = extract_final_answer(final_text)
        nums = extract_numbers(problem)
        op_type = "latex_sympy"

    # --- Final answer check ---
    final_correct = False
    if expected is not None and final_num is not None:
        final_correct = abs(expected - final_num) < 1e-6

    # --- Step checks ---
    step_count = len(steps)
    has_formulas = sum(1 for s in steps if s.get("formula")) >= step_count * 0.3 if step_count > 0 else False
    has_reasoning = sum(1 for s in steps if s.get("reasoning")) >= step_count * 0.5 if step_count > 0 else False

    # --- Keyword match ---
    expected_keywords = {
        "addition": ["add", "sum", "carry", "plus"],
        "subtraction": ["subtract", "borrow", "minus", "difference"],
        "multiplication": ["multiply", "product", "times", "cross"],
        "division": ["divide", "quotient", "remainder"],
        "nikhilam": ["base", "deviation", "cross", "vertical", "complement"],
        "urdhva": ["vertical", "crosswise", "diagonal"],
    }
    keywords = expected_keywords.get(tech.lower(), [])
    if not keywords:
        for k, v in expected_keywords.items():
            if k in tech.lower():
                keywords = v
                break
    ops_text = " ".join(s.get("operation", "").lower() for s in steps)
    keyword_hits = sum(1 for kw in keywords if kw in ops_text)
    keyword_score = keyword_hits / max(len(keywords), 1) if keywords else 1.0

    # --- Score ---
    checks = {
        "latex_extracted": latex_available,
        "latex_computed": expected is not None and op_type == "latex_sympy",
        "has_numbers": len(nums) >= 2 if expected is None else True,
        "has_final_answer": final_num is not None,
        "final_answer_computed": expected is not None,
        "final_answer_correct": final_correct,
        "has_steps": step_count >= 2,
        "has_formulas": has_formulas,
        "has_reasoning": has_reasoning,
        "keyword_match": keyword_score >= 0.3,
    }
    score = sum(1 for v in checks.values() if v) / len(checks)
    status = "validated" if score >= 0.7 else "flagged"

    return {
        "template_id": template.get("template_id"),
        "technique": tech,
        "status": status,
        "score": round(score, 2),
        "operation_detected": op_type,
        "latex_extracted": latex,
        "latex_error": latex_error,
        "expected_answer": expected,
        "actual_answer": final_num,
        "checks": checks,
        "step_count": step_count,
        "keyword_score": round(keyword_score, 2),
        "numbers_found": nums[:5] if expected is None else [],
        "python_audit": True,
    }

def detect_operation(problem: str, nums: List[float]) -> tuple[str, Optional[float]]:
    p = problem.lower()
    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        if "sum of" in p or "total of" in p or ("+" in p and len(nums) > 2):
            return "sum", sum(nums)
        if "product" in p and "sum" not in p:
            result = 1.0
            for n in nums: result *= n
            return "product", result
        if "difference" in p: return "difference", a - b
        if "quotient" in p: return "quotient", a / b if b != 0 else None
        if "remainder" in p: return "remainder", a % b if b != 0 else None
        front = problem[:200]
        if "+" in front and "-" not in front[:20]: return "add", a + b
        if "-" in front and "=" not in front[:10]: return "subtract", a - b
        if "\\times" in front or "multiply" in p or "\\cdot" in front: return "multiply", a * b
        if "\\div" in front or "divide" in p: return "divide", a / b if b != 0 else None
        return "add", a + b
    return "unknown", None

# ── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Fast Python Math Auditor v3 (LaTeX-Aware)")
    parser.add_argument("--book", type=str, default=None)
    args = parser.parse_args()

    LOG_PATH.write_text("", encoding="utf-8")
    log("=" * 60)
    log("FAST PYTHON MATH AUDITOR v3 — Starting")
    log("Method: SymPy on extracted LaTeX — NO LLM cost")
    log("=" * 60)

    pattern = f"{args.book}*_solvealong.jsonl" if args.book else "*_solvealong.jsonl"
    files = sorted(TEMPLATES_DIR.glob(pattern))

    all_results = []
    total = 0

    for fp in files:
        templates = []
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    templates.append(json.loads(line))

        log(f"Book {fp.stem}: {len(templates)} templates")
        for t in templates:
            result = validate_template(t)
            all_results.append(result)
            total += 1
            t["_python_audit_status"] = result["status"]
            t["_python_audit_score"] = result["score"]
            t["_python_audit_details"] = result
            t["_python_audited_at"] = datetime.now().isoformat()

        with open(fp, "w", encoding="utf-8") as f:
            for t in templates:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        log(f"  Done")

    by_status = {}
    by_technique = {}
    correct = flagged = 0
    latex_coverage = 0

    for r in all_results:
        s = r["status"]
        by_status[s] = by_status.get(s, 0) + 1
        if r["checks"]["latex_computed"]:
            latex_coverage += 1
        tech = r["technique"]
        if tech not in by_technique:
            by_technique[tech] = {"total": 0, "correct": 0, "flagged": 0}
        by_technique[tech]["total"] += 1
        if s == "validated":
            by_technique[tech]["correct"] += 1
            correct += 1
        else:
            by_technique[tech]["flagged"] += 1
            flagged += 1

    report = {
        "generated_at": datetime.now().isoformat(),
        "total_templates": total,
        "by_status": by_status,
        "latex_computed_count": latex_coverage,
        "latex_computed_pct": round(latex_coverage / total, 3) if total else 0,
        "by_technique": dict(sorted(by_technique.items(), key=lambda x: -x[1]["total"])[:20]),
        "accuracy": round(correct / total, 3) if total else 0,
        "results": all_results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log(f"\n{'='*60}")
    log("PYTHON AUDIT COMPLETE")
    log(f"  Total: {total}")
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        log(f"  {k}: {v}")
    log(f"  LaTeX computed: {latex_coverage} ({report['latex_computed_pct']:.1%})")
    log(f"  Accuracy: {report['accuracy']:.1%}")
    log(f"  Report: {REPORT_PATH}")
    log(f"{'='*60}")

if __name__ == "__main__":
    main()
