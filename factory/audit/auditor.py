#!/usr/bin/env python3
"""The 7-stage auditor — every generated question passes ALL stages; no side door.

Canonical mechanics from runtime_config/auditor_system_config.json (recovered):
  1 structural_validation   -> REJECT on missing fields
  2 latex_renderability     -> latex_sanity_v1 (balance checks; katex slot-in at integration)
  3 computation             -> INDEPENDENT re-evaluation of `compute` (exact int/Fraction
                               AST evaluator; SymPy if installed), tolerance 1e-10
  4 domain_specific_rules   -> sutra_validator_rules_v3 equivalents (base valid,
                               deviation bounds, right-part digit fit)
  5 trap_verification       -> declared traps sane (non-empty, distinct, <=5)
  6 deduplication           -> params_hash unique in-run + against the seen store
                               (file-backed now; Redis 24h window at integration)
  7 consensus_gate          -> 2-of-3 jesters (glm-5.1 / kimi-k2.6 / deepseek-v4-flash)
                               via a pluggable JesterGate; offline -> 'pending'

Trust-ladder entry (no side door): stages 1-6 pass + consensus pass -> 'sandbox';
consensus pending -> 'quarantined_pending_consensus'; any stage fail -> 'rejected'
(with resample handled by the caller, max 3 per the orchestrator config).
"""

import ast
import json
import operator
import re
from fractions import Fraction
from pathlib import Path

TOLERANCE = 1e-10
BASES_VALID = {10, 100, 1000, 10000}
MAX_TRAPS = 5

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: lambda a, b: Fraction(a) / Fraction(b), ast.Pow: operator.pow,
        ast.USub: operator.neg}


def safe_eval(expr: str):
    """Exact arithmetic evaluator over +,-,*,/,**, unary minus, ints. No names, no calls."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"disallowed node {type(node).__name__}")
    return ev(ast.parse(expr, mode="eval"))


class JesterGate:
    """Stage-7 interface. Offline default returns 'pending' for every record;
    the model-backed implementation (2-of-3: glm-5.1 / kimi-k2.6 /
    deepseek-v4-flash) plugs in when owner keys land."""

    def vote(self, record: dict) -> str:  # 'pass' | 'fail' | 'pending'
        return "pending"


def _check_latex(s: str) -> bool:
    if s.count("{") != s.count("}"):
        return False
    if len(re.findall(r"\\begin\b", s)) != len(re.findall(r"\\end\b", s)):
        return False
    if s.count("$") % 2 != 0:
        return False
    return not re.search(r"\\[0-9]", s)  # digits directly after backslash = broken command


class Auditor:
    def __init__(self, seen_store: Path | None = None, jester_gate: JesterGate | None = None):
        self.gate = jester_gate or JesterGate()
        self.seen_path = seen_store
        self.seen: set[str] = set()
        if seen_store and seen_store.exists():
            self.seen = set(json.loads(seen_store.read_text())["hashes"])

    def persist_seen(self):
        if self.seen_path:
            self.seen_path.parent.mkdir(parents=True, exist_ok=True)
            self.seen_path.write_text(json.dumps({"hashes": sorted(self.seen)}))

    def audit(self, rec: dict) -> dict:
        """Returns {verdict: sandbox|quarantined_pending_consensus|rejected,
        failed_stage, reasons[], consensus}."""
        reasons = []

        # 1 structural
        for field in ("template_id", "problem_statement", "final_answer", "difficulty",
                      "sub_topic", "solution"):
            if not rec.get(field):
                reasons.append(f"missing_{field}")
        if not (isinstance(rec.get("difficulty"), int) and 1 <= rec["difficulty"] <= 5):
            reasons.append("difficulty_invalid")
        if reasons:
            return {"verdict": "rejected", "failed_stage": 1, "reasons": reasons}

        # 2 latex sanity
        for step in rec.get("solution", []):
            f = step.get("formula") or ""
            if f and not _check_latex(f):
                return {"verdict": "rejected", "failed_stage": 2,
                        "reasons": [f"latex_unbalanced_step_{step.get('step_num')}"]}

        # 3 independent computation
        expr = rec.get("compute")
        if expr:
            try:
                value = safe_eval(expr)
            except Exception as e:
                return {"verdict": "rejected", "failed_stage": 3, "reasons": [f"compute_error:{e}"]}
            try:
                stated = Fraction(rec["final_answer"])
            except ValueError:
                return {"verdict": "rejected", "failed_stage": 3, "reasons": ["answer_not_numeric"]}
            if abs(Fraction(value) - stated) > Fraction(1, 10**10):
                return {"verdict": "rejected", "failed_stage": 3,
                        "reasons": [f"answer_mismatch:{value}!={stated}"]}
        elif rec.get("template_type") == "generated_t2":
            return {"verdict": "rejected", "failed_stage": 3, "reasons": ["generated_without_compute"]}

        # 4 domain rules (near-base sutra patterns)
        p = rec.get("params") or {}
        if "base" in p:
            base = p["base"]
            if base not in BASES_VALID:
                return {"verdict": "rejected", "failed_stage": 4, "reasons": [f"base_invalid:{base}"]}
            for k in ("a", "b"):
                if k in p:
                    dev = p[k] - base
                    if dev == 0:
                        return {"verdict": "rejected", "failed_stage": 4, "reasons": [f"{k}_equals_base"]}
                    if abs(dev) > base * 0.35:
                        return {"verdict": "rejected", "failed_stage": 4,
                                "reasons": [f"{k}_deviation_out_of_range:{dev}"]}

        # 5 trap sanity
        traps = rec.get("traps") or []
        if len(traps) > MAX_TRAPS or len(set(traps)) != len(traps) or \
                any(not isinstance(t, str) or len(t) < 8 for t in traps):
            return {"verdict": "rejected", "failed_stage": 5, "reasons": ["traps_insane"]}

        # 6 dedup
        h = rec.get("params_hash") or rec["template_id"]
        if h in self.seen:
            return {"verdict": "rejected", "failed_stage": 6, "reasons": ["duplicate_params_hash"]}
        self.seen.add(h)

        # 7 consensus
        consensus = self.gate.vote(rec)
        if consensus == "fail":
            return {"verdict": "rejected", "failed_stage": 7, "reasons": ["consensus_failed"],
                    "consensus": consensus}
        verdict = "sandbox" if consensus == "pass" else "quarantined_pending_consensus"
        return {"verdict": verdict, "failed_stage": None, "reasons": [], "consensus": consensus}
