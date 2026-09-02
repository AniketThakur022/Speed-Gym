#!/usr/bin/env python3
"""
SymPy Validation Layer — Computational verification with non-computable handling.

Extends existing compute_engine.py + compute_verifier.py with:
  1. Classification of computable vs non-computable problems
  2. Symbolic vs numeric answer normalization
  3. Integration boundary with LLM results
"""

import json
import re
import sys
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

import sympy as sp
sys.path.insert(0, str(Path(__file__).parent.parent))

from hybrid_validator_v3.compute_engine import (
    compute_from_latex,
    extract_answer_from_final,
    compare_answers,
)
from hybrid_validator_v3.latex_extractor import extract_math, clean_escaped_latex
from text_to_math_extractor.compute_verifier import ComputeVerifier
from dual_validator.decision_matrix import SymPyStatus


class SymPyValidator:
    """
    Wraps SymPy computation with problem-type awareness.
    """

    def __init__(self):
        self.compute_verifier = ComputeVerifier()

    def is_computable(self, problem_text: str) -> Tuple[bool, str]:
        """
        Check whether a problem is computable.

        Returns (is_computable, reason).
        """
        if not problem_text or not problem_text.strip():
            return False, "empty_text"

        # LaTeX present → attempt computation
        _, latex_list = extract_math(problem_text)
        if latex_list:
            return True, "has_latex"

        # Pure arithmetic with numbers
        digits = re.findall(r'\d+', problem_text)
        if len(digits) >= 1 and len(problem_text.split()) <= 15:
            return True, "has_numbers"

        # Non-computable indicators
        noncomp_markers = ["prove", "explain", "describe", "find the", "show that",
                           "determine", "justify", "derive", "state", "illustrate",
                           "if a train", "how many", "what is the", "which of"]
        lower = problem_text.lower()
        marker_count = sum(1 for m in noncomp_markers if m in lower)

        if marker_count >= 1 and len(digits) <= 2:
            return False, f"textual_problem_markers={marker_count}"

        # Diagrams — not computable from text
        if "[IMAGE]" in problem_text or "[DIAG" in problem_text or "figure" in lower:
            return False, "has_diagram_reference"

        # Symbolic algebra without concrete numbers
        if len(digits) == 0 and re.search(r'[a-z]', lower):
            return False, "symbolic_only"

        return True, "general_numeric"

    def extract_and_compute(self, problem_text: str) -> Dict[str, Any]:
        """
        Extract math from problem text and compute using SymPy.

        Returns dict with computed_value, status, error, etc.
        """
        result = {
            "computed_value": None,
            "status": "unknown",
            "error": None,
        }

        _, latex_list = extract_math(problem_text)

        # Try LaTeX computation first
        if latex_list:
            computed, status, error = compute_from_latex(latex_list)
            if computed is not None:
                try:
                    result["computed_value"] = float(computed.evalf())
                except Exception:
                    result["computed_value"] = str(computed)
                result["status"] = status
                return result
            result["status"] = status
            if error:
                result["error"] = error[200:]

        # Fallback: text-to-math extraction
        from text_to_math_extractor.extractor import TextToMathExtractor
        from text_to_math_extractor.confidence import ConfidenceLevel
        try:
            extractor = TextToMathExtractor(min_confidence=ConfidenceLevel.MEDIUM)
            extraction = extractor.process(text=problem_text)
            if extraction.computed_value:
                result["computed_value"] = extraction.computed_value
                result["status"] = "ok"
                return result
        except Exception:
            pass

        if result["status"] == "unknown":
            result["status"] = "no_latex"

        return result

    def compare_with_expected(
        self,
        computed_value: Any,
        expected_answer: str,
    ) -> Tuple[SymPyStatus, Optional[str], str]:
        """
        Compare computed value with the template's expected answer.

        Returns (sympy_status, computed_str, match_type).
        """
        if computed_value is None:
            return SymPyStatus.NONCOMP, None, "no_computed_value"

        computed_str = str(computed_value)
        if not expected_answer:
            return SymPyStatus.NONCOMP, computed_str, "no_expected_answer"

        try:
            expected_expr = extract_answer_from_final(expected_answer)
        except Exception:
            return SymPyStatus.NONCOMP, computed_str, "expected_parse_failed"

        if expected_expr is None:
            return SymPyStatus.NONCOMP, computed_str, "expected_extraction_failed"

        try:
            comp_expr = sp.sympify(computed_value)
        except Exception:
            return SymPyStatus.NONCOMP, computed_str, "computed_sympify_failed"

        match, _, _, match_type = compare_answers(comp_expr, expected_expr)

        return (SymPyStatus.MATCH if match else SymPyStatus.MISMATCH), computed_str, match_type

    def run_full_verification(
        self,
        problem_text: str,
        expected_answer: str,
    ) -> Dict[str, Any]:
        """
        Full SymPy verification pipeline.

        Returns dict consumable by DecisionMatrix.
        """
        is_comp, reason = self.is_computable(problem_text)

        if not is_comp:
            return {
                "sympy_status": SymPyStatus.NONCOMP,
                "computed_value": None,
                "reason": reason,
                "match_type": None,
            }

        compute_result = self.extract_and_compute(problem_text)
        sympy_status, computed_str, match_type = self.compare_with_expected(
            compute_result["computed_value"],
            expected_answer,
        )

        return {
            "sympy_status": sympy_status,
            "computed_value": computed_str,
            "computed_raw": compute_result["computed_value"],
            "status_detail": compute_result["status"],
            "error": compute_result.get("error"),
            "match_type": match_type,
            "reason": reason if not is_comp else None,
        }

    def verify_against_llm_answer(
        self,
        llm_correct_answer: str,
        expected_answer: str,
    ) -> Tuple[bool, str]:
        """
        Cross-check the LLM's claimed correct answer against SymPy.
        Used when LLM says template is wrong but offers a correct answer.
        """
        if not llm_correct_answer:
            return False, "no_llm_answer"

        comp_result = self.extract_and_compute(llm_correct_answer)
        if comp_result["computed_value"] is None:
            return False, "llm_answer_not_computable"

        sympy_status, _, match_type = self.compare_with_expected(
            comp_result["computed_value"],
            expected_answer,
        )

        # If SymPy says LLM's answer matches the template → template may be correct after all
        return sympy_status == SymPyStatus.MATCH, f"llm_answer_verification={match_type}"
