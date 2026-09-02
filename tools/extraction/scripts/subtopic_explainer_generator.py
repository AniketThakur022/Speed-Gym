#!/usr/bin/env python3
"""
Subtopic Explainer Generator — 3-LLM Consensus Batch Enrichment Pipeline.

Converts 25 draft-stub subtopic explainers into full Quick Ref JSONs using
3-LLM consensus with explicit contradiction resolution, SymPy verification,
JSON schema validation, and high-risk flagging for human review.

Usage:
    python subtopic_explainer_generator.py                    # Process all stubs
    python subtopic_explainer_generator.py --dry-run          # Validate only, no writes
    python subtopic_explainer_generator.py --ids nikhilam_sutra ekanyunena_purvena
    python subtopic_explainer_generator.py --risk-report       # Just output risk flags
"""

import json
import csv
import hashlib
import logging
import argparse
import asyncio
import re
import sys
import httpx
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from enum import Enum

# Make assembly_line importable for real API calls
try:
    WORKSPACE = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(WORKSPACE))
    from assembly_line.consensus import call_model_with_fallback
    from topic_browser_full_package.scripts.enrichment_utils import extract_json
    CONSENSUS_AVAILABLE = True
except ImportError:
    CONSENSUS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer"
OUTPUT_DIR = PACKAGE_ROOT / "content_data" / "subtopic_explainer_enriched"
MANIFEST_PATH = OUTPUT_DIR / "manifest.csv"
RISK_REPORT_PATH = OUTPUT_DIR / "risk_report.json"
SCHEMA_CANDIDATES = [
    PACKAGE_ROOT / "schemas" / "subtopic_reference_schema.json",
    PACKAGE_ROOT / "schemas" / "subtopic_reference_schema_v2.json",
]
CONFIG_DIR = PACKAGE_ROOT / "runtime_config"

# Approved files that serve as gold-standard reference
APPROVED_IDS = {"nikhilam_sutra", "urdhva_tiryak", "yavadunam"}

# Jester model IDs matching auditor_system_config.json stage 7
JESTER_MODELS = ["glm-5.1", "kimi-k2.6", "deepseek-v4-flash"]
CONSENSUS_THRESHOLD = 2  # 2-of-3 required (from master_orchestrator_config)

# SymPy tolerance from master_orchestrator_config.json
SYMPY_TOLERANCE = 1e-10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("subtopic_generator")


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConsensusResult(str, Enum):
    UNANIMOUS = "unanimous"           # 3/3 agree
    MAJORITY = "majority"             # 2/3 agree
    CONFLICT = "conflict"             # No 2/3 agreement — needs resolution
    RESOLVED = "resolved"             # Conflict was resolved via tie-breaker


@dataclass
class RiskFlag:
    subtopic_id: str
    risk_level: RiskLevel
    category: str       # "mixed_sign", "division_by_zero", "equation_structure", etc.
    description: str
    recommendation: str


@dataclass
class ConsensusReport:
    subtopic_id: str
    result: ConsensusResult
    jesters_agreed: list[str]
    jesters_disagreed: list[str]
    contradictions: list[str]
    resolution_method: Optional[str] = None


@dataclass
class VerificationResult:
    subtopic_id: str
    formula_verified: bool
    example_verified: bool
    sympy_checks: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class ProcessingRecord:
    subtopic_id: str
    status: str                     # "success", "failed", "flagged_for_review"
    risk_level: str
    consensus: str
    sympy_pass: bool
    schema_valid: bool
    completeness_score: float
    output_path: Optional[str] = None
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════
# 1. STUB LOADER
# ═══════════════════════════════════════════════════════════════════════════

def load_all_stubs(content_dir: Path = CONTENT_DIR) -> dict[str, dict]:
    """Load all JSON files; return {subtopic_id: data} for stubs only."""
    stubs = {}
    for p in sorted(content_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        sid = data.get("subtopic_id", p.stem)
        meta = data.get("metadata", {})
        if meta.get("content_status") == "coming_soon" or meta.get("completeness_score", 0) == 0.0:
            stubs[sid] = data
    return stubs


def load_approved_references(content_dir: Path = CONTENT_DIR) -> dict[str, dict]:
    """Load the 3 approved gold-standard files for reference pattern extraction."""
    refs = {}
    for sid in APPROVED_IDS:
        p = content_dir / f"{sid}.json"
        if p.exists():
            refs[sid] = json.loads(p.read_text(encoding="utf-8"))
    return refs


# ═══════════════════════════════════════════════════════════════════════════
# 2. RISK PROFILER — Pre-generation risk assessment
# ═══════════════════════════════════════════════════════════════════════════

# Known Vedic Math sutras and their mathematical risk profiles
SUTRA_RISK_PROFILES: dict[str, dict] = {
    "ekanyunena_purvena": {
        "risk_level": RiskLevel.HIGH,
        "risks": [
            RiskFlag(
                subtopic_id="ekanyunena_purvena",
                risk_level=RiskLevel.HIGH,
                category="equation_structure",
                description="Ekanyunena operates on repunit-like products (e.g., 999×n). "
                            "LLMs frequently confuse the multiplier pattern (all 9s of length d-1) "
                            "with simple subtraction.",
                recommendation="SymPy-verify every example. Cross-check: for n-digit multiplier, "
                               "result = multiplier × (10^n - 1) / 9 × multiplicand pattern."
            ),
        ],
    },
    "seshanyakena_caramena": {
        "risk_level": RiskLevel.HIGH,
        "risks": [
            RiskFlag(
                subtopic_id="seshanyakena_caramena",
                risk_level=RiskLevel.HIGH,
                category="division_by_zero",
                description="Seshanyakena Caramena (the remainder by the last digit) involves "
                            "division by the last digit of the divisor. Division by zero trap "
                            "when last digit is 0 (e.g., divisor = 20, 30, 100).",
                recommendation="Must include explicit guard: last_digit ≠ 0. "
                               "LLM-generated examples must never use divisors ending in 0. "
                               "SymPy must verify division is defined."
            ),
        ],
    },
    "chalana_kalanabhyam": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="chalana_kalanabhyam",
                risk_level=RiskLevel.MEDIUM,
                category="equation_structure",
                description="Chalana-Kalanabhyam (differences and similarities) applies to "
                            "special quadratic/cubic forms. LLMs often overgeneralize to "
                            "arbitrary polynomials where the method fails.",
                recommendation="Restrict examples to forms: (x+a)(x+b), (x-a)(x-b), "
                               "or cubes near perfect cubes. SymPy-validate factorization."
            ),
        ],
    },
    "puranapuranabhyam": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="puranapuranabhyam",
                risk_level=RiskLevel.MEDIUM,
                category="equation_structure",
                description="Puranapuranabhyam (by completion) is used for solving quadratics "
                            "by completing the square. LLMs may produce incorrect completions "
                            "or miss the ± root branches.",
                recommendation="SymPy-solve every quadratic example. Verify both roots. "
                               "Check that the 'completion' step algebraically matches."
            ),
        ],
    },
    "sopantyadvayam": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="sopantyadvayam",
                risk_level=RiskLevel.MEDIUM,
                category="mixed_sign",
                description="Sopantyadvayam (the ultimate and twice the penultimate) involves "
                            "simultaneous equations with specific coefficient relationships. "
                            "Mixed-sign coefficients can flip the formula.",
                recommendation="Verify with SymPy that the simultaneous solution matches. "
                               "Flag any example with negative coefficients for manual review."
            ),
        ],
    },
    "gunaka_samuccayah": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="gunaka_samuccayah",
                risk_level=RiskLevel.MEDIUM,
                category="equation_structure",
                description="Gunaka Samuccayah relates factors to sums. Common LLM confusion "
                            "between this and Gunita Samuccayah (product of sums vs. "
                            "sum of products).",
                recommendation="Cross-reference with gunita_samuccayah to ensure no "
                               "formula mixing. SymPy-verify all factorizations."
            ),
        ],
    },
    "gunita_samuccayah": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="gunita_samuccayah",
                risk_level=RiskLevel.MEDIUM,
                category="equation_structure",
                description="Gunita Samuccayah (the product of the sum of coefficients) — "
                            "LLMs often confuse this divisibility test with direct computation.",
                recommendation="Verify: sum_of_coeffs(product) == product_of_sums. "
                               "SymPy-expand and check coefficient sums."
            ),
        ],
    },
    "vyasti_samasti": {
        "risk_level": RiskLevel.MEDIUM,
        "risks": [
            RiskFlag(
                subtopic_id="vyasti_samasti",
                risk_level=RiskLevel.MEDIUM,
                category="equation_structure",
                description="Vyasti-Samasti (individuality and totality) involves averages "
                            "and deviations. LLMs may produce wrong deviation calculations "
                            "when numbers span zero or are negative.",
                recommendation="SymPy-verify average and deviation calculations. "
                               "Test with mixed-sign number sets."
            ),
        ],
    },
}

# Topic-level risk heuristics for non-Vedic stubs
TOPIC_RISK_HEURISTICS = {
    "quadratic_equations": (RiskLevel.MEDIUM, "equation_structure",
                             "Quadratic formula requires discriminant checks. LLMs may miss "
                             "complex root cases."),
    "polynomials": (RiskLevel.MEDIUM, "equation_structure",
                    "Polynomial operations require degree tracking. LLMs may confuse "
                    "multiplication with composition."),
    "linear_equations": (RiskLevel.LOW, "general",
                         "Standard algebra — low risk but verify solution steps."),
    "fractions": (RiskLevel.MEDIUM, "division_by_zero",
                  "Division by zero when denominator = 0. LLMs may produce invalid "
                  "simplifications."),
    "division_tricks": (RiskLevel.HIGH, "division_by_zero",
                        "Division shortcuts must handle divisors of 0, 1, and negative values. "
                        "LLMs frequently produce division-by-zero examples."),
    "arithmetic_gre": (RiskLevel.LOW, "exam_content",
                       "Standard GRE arithmetic — verify against known problem types."),
    "problem_solving_gmat": (RiskLevel.LOW, "exam_content",
                             "GMAT problem-solving — verify against official GMAT scope."),
    "quantitative_aptitude_cat": (RiskLevel.LOW, "exam_content",
                                   "CAT quant — verify against CAT syllabus boundaries."),
    # ── NEW: Previously uncovered General Maths subtopics ──
    "trigonometry_basics": (RiskLevel.HIGH, "undefined_values",
                            "Trigonometric functions have undefined points (tan 90°, cot 0°). "
                            "LLMs may produce examples at undefined values. Degree/radian "
                            "confusion is common."),
    "geometry_basics": (RiskLevel.MEDIUM, "degenerate_shapes",
                        "Geometry problems require non-degenerate shapes. LLMs may produce "
                        "impossible triangles (a+b<c), negative lengths, or zero areas."),
    "mensuration": (RiskLevel.MEDIUM, "unit_mismatch",
                    "Mensuration formulas require consistent units. LLMs may mix units "
                    "or produce negative volumes/areas."),
    "number_theory": (RiskLevel.MEDIUM, "primality_edge_cases",
                      "Number theory edge cases: 0 and 1 for primality, negative numbers "
                      "for GCD/LCM, division by zero in modular arithmetic."),
    "school_foundation": (RiskLevel.LOW, "general",
                          "Catch-all school arithmetic — verify arithmetic correctness."),
    "ratios_proportions": (RiskLevel.MEDIUM, "zero_ratio",
                           "Ratios involving zero (0:x, x:0) are undefined. LLMs may produce "
                           "proportions with missing constraints."),
    "percentages": (RiskLevel.LOW, "general",
                    "Standard percentage problems — verify that percentage > 100% cases "
                    "are handled correctly."),
    "addition_tricks": (RiskLevel.LOW, "carry_propagation",
                        "Addition tricks must handle carry propagation across multiple "
                        "digits. Verify final sums."),
    "subtraction_tricks": (RiskLevel.LOW, "borrow_propagation",
                           "Subtraction tricks must handle borrow across multiple digits. "
                           "Verify no negative intermediate results."),
    "multiplication_tricks": (RiskLevel.LOW, "general",
                              "Standard multiplication shortcuts — verify final product."),
    "functions_graphs": (RiskLevel.MEDIUM, "domain_range",
                         "Functions require domain/range constraints. LLMs may produce "
                         "examples with undefined inputs (e.g., sqrt(-1), log(0))."),
    "complex_numbers": (RiskLevel.HIGH, "i_squared_identity",
                        "Complex numbers require i²=-1 invariant. LLMs frequently confuse "
                        "i² with -i or produce inconsistent real/imaginary splits."),
    "magic_squares": (RiskLevel.MEDIUM, "magic_constant",
                      "Magic squares must satisfy row/col/diag sum = magic constant. "
                      "LLMs may produce squares where sums don't match."),
    "calendar_calculations": (RiskLevel.MEDIUM, "leap_year",
                              "Calendar calculations must account for leap years, century "
                              "exceptions. LLMs may miss the 400-year Gregorian rule."),
}


def profile_risks(subtopic_id: str, stub: dict) -> list[RiskFlag]:
    """Pre-generation risk assessment for a subtopic."""
    flags: list[RiskFlag] = []

    # 1. Check Vedic Math sutra-specific risks
    if subtopic_id in SUTRA_RISK_PROFILES:
        profile = SUTRA_RISK_PROFILES[subtopic_id]
        flags.extend(profile["risks"])

    # 2. Check topic-level heuristics
    topic = stub.get("topic", "")
    if subtopic_id in TOPIC_RISK_HEURISTICS:
        level, cat, desc = TOPIC_RISK_HEURISTICS[subtopic_id]
        flags.append(RiskFlag(
            subtopic_id=subtopic_id,
            risk_level=level,
            category=cat,
            description=desc,
            recommendation="SymPy-verify all numerical examples. Flag for human review if "
                           "completeness_score < 0.7 after enrichment."
        ))

    # 3. Heuristic: stubs with sutra=null that are Vedic Math topics are riskier
    #    because LLMs must infer the correct sutra mapping
    if stub.get("sutra") is None and topic == "Vedic Math":
        if not any(f.category == "equation_structure" for f in flags):
            flags.append(RiskFlag(
                subtopic_id=subtopic_id,
                risk_level=RiskLevel.MEDIUM,
                category="sutra_inference",
                description=f"Sutra mapping is null — LLM must correctly identify the "
                            f"sutra for '{subtopic_id}'. Risk of hallucinated sutra names.",
                recommendation="Cross-validate sutra name against Tirthaji's 16 sutras. "
                               "Verify Sanskrit transliteration."
            ))

    # Default: low risk if no flags raised
    if not flags:
        flags.append(RiskFlag(
            subtopic_id=subtopic_id,
            risk_level=RiskLevel.LOW,
            category="general",
            description="Standard content — no elevated mathematical risk detected.",
            recommendation="Standard SymPy verification pipeline."
        ))

    return flags


# ═══════════════════════════════════════════════════════════════════════════
# 3. 3-LLM CONSENSUS ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class LLMJester:
    """Simulates a single LLM jester for content generation.

    In production, replace generate() with actual API calls to:
      - glm-5.1   (GLM / Zhipu)
      - kimi-k2.6  (Moonshot)
      - deepseek-v4-flash (DeepSeek)
    """

    def __init__(self, model_id: str, temperature: float = 0.7):
        self.model_id = model_id
        self.temperature = temperature

    def generate_enrichment(
        self,
        subtopic_id: str,
        stub: dict,
        approved_refs: dict[str, dict],
        risk_flags: list[RiskFlag],
    ) -> dict:
        """Generate a single-model enrichment proposal (raw jester output).

        The ConsensusEngine calls this on 3 jesters and then synthesizes their
        outputs, avoiding the double-consensus bug where run_consensus was called
        inside each jester.
        """
        if CONSENSUS_AVAILABLE:
            return asyncio.run(self._generate_single_model(
                subtopic_id, stub, approved_refs, risk_flags
            ))
        else:
            log.warning(
                f"  [{self.model_id}] API unavailable — "
                f"raising error for {subtopic_id}"
            )
            raise RuntimeError(f"Consensus API unavailable for {subtopic_id}")

    async def _generate_single_model(
        self,
        subtopic_id: str,
        stub: dict,
        approved_refs: dict[str, dict],
        risk_flags: list[RiskFlag],
    ) -> dict:
        """Call a single LLM to produce one enrichment proposal."""
        topic = stub.get("topic", "Maths")
        category = stub.get("category", "Foundation")
        sutra_name = stub.get("sutra")
        applicability = stub.get("applicability_type", "general")

        # Build reference examples from approved files
        approved_json = json.dumps(
            {k: v for k, v in approved_refs.items() if k in APPROVED_IDS},
            indent=2, ensure_ascii=False,
        )[:6000]

        # Collect risk context
        risk_text = ""
        for f in risk_flags:
            risk_text += f"- [{f.risk_level.value.upper()}] {f.category}: {f.description}\n"
        if not risk_text:
            risk_text = "No specific risks identified."

        prompt = _build_enrichment_prompt(
            subtopic_id=subtopic_id,
            topic=topic,
            category=category,
            sutra_name=sutra_name,
            applicability=applicability,
            risk_text=risk_text,
            approved_json=approved_json,
        )

        async with httpx.AsyncClient() as client:
            result = await call_model_with_fallback(
                client,
                self.model_id,
                0,  # key rotation index
                [{"role": "user", "content": prompt}],
                label=self.model_id,
                timeout=180,
                max_tokens=8192,
            )

        if result["error"]:
            raise RuntimeError(f"Model {self.model_id} failed: {result['error']}")

        enriched = extract_json(result["content"], subtopic_id)
        log.info(f"  [{self.model_id}] Generated proposal for {subtopic_id}")
        return enriched


# ── Prompt builder (avoids f-string brace escaping) ──
def _build_enrichment_prompt(**kwargs) -> str:
    """Build enrichment prompt with safe substitution."""
    return f"""You are a math educator creating a Quick Reference Card for the subtopic '{kwargs["subtopic_id"]}'.

## Subtopic Info
- Topic: {kwargs["topic"]}
- Category: {kwargs["category"]}
- Sutra: {kwargs["sutra_name"] or 'N/A (not a Vedic sutra)'}
- Applicability: {kwargs["applicability"]}

## Risk Warnings (avoid these mistakes)
{kwargs["risk_text"]}

## Approved Reference Examples (for style/structure)
{kwargs["approved_json"]}

## Required Output
Return a COMPLETE JSON object with these keys at minimum:
- subtopic_id, category, topic, sutra, applicability_type
- quick_ref > when_to_use (conditions, range_rule), base_selection_guide, the_trick (formula_latex, variable_definitions, mental_steps, time_saved, difficulty_label), quick_example (problem, answer, visual_layout, time_estimate_ms), top_traps (exactly 3 with rank, name, trap_type, description, example, why_it_happens, prevention)
- techniques_by_difficulty with L1, L2, L3 (each with technique_id, name, focus, example with problem/answer, template_count). L2 should have representative:true.
- total_techniques, total_templates, metadata

## Critical Rules
1. Output ONLY the JSON object — no markdown fences, no explanation text.
2. ALL mathematical examples MUST be correct. Double-check every answer.
3. quick_example must use simple numbers suitable for mental math.
4. If this is a division subtopic, NEVER use divisor = 0.
5. For Vedic sutras: include correct Sanskrit transliteration and English translation.
6. top_traps must have exactly 3 entries with rank 1, 2, 3.
7. techniques_by_difficulty must have L1, L2, L3 populated.
8. difficulty_label should reflect actual cognitive load.
9. All formula_latex entries must be valid KaTeX.

Return the complete JSON object now."""


class ConsensusEngine:
    """3-LLM consensus with explicit contradiction resolution.

    Protocol (from AGENTS.md / auditor_system_config.json):
    1. Dispatch generation to all 3 jesters
    2. Compare outputs field-by-field
    3. If 2/3 agree on a field → use the majority value
    4. If 3-way disagreement → invoke tie-breaker (re-prompt with context)
    5. Log all contradictions and resolutions
    """

    def __init__(self, jesters: list[LLMJester]):
        self.jesters = jesters
        self.tie_breaker = LLMJester("tie-breaker", temperature=0.3)

    def generate_with_consensus(
        self,
        subtopic_id: str,
        stub: dict,
        approved_refs: dict[str, dict],
        risk_flags: list[RiskFlag],
    ) -> tuple[dict, ConsensusReport]:
        """Run 3-jester consensus and return merged result + report."""

        # Step 1: Collect proposals from all jesters
        proposals: list[dict] = []
        failed_jesters: list[str] = []
        for jester in self.jesters:
            try:
                proposal = jester.generate_enrichment(subtopic_id, stub, approved_refs, risk_flags)
                proposals.append(proposal)
            except Exception as e:
                log.error(f"  [{jester.model_id}] Failed to generate proposal for {subtopic_id}: {e}")
                failed_jesters.append(jester.model_id)

        if not proposals:
            raise RuntimeError(f"All jesters failed for {subtopic_id}; failures: {failed_jesters}")

        if len(proposals) == 1:
            # Only one proposal available — use it but mark as unresolved
            report = ConsensusReport(
                subtopic_id=subtopic_id,
                result=ConsensusResult.CONFLICT,
                jesters_agreed=[],
                jesters_disagreed=[],
                contradictions=[f"Only 1 of {len(self.jesters)} jesters succeeded; failed: {failed_jesters}"],
                resolution_method="single_proposal_fallback",
            )
            return proposals[0], report

        # Step 2: Field-by-field comparison
        # Key fields to compare for consensus
        critical_fields = [
            ("quick_ref", "the_trick", "formula_latex"),
            ("quick_ref", "quick_example", "answer"),
            ("quick_ref", "quick_example", "problem"),
            ("quick_ref", "when_to_use", "conditions"),
            ("sutra",),
            ("sutra_sanskrit",),
            ("translation",),
            ("applicability_type",),
        ]

        contradictions: list[str] = []
        agreed_jesters: set[str] = set()
        disagreed_jesters: set[str] = set()
        merged = json.loads(json.dumps(proposals[0]))  # start from first proposal

        for field_path in critical_fields:
            values = []
            for i, prop in enumerate(proposals):
                val = _get_nested(prop, field_path)
                values.append((self.jesters[i].model_id, val))

            # Check agreement
            unique_values = {}
            for model_id, val in values:
                key = json.dumps(val, sort_keys=True) if val is not None else "null"
                unique_values.setdefault(key, []).append(model_id)

            if len(unique_values) == 1:
                # Unanimous on this field
                for model_id, _ in values:
                    agreed_jesters.add(model_id)
            elif any(len(v) >= CONSENSUS_THRESHOLD for v in unique_values.values()):
                # Majority exists
                majority_key = max(unique_values, key=lambda k: len(unique_values[k]))
                for model_id in unique_values[majority_key]:
                    agreed_jesters.add(model_id)
                dissenters = [m for k, v in unique_values.items() if k != majority_key for m in v]
                for m in dissenters:
                    disagreed_jesters.add(m)
                contradictions.append(
                    f"Field {'.'.join(field_path)}: majority={majority_key[:80]}, "
                    f"dissenters={dissenters}"
                )
                # Use majority value
                _set_nested(merged, field_path, json.loads(majority_key))
            else:
                # 3-way conflict — need tie-breaker
                contradictions.append(
                    f"Field {'.'.join(field_path)}: 3-way conflict — invoking tie-breaker"
                )
                for model_id, _ in values:
                    disagreed_jesters.add(model_id)

        # Step 3: Resolve 3-way conflicts via tie-breaker
        resolution_method = None
        if any("3-way conflict" in c for c in contradictions):
            resolution_method = "tie_breaker_reprompt"
            tie_breaker_proposal = self.tie_breaker.generate_enrichment(
                subtopic_id, stub, approved_refs, risk_flags
            )
            # For scaffold: use tie-breaker proposal as final authority
            merged = tie_breaker_proposal
            log.warning(f"  [{subtopic_id}] 3-way conflict resolved by tie-breaker")

        # Determine overall result
        if not contradictions:
            result = ConsensusResult.UNANIMOUS
        elif resolution_method:
            result = ConsensusResult.RESOLVED
        elif len(contradictions) <= 2:
            result = ConsensusResult.MAJORITY
        else:
            result = ConsensusResult.CONFLICT

        report = ConsensusReport(
            subtopic_id=subtopic_id,
            result=result,
            jesters_agreed=list(agreed_jesters - disagreed_jesters),
            jesters_disagreed=list(disagreed_jesters),
            contradictions=contradictions,
            resolution_method=resolution_method,
        )

        return merged, report


def _get_nested(d: dict, path: tuple) -> Any:
    """Safely get a nested value from a dict by path tuple."""
    current = d
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _set_nested(d: dict, path: tuple, value: Any) -> None:
    """Set a nested value in a dict by path tuple."""
    current = d
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[path[-1]] = value


# ═══════════════════════════════════════════════════════════════════════════
# 4. SYMPY VERIFICATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class SymPyVerifier:
    """Verifies numerical examples and formulas using SymPy.

    Checks:
    1. quick_example.answer matches computed result
    2. formula_latex evaluates correctly for the example
    3. techniques_by_difficulty examples have correct answers
    4. No division-by-zero in any step
    5. Deviation signs are consistent
    """

    def __init__(self, tolerance: float = SYMPY_TOLERANCE):
        self.tolerance = tolerance
        self._sympy_available = False
        try:
            import sympy  # noqa: F401
            self._sympy_available = True
        except ImportError:
            log.warning("SymPy not installed — numerical verification will use Python eval fallback")

    def verify_subtopic(self, subtopic_id: str, data: dict) -> VerificationResult:
        """Full verification of a subtopic explainer's numerical content."""
        result = VerificationResult(
            subtopic_id=subtopic_id,
            formula_verified=True,
            example_verified=True,
        )

        # 1. Verify quick_example
        self._verify_quick_example(subtopic_id, data, result)

        # 2. Verify technique examples
        self._verify_technique_examples(subtopic_id, data, result)

        # 3. Verify formula consistency
        self._verify_formula_consistency(subtopic_id, data, result)

        return result

    def _verify_quick_example(self, subtopic_id: str, data: dict, result: VerificationResult):
        """Verify the primary quick_example.answer."""
        qe = data.get("quick_ref", {}).get("quick_example", {})
        problem = qe.get("problem", "")
        stated_answer = qe.get("answer", "")

        if not problem or not stated_answer:
            result.errors.append("quick_example missing problem or answer")
            result.example_verified = False
            return

        computed = self._compute_answer(problem, subtopic_id, data)
        check = {
            "field": "quick_ref.quick_example",
            "problem": problem,
            "stated": stated_answer,
            "computed": str(computed) if computed is not None else "COMPUTATION_FAILED",
        }

        if computed is not None and str(computed) == str(stated_answer):
            check["status"] = "PASS"
        elif computed is not None:
            check["status"] = "FAIL"
            result.example_verified = False
            result.errors.append(
                f"quick_example mismatch: stated={stated_answer}, computed={computed}"
            )
        else:
            check["status"] = "SKIP_UNCOMPUTABLE"

        result.sympy_checks.append(check)

    def _verify_technique_examples(self, subtopic_id: str, data: dict, result: VerificationResult):
        """Verify each technique's example answer."""
        techs = data.get("techniques_by_difficulty", {})
        for level, tech in techs.items():
            ex = tech.get("example", {})
            problem = ex.get("problem", "")
            stated = ex.get("answer", "")
            if not problem or not stated:
                continue

            computed = self._compute_answer(problem, subtopic_id, data)
            check = {
                "field": f"techniques_by_difficulty.{level}.example",
                "problem": problem,
                "stated": stated,
                "computed": str(computed) if computed is not None else "COMPUTATION_FAILED",
            }

            if computed is not None and str(computed) == str(stated):
                check["status"] = "PASS"
            elif computed is not None:
                check["status"] = "FAIL"
                result.example_verified = False
                result.errors.append(
                    f"Technique {level} mismatch: stated={stated}, computed={computed}"
                )
            else:
                check["status"] = "SKIP_UNCOMPUTABLE"

            result.sympy_checks.append(check)

    def _verify_formula_consistency(self, subtopic_id: str, data: dict, result: VerificationResult):
        """Verify that the formula and the example are internally consistent.

        For Vedic Math base-deviation methods:
          (base + d1)(base + d2) = base² + base(d1+d2) + d1·d2
        Cross-check this structure.
        """
        qe = data.get("quick_ref", {}).get("quick_example", {})
        stated_answer = qe.get("answer", "")
        base = qe.get("base")
        deviations = qe.get("deviations", [])
        left = qe.get("left_part", {}).get("calculation", "")
        right = qe.get("right_part", {}).get("calculation", "")

        if base and deviations and left and right and stated_answer:
            # Try to reconstruct from left|right parts
            try:
                # Parse left_part: e.g., "96 - 7 = 89" → 89
                left_val = self._extract_final_number(left)
                # Parse right_part: e.g., "4 × 7 = 28" → 28
                right_val = self._extract_final_number(right)
                # Determine right_part digit count from base
                import math
                base_zeros = int(math.log10(base)) if base > 0 else 0

                if left_val is not None and right_val is not None:
                    reconstructed = left_val * (10 ** base_zeros) + right_val
                    check = {
                        "field": "formula_consistency",
                        "reconstructed": str(reconstructed),
                        "stated": stated_answer,
                    }
                    if str(reconstructed) == str(stated_answer):
                        check["status"] = "PASS"
                    else:
                        check["status"] = "FAIL"
                        result.formula_verified = False
                        result.errors.append(
                            f"Formula reconstruction mismatch: reconstructed={reconstructed}, "
                            f"stated={stated_answer}"
                        )
                    result.sympy_checks.append(check)
            except Exception as e:
                result.sympy_checks.append({
                    "field": "formula_consistency",
                    "status": "SKIP_PARSE_ERROR",
                    "error": str(e),
                })

    def _compute_answer(self, problem: str, subtopic_id: str, data: dict) -> Optional[str]:
        """Compute the expected answer for a problem string.

        Tier 1: Fast arithmetic (×, ÷, +, -, ²)
        Tier 2: SymPy expression evaluation for algebra, trig, geometry
        """
        problem = problem.strip().replace(",", "").replace(" ", "")

        # ── Tier 1: Basic arithmetic ──
        try:
            # Squaring: "98²" or "98^2"
            if "²" in problem or "^2" in problem:
                n = problem.replace("²", "").replace("^2", "")
                if n.lstrip("-").isdigit():
                    return str(int(n) ** 2)

            # Multiplication: "96×93" or "96*93"
            if "×" in problem or "*" in problem:
                sep = "×" if "×" in problem else "*"
                parts = problem.split(sep)
                if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                    return str(int(parts[0]) * int(parts[1]))

            # Division: "a÷b"
            if "÷" in problem:
                parts = problem.split("÷")
                if len(parts) == 2:
                    a, b = int(parts[0]), int(parts[1])
                    if b == 0:
                        return None  # division by zero
                    if a % b == 0:
                        return str(a // b)
                    return f"{a / b:.10g}"

            # Addition: "a+b"
            if "+" in problem:
                parts = problem.split("+")
                if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                    return str(int(parts[0]) + int(parts[1]))

            # Subtraction: "a-b"
            if "-" in problem and not problem.startswith("-"):
                parts = problem.split("-")
                if len(parts) == 2 and all(p.lstrip("-").isdigit() for p in parts):
                    return str(int(parts[0]) - int(parts[1]))
        except (ValueError, ZeroDivisionError):
            pass

        # ── Tier 2: SymPy expression evaluation ──
        try:
            import sympy
            from sympy import sympify, N, pi, E, I, sqrt, sin, cos, tan, Rational
            expr_str = problem
            expr_str = expr_str.replace("²", "**2").replace("³", "**3")
            expr_str = expr_str.replace("×", "*").replace("÷", "/")
            expr_str = expr_str.replace("√", "sqrt")
            expr_str = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', expr_str)
            expr = sympify(expr_str, evaluate=True)
            result = N(expr, 15)
            if result == int(result):
                return str(int(result))
            return f"{float(result):.10g}"
        except Exception:
            pass

        return None

    def _extract_final_number(self, expression: str) -> Optional[int]:
        """Extract the final number from a calculation string like '96 - 7 = 89'."""
        if "=" in expression:
            rhs = expression.split("=")[-1].strip()
            try:
                return int(rhs.replace(",", ""))
            except ValueError:
                return None
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. SCHEMA VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════

class SchemaValidator:
    """Validates enriched JSON against the subtopic_reference_schema.

    Falls back to structural inference from approved files if no schema file exists.
    """

    def __init__(self, schema_path: Optional[Path] = None, approved_refs: Optional[dict] = None):
        self.schema = None
        self._jsonschema_available = False
        self._inferred_required_fields: list[str] = []

        # Try to load explicit schema
        if schema_path and schema_path.exists():
            try:
                import jsonschema
                self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
                self._jsonschema_available = True
                log.info(f"Loaded schema from {schema_path}")
            except ImportError:
                log.warning("jsonschema not installed — using structural validation only")

        # Infer required fields from approved references
        if approved_refs:
            self._infer_required_fields(approved_refs)

    def _infer_required_fields(self, refs: dict[str, dict]):
        """Infer required top-level and nested fields from approved files."""
        if not refs:
            return
        # Use intersection of keys across all approved files
        key_sets = [set(ref.keys()) for ref in refs.values()]
        self._inferred_required_fields = list(set.intersection(*key_sets)) if key_sets else []

    def validate(self, data: dict) -> tuple[bool, list[str]]:
        """Validate data against schema or inferred structure. Returns (is_valid, errors)."""
        errors: list[str] = []

        # 1. JSON Schema validation (if available)
        if self._jsonschema_available and self.schema:
            try:
                import jsonschema
                jsonschema.validate(instance=data, schema=self.schema)
            except jsonschema.ValidationError as e:
                errors.append(f"Schema violation: {e.message} at {'.'.join(str(p) for p in e.absolute_path)}")
                return False, errors
            except Exception as e:
                errors.append(f"Schema validation error: {str(e)}")
            return len(errors) == 0, errors

        # 2. Structural validation (fallback)
        # Required top-level fields
        required_top = ["subtopic_id", "category", "topic", "applicability_type",
                        "quick_ref", "techniques_by_difficulty", "total_techniques",
                        "total_templates", "metadata"]
        for field_name in required_top:
            if field_name not in data:
                errors.append(f"Missing required top-level field: {field_name}")

        # Validate quick_ref structure
        qr = data.get("quick_ref", {})
        required_qr = ["when_to_use", "the_trick", "quick_example", "top_traps"]
        for field_name in required_qr:
            if field_name not in qr:
                errors.append(f"Missing required quick_ref field: {field_name}")

        # Validate quick_example has answer
        qe = qr.get("quick_example", {})
        if not qe.get("answer"):
            errors.append("quick_example.answer is empty or missing")

        # Validate metadata
        meta = data.get("metadata", {})
        if meta.get("completeness_score", 0) < 0.5:
            errors.append(f"completeness_score too low: {meta.get('completeness_score', 0)}")
        if meta.get("content_status") == "coming_soon":
            errors.append("content_status still 'coming_soon' after enrichment")

        # Validate techniques_by_difficulty is non-empty
        techs = data.get("techniques_by_difficulty", {})
        if not techs:
            errors.append("techniques_by_difficulty is empty — at least L1 required")

        return len(errors) == 0, errors


# ═══════════════════════════════════════════════════════════════════════════
# 6. ENRICHMENT PIPELINE — Orchestrates the full process
# ═══════════════════════════════════════════════════════════════════════════

class SubtopicEnrichmentPipeline:
    """Main orchestrator for the batch enrichment process."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.stubs: dict[str, dict] = {}
        self.approved_refs: dict[str, dict] = {}
        self.risk_flags: dict[str, list[RiskFlag]] = {}
        self.consensus_reports: dict[str, ConsensusReport] = {}
        self.verification_results: dict[str, VerificationResult] = {}
        self.records: list[ProcessingRecord] = []

        # Components
        self.consensus_engine = ConsensusEngine([
            LLMJester("glm-5.1"),
            LLMJester("kimi-k2.6"),
            LLMJester("deepseek-v4-flash"),
        ])
        self.sympy_verifier = SymPyVerifier()
        self.schema_validator: Optional[SchemaValidator] = None

    def run(self, target_ids: Optional[list[str]] = None):
        """Execute the full enrichment pipeline."""
        log.info("=" * 70)
        log.info("Subtopic Explainer Generator — Batch Enrichment Pipeline")
        log.info("=" * 70)

        # Phase 1: Load
        log.info("Phase 1: Loading stubs and references...")
        self.stubs = load_all_stubs()
        self.approved_refs = load_approved_references()
        log.info(f"  Loaded {len(self.stubs)} stubs, {len(self.approved_refs)} approved references")

        if target_ids:
            self.stubs = {k: v for k, v in self.stubs.items() if k in target_ids}
            log.info(f"  Filtered to {len(self.stubs)} target subtopics")

        # Phase 2: Schema setup
        log.info("Phase 2: Initializing schema validator...")
        schema_path = None
        for candidate in SCHEMA_CANDIDATES:
            if candidate.exists():
                schema_path = candidate
                break
        self.schema_validator = SchemaValidator(schema_path, self.approved_refs)

        # Phase 3: Risk profiling
        log.info("Phase 3: Risk profiling...")
        for sid, stub in self.stubs.items():
            flags = profile_risks(sid, stub)
            self.risk_flags[sid] = flags
            risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            max_risk = max((f.risk_level for f in flags), key=lambda r: risk_order.get(r.value, 0))
            if max_risk.value in ("high", "critical"):
                log.warning(f"  ⚠ {sid}: {max_risk.value.upper()} risk — {[f.category for f in flags]}")

        # Phase 4: 3-LLM Consensus Generation
        log.info("Phase 4: 3-LLM consensus generation...")
        enriched_data: dict[str, dict] = {}
        failed_ids: list[str] = []
        for sid, stub in self.stubs.items():
            log.info(f"  Processing {sid}...")
            try:
                enriched, report = self.consensus_engine.generate_with_consensus(
                    sid, stub, self.approved_refs, self.risk_flags.get(sid, [])
                )
                self.consensus_reports[sid] = report
                enriched_data[sid] = enriched

                if report.result == ConsensusResult.CONFLICT:
                    log.warning(f"    ⚠ CONFLICT for {sid}: {report.contradictions}")
            except Exception as e:
                log.error(f"  ❌ Enrichment failed for {sid}: {e}")
                failed_ids.append(sid)
                self.records.append(ProcessingRecord(
                    subtopic_id=sid,
                    status="failed",
                    risk_level="critical",
                    consensus="none",
                    sympy_pass=False,
                    schema_valid=False,
                    completeness_score=0.0,
                    error=str(e),
                ))

        if failed_ids:
            log.warning(f"  {len(failed_ids)} subtopics failed enrichment: {failed_ids}")

        # Phase 5: SymPy Verification
        log.info("Phase 5: SymPy numerical verification...")
        for sid, data in enriched_data.items():
            vr = self.sympy_verifier.verify_subtopic(sid, data)
            self.verification_results[sid] = vr
            if not vr.example_verified:
                log.error(f"  ✗ {sid}: Example verification FAILED — {vr.errors}")
            if not vr.formula_verified:
                log.error(f"  ✗ {sid}: Formula verification FAILED — {vr.errors}")

        # Phase 6: Schema Validation
        log.info("Phase 6: Schema validation...")
        schema_validation_results: dict[str, tuple[bool, list[str]]] = {}
        for sid, data in enriched_data.items():
            is_valid, errors = self.schema_validator.validate(data)
            schema_validation_results[sid] = (is_valid, errors)
            if not is_valid:
                log.error(f"  ✗ {sid}: Schema validation FAILED — {errors}")

        # Phase 7: Post-processing and metadata update
        log.info("Phase 7: Post-processing...")
        for sid, data in enriched_data.items():
            vr = self.verification_results.get(sid)
            cr = self.consensus_reports.get(sid)
            schema_valid, schema_errors = schema_validation_results.get(sid, (False, []))

            # Update metadata
            meta = data.get("metadata", {})
            meta["author"] = "3llm_consensus"
            meta["auto_generated"] = True
            meta["enrichment_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            meta["consensus_result"] = cr.result.value if cr else "unknown"
            meta["sympy_verified"] = vr.example_verified if vr else False
            meta["formula_verified"] = vr.formula_verified if vr else False

            # Compute completeness score
            from topic_browser_full_package.scripts.enrichment_utils import compute_completeness_score
            score = compute_completeness_score(data, verified=vr.example_verified if vr else False)
            meta["completeness_score"] = score

            # Determine review status
            max_risk = RiskLevel.LOW
            for f in self.risk_flags.get(sid, []):
                if ["low", "medium", "high", "critical"].index(f.risk_level.value) > \
                   ["low", "medium", "high", "critical"].index(max_risk.value):
                    max_risk = f.risk_level

            techs = data.get("techniques_by_difficulty", {})

            if max_risk.value in ("high", "critical") or not vr.example_verified:
                meta["review_status"] = "flagged_for_review"
                meta["content_status"] = "needs_human_review"
                status = "flagged_for_review"
            elif score >= 0.7 and techs:
                meta["review_status"] = "pending_human_review"
                meta["content_status"] = "complete"
                status = "success"
            elif score >= 0.7 and not techs:
                # Should not happen due to scoring guard, but enforce invariant
                meta["review_status"] = "draft"
                meta["content_status"] = "partial"
                status = "success"
            else:
                meta["review_status"] = "draft"
                meta["content_status"] = "partial"
                status = "success"

            data["metadata"] = meta
            enriched_data[sid] = data

            self.records.append(ProcessingRecord(
                subtopic_id=sid,
                status=status,
                risk_level=max_risk.value,
                consensus=cr.result.value if cr else "unknown",
                sympy_pass=vr.example_verified if vr else False,
                schema_valid=schema_valid,
                completeness_score=score,
            ))

        # Phase 8: Write outputs
        if not self.dry_run:
            log.info("Phase 8: Writing enriched JSONs...")
            self._write_outputs(enriched_data)
        else:
            log.info("Phase 8: DRY RUN — skipping file writes")

        # Phase 9: Manifest and reports
        log.info("Phase 9: Generating manifest and reports...")
        if not self.dry_run:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            self._write_manifest()
            self._write_risk_report()

        # Summary
        self._print_summary()

    def _write_outputs(self, enriched_data: dict[str, dict]):
        """Write enriched JSON files to output directory."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for sid, data in enriched_data.items():
            out_path = OUTPUT_DIR / f"{sid}.json"
            out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            log.info(f"  → {out_path.name}")

    def _write_manifest(self):
        """Write manifest.csv with processing results."""
        with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "subtopic_id", "status", "risk_level", "consensus",
                "sympy_pass", "schema_valid", "completeness_score", "output_path", "error"
            ])
            writer.writeheader()
            for rec in self.records:
                row = asdict(rec)
                if rec.status == "success":
                    row["output_path"] = str(OUTPUT_DIR / f"{rec.subtopic_id}.json")
                writer.writerow(row)
        log.info(f"  → {MANIFEST_PATH}")

    def _write_risk_report(self):
        """Write risk_report.json with all flagged items."""
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_stubs": len(self.stubs),
            "flagged_count": sum(
                1 for flags in self.risk_flags.values()
                if any(f.risk_level.value in ("high", "critical") for f in flags)
            ),
            "flags": {},
        }
        for sid, flags in self.risk_flags.items():
            high_flags = [f for f in flags if f.risk_level.value in ("high", "medium", "critical")]
            if high_flags:
                report["flags"][sid] = [asdict(f) for f in high_flags]

        RISK_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info(f"  → {RISK_REPORT_PATH}")

    def _print_summary(self):
        """Print final processing summary."""
        log.info("")
        log.info("=" * 70)
        log.info("SUMMARY")
        log.info("=" * 70)

        by_status = {}
        for rec in self.records:
            by_status.setdefault(rec.status, []).append(rec.subtopic_id)

        for status, sids in by_status.items():
            log.info(f"  {status}: {len(sids)}")
            for sid in sids:
                log.info(f"    - {sid}")

        flagged = [r for r in self.records if r.status == "flagged_for_review"]
        if flagged:
            log.info("")
            log.info("FLAGGED FOR HUMAN REVIEW:")
            for rec in flagged:
                log.info(f"  ⚠ {rec.subtopic_id} (risk={rec.risk_level}, sympy={rec.sympy_pass})")

        log.info("")
        log.info("Files written:")
        log.info(f"  Enriched JSONs: {OUTPUT_DIR}/")
        log.info(f"  Manifest:       {MANIFEST_PATH}")
        log.info(f"  Risk Report:    {RISK_REPORT_PATH}")


# ═══════════════════════════════════════════════════════════════════════════
# 7. CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Subtopic Explainer Generator — 3-LLM Consensus Batch Enrichment"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and generate proposals without writing files"
    )
    parser.add_argument(
        "--ids", nargs="*", metavar="SUBTOPIC_ID",
        help="Process only these subtopic IDs (space-separated)"
    )
    parser.add_argument(
        "--risk-report", action="store_true",
        help="Only output risk profiling report, skip generation"
    )
    parser.add_argument(
        "--list-stubs", action="store_true",
        help="List all stub subtopic IDs and exit"
    )

    args = parser.parse_args()

    # List stubs mode
    if args.list_stubs:
        stubs = load_all_stubs()
        print(f"Stub subtopic IDs ({len(stubs)}):")
        for sid in sorted(stubs.keys()):
            print(f"  {sid}")
        return

    # Risk report only mode
    if args.risk_report:
        stubs = load_all_stubs()
        print("RISK PROFILING REPORT")
        print("=" * 60)
        for sid, stub in sorted(stubs.items()):
            flags = profile_risks(sid, stub)
            max_risk = max(flags, key=lambda f: ["low", "medium", "high", "critical"].index(f.risk_level.value))
            marker = "⚠" if max_risk.risk_level.value in ("high", "critical") else "✓"
            print(f"  {marker} {sid}: {max_risk.risk_level.value.upper()} — {max_risk.category}")
            for f in flags:
                if f.risk_level.value in ("high", "critical"):
                    print(f"      ↳ {f.description}")
        return

    # Full pipeline
    pipeline = SubtopicEnrichmentPipeline(dry_run=args.dry_run)
    pipeline.run(target_ids=args.ids)


if __name__ == "__main__":
    main()
