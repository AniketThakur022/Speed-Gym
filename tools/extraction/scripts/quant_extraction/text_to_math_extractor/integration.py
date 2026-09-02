"""
Integration with Hybrid Validator v3 Compute Engine

Bridge between text_to_math_extractor and existing compute_engine.
"""

from typing import Optional, Tuple, List, Dict, Any
import sys
from pathlib import Path

# Add path for importing existing compute_engine
sys.path.insert(0, str(Path(__file__).parent.parent / "hybrid_validator_v3"))

try:
    from compute_engine import (
        compute_from_latex,
        extract_answer_from_final,
        compare_answers,
    )
    COMPUTE_ENGINE_AVAILABLE = True
except ImportError:
    COMPUTE_ENGINE_AVAILABLE = False

from .extractor import TextToMathExtractor, ExtractionResult
from .confidence import ConfidenceLevel


class HybridValidatorBridge:
    """
    Bridge connecting TextToMathExtractor with Hybrid Validator v3.
    
    This provides a unified interface for processing both:
    1. LaTeX-based problems (handled by existing compute_engine)
    2. Plain-text problems (handled by text_to_math_extractor)
    
    Usage:
        bridge = HybridValidatorBridge()
        result = bridge.process_problem(problem_text, final_answer)
    """
    
    def __init__(self):
        self.text_extractor = TextToMathExtractor()
        self.compute_engine_available = COMPUTE_ENGINE_AVAILABLE
    
    def extract_latex(self, text: str) -> List[str]:
        """Extract LaTeX expressions from text using existing extractor."""
        try:
            from latex_extractor import extract_math
            problem_text, latex_list = extract_math(text)
            return latex_list
        except ImportError:
            # Fallback: simple regex extraction
            import re
            latex_pattern = re.compile(r'\$([^$]+?)\$')
            return latex_pattern.findall(text)
    
    def process_problem(
        self,
        problem_text: str,
        final_answer: str,
        template_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a problem using appropriate method.
        
        Strategy:
        1. Check for LaTeX - if present, use existing compute_engine
        2. If no LaTeX, try text-to-math extraction
        3. Return unified result format
        
        Args:
            problem_text: The problem statement
            final_answer: Expected answer
            template_id: Optional template identifier
            
        Returns:
            Unified result dictionary
        """
        result = {
            "template_id": template_id,
            "problem_text": problem_text,
            "final_answer": final_answer,
            "method": None,
            "status": "pending",
            "computed": None,
            "match": None,
            "match_type": None,
            "error": None,
        }
        
        # Step 1: Check for LaTeX
        latex_list = self.extract_latex(problem_text)
        
        if latex_list and self.compute_engine_available:
            # Use existing LaTeX compute engine
            result["method"] = "latex"
            result["latex_found"] = latex_list
            
            try:
                computed_val, status, error = compute_from_latex(latex_list)
                
                if computed_val is not None:
                    result["computed"] = str(computed_val)
                    result["status"] = status
                    
                    # Compare with expected
                    expected_val = extract_answer_from_final(final_answer)
                    is_match, _, _, match_type = compare_answers(computed_val, expected_val)
                    
                    result["match"] = is_match
                    result["match_type"] = match_type
                else:
                    result["status"] = status
                    result["error"] = error
                    
            except Exception as e:
                result["status"] = "compute_error"
                result["error"] = str(e)
        
        else:
            # Step 2: Try text-to-math extraction
            result["method"] = "text_extraction"
            
            extraction = self.text_extractor.process(
                text=problem_text,
                expected_answer=final_answer,
                template_id=template_id
            )
            
            result["extraction"] = extraction.to_dict()
            result["confidence"] = extraction.confidence.level.value if extraction.confidence else None
            
            # Map extraction result to unified format
            if extraction.verification_status == "match":
                result["status"] = "ok"
                result["computed"] = extraction.computed_value
                result["match"] = True
                result["match_type"] = "extracted_match"
            elif extraction.verification_status == "mismatch":
                result["status"] = "ok"
                result["computed"] = extraction.computed_value
                result["match"] = False
                result["match_type"] = "extracted_mismatch"
            elif extraction.verification_status == "rejected":
                result["status"] = "needs_llm"
                result["reason"] = "text_extraction_rejected"
            else:
                result["status"] = extraction.verification_status
        
        return result
    
    def batch_process(
        self,
        problems: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Process multiple problems.
        
        Args:
            problems: List of dicts with 'problem_text' and 'final_answer'
            
        Returns:
            List of result dictionaries
        """
        results = []
        
        for i, prob in enumerate(problems):
            result = self.process_problem(
                problem_text=prob.get("problem_text", ""),
                final_answer=prob.get("final_answer", ""),
                template_id=prob.get("template_id", f"problem_{i}")
            )
            results.append(result)
        
        return results
    
    def get_extraction_stats(self) -> Dict[str, Any]:
        """Get statistics from text extractor."""
        return self.text_extractor.get_stats()


def create_audit_report(
    results: List[Dict[str, Any]],
    output_path: str
) -> None:
    """
    Create a detailed audit report from processing results.
    
    Args:
        results: List of result dictionaries from batch_process
        output_path: Path to write report
    """
    # Categorize results
    latex_processed = [r for r in results if r.get("method") == "latex"]
    text_extracted = [r for r in results if r.get("method") == "text_extraction"]
    needs_llm = [r for r in results if r.get("status") == "needs_llm"]
    
    # Calculate statistics
    stats = {
        "total_problems": len(results),
        "latex_processed": len(latex_processed),
        "text_extracted": len(text_extracted),
        "needs_llm": len(needs_llm),
        "latex_matches": sum(1 for r in latex_processed if r.get("match")),
        "latex_mismatches": sum(1 for r in latex_processed if r.get("match") == False),
        "extraction_matches": sum(1 for r in text_extracted if r.get("match")),
        "extraction_mismatches": sum(1 for r in text_extracted if r.get("match") == False),
    }
    
    # Write report
    import json
    with open(output_path, 'w') as f:
        json.dump({
            "summary": stats,
            "results": results,
        }, f, indent=2)


# Integration function for existing pipelines
def process_solve_along_template(
    template: Dict[str, Any],
    extractor: Optional[TextToMathExtractor] = None
) -> Dict[str, Any]:
    """
    Process a single solve_along template.
    
    This is a convenience function for integration with existing pipelines.
    
    Args:
        template: Template dictionary
        extractor: Optional pre-configured extractor
        
    Returns:
        Processing result
    """
    extractor = extractor or TextToMathExtractor()
    
    # Extract problem info
    sequence = template.get("solve_along_sequence", {})
    current_problem = sequence.get("current_problem", {})
    
    problem_text = current_problem.get("question_text", "")
    final_answer = sequence.get("final_answer", "")
    template_id = template.get("template_name", "")
    
    if not problem_text:
        return {
            "template_id": template_id,
            "status": "no_problem_text",
            "error": "No question_text found in template"
        }
    
    # Process
    result = extractor.process(
        text=problem_text,
        expected_answer=final_answer,
        template_id=template_id,
        metadata={"template": template}
    )
    
    return result.to_dict()
