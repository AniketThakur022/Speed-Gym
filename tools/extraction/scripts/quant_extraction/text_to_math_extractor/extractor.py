"""
Core TextToMathExtractor Class

Main entry point for extracting computable math from plain-text problems.
Integrates pattern matching, confidence scoring, and compute verification.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import hashlib

from .patterns import MathPatterns, PatternDefinition, DEFAULT_PATTERNS
from .confidence import ConfidenceScorer, ConfidenceLevel, ConfidenceScore
from .compute_verifier import ComputeVerifier


@dataclass
class ExtractionResult:
    """Result of text-to-math extraction."""
    original_text: str
    cleaned_text: str
    pattern_matched: Optional[str]
    operation: Optional[str]
    extracted_numbers: List[str] = field(default_factory=list)
    sympy_expression: Optional[str] = None
    computed_value: Optional[str] = None
    expected_answer: Optional[str] = None
    verification_status: str = "pending"  # pending | match | mismatch | error
    confidence: Optional[ConfidenceScore] = None
    extraction_time: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "original_text": self.original_text,
            "cleaned_text": self.cleaned_text,
            "pattern_matched": self.pattern_matched,
            "operation": self.operation,
            "extracted_numbers": self.extracted_numbers,
            "sympy_expression": self.sympy_expression,
            "computed_value": self.computed_value,
            "expected_answer": self.expected_answer,
            "verification_status": self.verification_status,
            "confidence": {
                "level": self.confidence.level.value if self.confidence else None,
                "score": self.confidence.score if self.confidence else None,
                "reason": self.confidence.reason if self.confidence else None,
            },
            "extraction_time": self.extraction_time,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionResult":
        """Create from dictionary."""
        confidence_data = data.get("confidence", {})
        confidence = None
        if confidence_data.get("level"):
            confidence = ConfidenceScore(
                level=ConfidenceLevel(confidence_data["level"]),
                score=confidence_data.get("score", 0.0),
                reason=confidence_data.get("reason", ""),
                details={}
            )
        
        return cls(
            original_text=data.get("original_text", ""),
            cleaned_text=data.get("cleaned_text", ""),
            pattern_matched=data.get("pattern_matched"),
            operation=data.get("operation"),
            extracted_numbers=data.get("extracted_numbers", []),
            sympy_expression=data.get("sympy_expression"),
            computed_value=data.get("computed_value"),
            expected_answer=data.get("expected_answer"),
            verification_status=data.get("verification_status", "pending"),
            confidence=confidence,
            extraction_time=data.get("extraction_time", ""),
            metadata=data.get("metadata", {}),
        )


class TextToMathExtractor:
    """
    Main extractor class for converting plain-text math to computable expressions.
    
    Usage:
        extractor = TextToMathExtractor()
        
        # Process single problem
        result = extractor.process("Multiply 87265 by 32117")
        
        # Process with expected answer
        result = extractor.process(
            "Multiply 87265 by 32117",
            expected_answer="2,800,797,005"
        )
        
        # Batch processing
        results = extractor.process_batch(problem_list)
    """
    
    def __init__(
        self,
        patterns: Optional[MathPatterns] = None,
        confidence_scorer: Optional[ConfidenceScorer] = None,
        compute_verifier: Optional[ComputeVerifier] = None,
        min_confidence: ConfidenceLevel = ConfidenceLevel.LOW
    ):
        """
        Initialize extractor.
        
        Args:
            patterns: Pattern definitions (uses default if None)
            confidence_scorer: Confidence scorer (creates default if None)
            compute_verifier: Compute verifier (creates default if None)
            min_confidence: Minimum confidence level to accept extraction
        """
        self.patterns = patterns or DEFAULT_PATTERNS
        self.confidence_scorer = confidence_scorer or ConfidenceScorer()
        self.compute_verifier = compute_verifier or ComputeVerifier()
        self.min_confidence = min_confidence
        
        # Statistics tracking
        self.stats = {
            "total_processed": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "rejected": 0,
            "verified_match": 0,
            "verified_mismatch": 0,
            "verification_error": 0,
        }
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize input text."""
        if not text:
            return ""
        
        # Normalize whitespace
        cleaned = " ".join(text.split())
        
        # Replace unicode multiplication signs
        cleaned = cleaned.replace('×', 'x')
        cleaned = cleaned.replace('⋅', '*')
        cleaned = cleaned.replace('÷', '/')
        
        # Replace superscript numbers
        superscript_map = {
            '²': '^2',
            '³': '^3',
            '⁴': '^4',
            '⁵': '^5',
        }
        for sup, repl in superscript_map.items():
            cleaned = cleaned.replace(sup, repl)
        
        return cleaned
    
    def _has_latex(self, text: str) -> bool:
        """Check if text contains LaTeX."""
        latex_indicators = [
            r'\$', r'\\', r'\frac', r'\times', r'\div',
            r'\sqrt', r'\cdot', r'\sum', r'\int',
        ]
        return any(ind in text for ind in latex_indicators)
    
    def extract_from_text(self, text: str) -> Tuple[Optional[PatternDefinition], List[str]]:
        """
        Extract pattern and numbers from text.
        
        Returns:
            (matched_pattern, extracted_numbers)
        """
        cleaned = self._clean_text(text)
        
        # Find matching pattern
        pattern = self.patterns.find_matching_pattern(cleaned)
        
        if pattern is None:
            return None, []
        
        # Extract numbers
        numbers = self.patterns.extract_numbers(cleaned)
        
        return pattern, numbers
    
    def process(
        self,
        text: str,
        expected_answer: Optional[str] = None,
        template_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        """
        Process a single text problem.
        
        Args:
            text: Problem text
            expected_answer: Expected answer (for verification)
            template_id: Template identifier
            metadata: Additional metadata
            
        Returns:
            ExtractionResult with full extraction details
        """
        self.stats["total_processed"] += 1
        
        cleaned = self._clean_text(text)
        has_latex = self._has_latex(text)
        
        # Extract pattern and numbers
        pattern, numbers = self.extract_from_text(text)
        
        # Determine expected operand count from pattern
        expected_operands = self._estimate_operand_count(pattern, numbers)
        
        # Calculate confidence
        confidence = self.confidence_scorer.score_extraction(
            text=text,
            pattern_name=pattern.name if pattern else None,
            extracted_numbers=numbers,
            expected_operand_count=expected_operands,
            has_latex=has_latex
        )
        
        # Update confidence stats
        if confidence.level == ConfidenceLevel.HIGH:
            self.stats["high_confidence"] += 1
        elif confidence.level == ConfidenceLevel.MEDIUM:
            self.stats["medium_confidence"] += 1
        elif confidence.level == ConfidenceLevel.LOW:
            self.stats["low_confidence"] += 1
        else:
            self.stats["rejected"] += 1
        
        # Build result
        result = ExtractionResult(
            original_text=text,
            cleaned_text=cleaned,
            pattern_matched=pattern.name if pattern else None,
            operation=pattern.operation if pattern else None,
            extracted_numbers=numbers,
            expected_answer=expected_answer,
            confidence=confidence,
            metadata=metadata or {},
        )
        
        # Add template info to metadata
        if template_id:
            result.metadata["template_id"] = template_id
        
        # Skip verification if rejected
        if confidence.level == ConfidenceLevel.REJECT:
            result.verification_status = "rejected"
            return result
        
        # Skip verification if below minimum confidence (numeric comparison, NOT string)
        LEVEL_ORDER = {
            ConfidenceLevel.REJECT: 0,
            ConfidenceLevel.LOW: 1,
            ConfidenceLevel.MEDIUM: 2,
            ConfidenceLevel.HIGH: 3,
        }
        if LEVEL_ORDER[confidence.level] < LEVEL_ORDER[self.min_confidence]:
            result.verification_status = "skipped_low_confidence"
            return result
        
        # Build and verify expression
        if pattern and numbers:
            self._verify_result(result, pattern, numbers)
        
        return result
    
    def _estimate_operand_count(
        self,
        pattern: Optional[PatternDefinition],
        numbers: List[str]
    ) -> int:
        """Estimate expected number of operands from pattern."""
        if pattern is None:
            return len(numbers)
        
        # Pattern-specific operand counts
        operand_counts = {
            'bare_multiply_x': 2,
            'bare_multiply_dot': 2,
            'multiply_by': 2,
            'times': 2,
            'divide_by': 2,
            'add_two': 2,
            'subtract_from': 2,
            'minus': 2,
            'square_of': 1,
            'cube_of': 1,
            'sqrt_of': 1,
            'cbrt_of': 1,
            'power_of': 1,
            'percent_of': 2,
            'simplify_fraction': 2,
        }
        
        return operand_counts.get(pattern.name, len(numbers))
    
    def _verify_result(
        self,
        result: ExtractionResult,
        pattern: PatternDefinition,
        numbers: List[str]
    ):
        """Verify extraction by computing and comparing."""
        if not result.expected_answer:
            result.verification_status = "no_expected_answer"
            return
        
        try:
            verify_result = self.compute_verifier.verify_extraction(
                operation=pattern.operation,
                numbers=numbers,
                sympy_template=pattern.sympy_template,
                expected_answer=result.expected_answer,
                pattern_name=pattern.name
            )
            
            result.sympy_expression = verify_result["expression_build"].get("expression")
            result.computed_value = verify_result["computation"].get("computed_value")
            result.verification_status = verify_result["status"]
            
            # Update verification stats
            if result.verification_status == "match":
                self.stats["verified_match"] += 1
            elif result.verification_status == "mismatch":
                self.stats["verified_mismatch"] += 1
            else:
                self.stats["verification_error"] += 1
                
        except Exception as e:
            result.verification_status = f"verification_error: {str(e)}"
            self.stats["verification_error"] += 1
    
    def process_batch(
        self,
        items: List[Tuple[str, Optional[str]]],
        template_ids: Optional[List[str]] = None
    ) -> List[ExtractionResult]:
        """
        Process multiple problems in batch.
        
        Args:
            items: List of (text, expected_answer) tuples
            template_ids: Optional list of template IDs
            
        Returns:
            List of ExtractionResult
        """
        results = []
        
        for i, (text, expected) in enumerate(items):
            template_id = template_ids[i] if template_ids and i < len(template_ids) else None
            result = self.process(
                text=text,
                expected_answer=expected,
                template_id=template_id
            )
            results.append(result)
        
        return results
    
    def is_extractable(self, text: str) -> Tuple[bool, ConfidenceLevel]:
        """
        Quick check if text is extractable.
        
        Returns:
            (is_extractable, confidence_level)
        """
        pattern, numbers = self.extract_from_text(text)
        
        confidence = self.confidence_scorer.score_extraction(
            text=text,
            pattern_name=pattern.name if pattern else None,
            extracted_numbers=numbers,
            expected_operand_count=len(numbers),
            has_latex=self._has_latex(text)
        )
        
        return confidence.level != ConfidenceLevel.REJECT, confidence.level
    
    def get_stats(self) -> Dict[str, Any]:
        """Get extraction statistics."""
        return {
            **self.stats,
            "success_rate": (
                (self.stats["high_confidence"] + self.stats["medium_confidence"]) /
                max(self.stats["total_processed"], 1)
            ),
            "verification_accuracy": (
                self.stats["verified_match"] /
                max(self.stats["verified_match"] + self.stats["verified_mismatch"], 1)
            ),
        }
    
    def reset_stats(self):
        """Reset statistics counters."""
        self.stats = {
            "total_processed": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0,
            "rejected": 0,
            "verified_match": 0,
            "verified_mismatch": 0,
            "verification_error": 0,
        }
