#!/usr/bin/env python3
"""
Jester Prime — Multi-LLM Consensus Math Validator v3
========================================================
Validates solve_along templates using 3 independent LLM validators.
Consensus rule: 2-of-3 agreement wins. Dissent flagged for review.

Models (OpenRouter, FREE tier):
  Alpha: deepseek/deepseek-v4-flash    (math primary)
  Beta:  qwen/qwen3-235b-a22b-2507     (cross-check)
  Gamma: google/gemini-2.5-flash-lite-preview-09-2025 (edge-case hunter)

Usage:
    python3 consensus_math_validator_v3.py [--limit N] [--book BookName]
"""
from __future__ import annotations
import json, os, sys, time, re, argparse, hashlib
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
import requests
from dotenv import load_dotenv

# Load env vars
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Configuration ──────────────────────────────────────────────
OLLAMA_URL = "https://ollama.com/v1/chat/completions"

MODELS = {
    "alpha": "cogito-2.1:671b",          # math primary
    "beta":  "qwen3-vl:235b-instruct",   # cross-check (good JSON)
    "gamma": "deepseek-v4-flash",         # edge-case hunter
}

KEYS = [
    os.getenv("OLLAMA_CLOUD_API_KEY", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_2", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_3", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_4", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_5", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_6", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_7", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_8", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_9", ""),
    os.getenv("OLLAMA_CLOUD_API_KEY_10", ""),
]
KEYS = [k for k in KEYS if k]

TEMPLATES_DIR = Path("/workspace/data/enrichment/templates/solve_along")
REPORT_PATH = Path("/workspace/data/enrichment/math_validation_report_v3.json")
CHECKPOINT_PATH = Path("/workspace/data/enrichment/.math_validator_checkpoint.json")
LOG_PATH = Path("/workspace/data/enrichment/math_validator_v3.log")

MAX_WORKERS = 2          # concurrent templates (reduce to avoid rate limits)
LLM_TIMEOUT = 90         # seconds per LLM call
RETRIES = 3
CHECKPOINT_EVERY = 25
TEMPERATURE = 0.0
INTER_TEMPLATE_DELAY = 1.5  # seconds between template submissions

# ── Logging ──────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── Key rotation ─────────────────────────────────────────────
_key_idx = 0
_key_lock = __import__("threading").Lock()

def next_key() -> str:
    global _key_idx
    with _key_lock:
        if not KEYS:
            return ""
        k = KEYS[_key_idx % len(KEYS)]
        _key_idx += 1
    return k

# ── LLM Caller ───────────────────────────────────────────────
def call_llm(prompt: str, model_id: str, max_tokens: int = 800) -> Optional[dict]:
    """Call one LLM. Return parsed JSON dict or None."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }
    for attempt in range(RETRIES):
        key = next_key()
        if not key:
            log("  ⚠️ No API keys available")
            return None
        try:
            resp = requests.post(
                OLLAMA_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=LLM_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
                # Strip markdown
                raw = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
                raw = re.sub(r"```", "", raw).strip()
                # Find JSON object
                s = raw.find("{")
                e = raw.rfind("}")
                if s >= 0 and e > s:
                    raw = raw[s:e+1]
                try:
                    parsed = json.loads(raw)
                    parsed["_model"] = model_id
                    parsed["_tokens"] = data.get("usage", {}).get("total_tokens", 0)
                    return parsed
                except json.JSONDecodeError:
                    if attempt == RETRIES - 1:
                        return None
                    time.sleep(2 ** attempt)
            elif resp.status_code == 429:
                log(f"  ⏳ Rate limit ({model_id}, attempt {attempt+1})")
                time.sleep(30 * (attempt + 1))
            else:
                log(f"  ⚠️ HTTP {resp.status_code} from {model_id}")
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            log(f"  ⚠️ Exception calling {model_id}: {type(e).__name__}")
            time.sleep(5 * (attempt + 1))
    return None

# ── Prompt Builder ─────────────────────────────────────────────
def build_validation_prompt(template: dict) -> str:
    """Build a deterministic, context-rich prompt for math validation."""
    concept = template.get("concept", {})
    tech = concept.get("technique_name", "UNKNOWN")
    topic = concept.get("topic", "UNKNOWN")
    sub = concept.get("sub_topic", "UNKNOWN")
    diff = template.get("difficulty", "?")
    cls = template.get("cognitive_load_score", "?")

    # Build step preview + extract structured fields
    ex = template.get("examples", [{}])[0]
    problem_raw = ex.get("problem_statement", "")
    steps = ex.get("solution", [])
    final_ans = ex.get("final_answer", "")

    # Separate plain-text prose from LaTeX math
    import re as _re_local
    # Inline math: split by $, odd indices are LaTeX
    parts = problem_raw.split('$')
    inline_math = []
    text_parts = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            inline_math.append(part.strip())
        else:
            text_parts.append(part)
    # Reconstruct text with [MATH] placeholders for inline math
    display_math = _re_local.findall(r'\\\[(.*?)\\\]', problem_raw)
    reconstructed = []
    for i, txt in enumerate(text_parts):
        reconstructed.append(txt)
        if i < len(inline_math):
            reconstructed.append('[MATH]')
    problem_text = ' '.join(' '.join(reconstructed).split())
    # Remove display math markers from text too
    for dm in display_math:
        problem_text = problem_text.replace(f'\\[{dm}\\]', '[MATH]')
    function_latex = ' '.join(inline_math + display_math)

    step_text = ""
    for step in steps:
        op = step.get("operation", "")
        formula = step.get("formula", "")
        reasoning = step.get("reasoning", "")
        step_text += f"\nStep {step['step_num']}:\n"
        step_text += f"  Operation: {op}\n"
        if formula:
            step_text += f"  Formula: {formula}\n"
        if reasoning:
            step_text += f"  Reasoning: {reasoning}\n"

    prompt = f"""You are a rigorous mathematical auditor. Validate the following worked example for correctness.

TECHNIQUE: {tech}
TOPIC: {topic} / {sub}
DIFFICULTY: {diff}/5  COGNITIVE_LOAD: {cls}/5

PROBLEM TEXT (prose):
{problem_text}

PROBLEM MATH (LaTeX):
{function_latex}

FINAL ANSWER:
{final_ans}

SOLUTION STEPS:{step_text}

INSTRUCTIONS:
1. Independently compute the correct answer to the problem using the LaTeX math provided.
2. Check whether the FINAL ANSWER matches your computed answer.
3. Check whether EACH solution step is mathematically correct and logically follows from the previous step.
4. Check whether the technique/sutra is applied correctly (if applicable).
5. Look for common traps: sign errors, carry/borrow mistakes, wrong base selection, incorrect formula application.

Return ONLY this JSON (no markdown, no explanation outside JSON):
{{
  "problem_text": "{problem_text[:200].replace(chr(34), chr(92)+chr(34))}",
  "function_latex": "{function_latex[:200].replace(chr(34), chr(92)+chr(34))}",
  "final_answer_correct": true or false,
  "final_answer_expected": "your independently computed answer as a string",
  "final_answer_actual": "{final_ans[:100].replace(chr(34), chr(92)+chr(34))}",
  "step_validations": [
    {{
      "step_num": 1,
      "correct": true or false,
      "error_type": "none | MATH | LOGIC | SUTRA | FORMULA | SIGN",
      "explanation": "brief note if error found, else 'Correct'"
    }}
  ],
  "sutra_adherence": {{
    "correct": true or false,
    "sutra_used": "name of sutra/technique detected in steps",
    "expected_sutra": "{tech}",
    "note": "brief assessment"
  }},
  "trap_detected": {{
    "present": true or false,
    "trap_type": "type of trap if any",
    "explanation": "description if trap found"
  }},
  "overall_confidence": 0.0 to 1.0,
  "review_needed": true or false,
  "review_reason": "if review_needed, explain why"
}}

IMPORTANT: Be strict. If ANY step contains an error, mark final_answer_correct as false. If the problem is ambiguous or you cannot compute it, set review_needed=true."""
    return prompt

# ── Consensus Engine ─────────────────────────────────────────
class ConsensusValidator:
    def __init__(self):
        self.models = MODELS
        self.token_count = 0

    def validate_template(self, template: dict) -> dict:
        """Run 3 LLMs in parallel, compute consensus."""
        prompt = build_validation_prompt(template)
        results = {}

        # Parallel calls
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                name: executor.submit(call_llm, prompt, model_id)
                for name, model_id in self.models.items()
            }
            for i, (name, future) in enumerate(futures.items()):
                # Stagger call starts slightly to avoid burst
                time.sleep(0.3 * i)
                try:
                    res = future.result(timeout=LLM_TIMEOUT + 30)
                    results[name] = res
                    if res:
                        self.token_count += res.get("_tokens", 0)
                except Exception as e:
                    log(f"  ⚠️ Future error for {name}: {type(e).__name__}")
                    results[name] = None

        # Extract votes
        votes = {}
        for name, res in results.items():
            if res:
                votes[name] = {
                    "final_correct": res.get("final_answer_correct"),
                    "confidence": res.get("overall_confidence", 0.5),
                    "review": res.get("review_needed", False),
                    "tokens": res.get("_tokens", 0),
                }

        # Consensus on final_answer
        correct_votes = sum(1 for v in votes.values() if v.get("final_correct") is True)
        incorrect_votes = sum(1 for v in votes.values() if v.get("final_correct") is False)
        review_votes = sum(1 for v in votes.values() if v.get("review") is True)
        total_votes = len(votes)

        if total_votes == 0:
            consensus = {
                "final_answer_correct": None,
                "status": "no_response",
                "confidence": 0.0,
                "review_needed": True,
                "review_reason": "All LLM calls failed",
            }
        elif review_votes >= 2:
            consensus = {
                "final_answer_correct": None,
                "status": "needs_review",
                "confidence": max(v.get("confidence", 0.5) for v in votes.values()),
                "review_needed": True,
                "review_reason": "Majority of validators flagged for human review",
            }
        elif correct_votes >= 2:
            consensus = {
                "final_answer_correct": True,
                "status": "consensus_pass",
                "confidence": sum(v.get("confidence", 0.5) for v in votes.values() if v.get("final_correct") is True) / correct_votes,
                "review_needed": False,
                "review_reason": "",
            }
        elif incorrect_votes >= 2:
            consensus = {
                "final_answer_correct": False,
                "status": "consensus_fail",
                "confidence": sum(v.get("confidence", 0.5) for v in votes.values() if v.get("final_correct") is False) / incorrect_votes,
                "review_needed": True,
                "review_reason": "Majority of validators found mathematical errors",
            }
        else:
            # Split decision (e.g., 1 correct, 1 incorrect, 1 review)
            # Tie-break: use highest-confidence vote
            best = max(votes.items(), key=lambda x: x[1].get("confidence", 0))
            consensus = {
                "final_answer_correct": best[1].get("final_correct"),
                "status": "split_decision",
                "confidence": best[1].get("confidence", 0.5),
                "review_needed": True,
                "review_reason": f"Split decision across validators. Tie-broken by {best[0]} (highest confidence)",
            }

        return {
            "template_id": template.get("template_id"),
            "timestamp": datetime.now().isoformat(),
            "individual_results": results,
            "consensus": consensus,
            "vote_summary": {
                "correct": correct_votes,
                "incorrect": incorrect_votes,
                "review": review_votes,
                "total": total_votes,
            },
            "tokens_used": sum(v.get("_tokens", 0) for v in results.values() if v),
        }

# ── File Processor ───────────────────────────────────────────
def process_book(filepath: Path, validator: ConsensusValidator, limit: Optional[int] = None, skip_set: set = None) -> List[dict]:
    """Process one JSONL file. Return list of results."""
    book_results = []
    templates = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                templates.append(json.loads(line))

    # Filter out already-validated
    to_process = []
    for t in templates:
        tid = t.get("template_id")
        if skip_set and tid in skip_set:
            continue
        if t.get("_math_validation_status") in ("validated", "flagged"):
            continue
        to_process.append(t)

    if limit:
        to_process = to_process[:limit]

    log(f"📖 {filepath.stem}: {len(templates)} total, {len(to_process)} to validate")

    # Process with parallel workers
    processed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_template = {
            executor.submit(validator.validate_template, t): t
            for t in to_process
        }
        for future in as_completed(future_to_template):
            template = future_to_template[future]
            try:
                result = future.result()
                book_results.append(result)

                # Update template in-memory
                consensus = result.get("consensus", {})
                status = "validated" if consensus.get("final_answer_correct") is True else ("flagged" if consensus.get("final_answer_correct") is False else "needs_review")
                template["_math_validation_status"] = status
                template["_math_validation_score"] = int(consensus.get("confidence", 0) * 100)
                template["_math_validation_details"] = result
                template["_math_validated_at"] = datetime.now().isoformat()
                template["_math_validation_version"] = "v3_consensus"

                processed += 1
                if processed % 10 == 0:
                    log(f"  Progress: {processed}/{len(to_process)} | tokens={validator.token_count}")
                
                # Rate limit safety: delay between templates
                time.sleep(INTER_TEMPLATE_DELAY)

            except Exception as e:
                log(f"  ⚠️ Template {template.get('template_id')} failed: {type(e).__name__}")

    # Write back updated templates
    with open(filepath, "w", encoding="utf-8") as f:
        for t in templates:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    log(f"  ✅ Done: {processed} processed")
    return book_results

# ── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Multi-LLM Consensus Math Validator v3")
    parser.add_argument("--limit", type=int, default=None, help="Max templates per book")
    parser.add_argument("--book", type=str, default=None, help="Specific book name (stem)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    args = parser.parse_args()

    # Clear log
    LOG_PATH.write_text("", encoding="utf-8")
    log("=" * 60)
    log("CONSENSUS MATH VALIDATOR v3 — Starting")
    log("Provider: Ollama Cloud (FREE tier)")
    log(f"Models: {MODELS}")
    log(f"Keys available: {len(KEYS)}")
    log("=" * 60)

    validator = ConsensusValidator()
    all_results = []

    # Load checkpoint
    skip_set = set()
    if args.resume and CHECKPOINT_PATH.exists():
        cp = json.loads(CHECKPOINT_PATH.read_text())
        skip_set = set(cp.get("completed_ids", []))
        log(f"🔄 Resuming: {len(skip_set)} templates already validated")

    # Find files
    pattern = f"{args.book}*_solvealong.jsonl" if args.book else "*_solvealong.jsonl"
    files = sorted(TEMPLATES_DIR.glob(pattern))

    for fp in files:
        results = process_book(fp, validator, limit=args.limit, skip_set=skip_set)
        all_results.extend(results)

        # Save checkpoint
        completed = [r["template_id"] for r in all_results if r.get("template_id")]
        CHECKPOINT_PATH.write_text(json.dumps({"completed_ids": completed, "timestamp": datetime.now().isoformat()}, indent=2), encoding="utf-8")

    # Aggregate report
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_templates": len(all_results),
        "tokens_used": validator.token_count,
        "by_status": {},
        "results": all_results,
    }
    for r in all_results:
        status = r.get("consensus", {}).get("status", "unknown")
        report["by_status"][status] = report["by_status"].get(status, 0) + 1

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log(f"\n{'='*60}")
    log("VALIDATION COMPLETE")
    log(f"  Total validated: {len(all_results)}")
    log(f"  Total tokens: {validator.token_count}")
    for k, v in sorted(report["by_status"].items(), key=lambda x: -x[1]):
        log(f"  {k}: {v}")
    log(f"  Report: {REPORT_PATH}")
    log(f"{'='*60}")

if __name__ == "__main__":
    main()
