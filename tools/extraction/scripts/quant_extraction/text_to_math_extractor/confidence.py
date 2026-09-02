"""
Confidence Scoring System for Text-to-Math Extraction

Assigns confidence levels based on:
1. Pattern clarity (specific vs generic patterns)
2. Number extraction success
3. Ambiguity detection
4. Known failure modes
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import re


class ConfidenceLevel(Enum):
    """Confidence levels for extraction results."""
    HIGH = "high"      # Clear pattern, extracted numbers, computable
    MEDIUM = "medium"  # Pattern matched but some ambiguity
    LOW = "low"        # Ambiguous language, questionable extraction
    REJECT = "reject"  # Cannot extract - needs LLM


@dataclass
class ConfidenceScore:
    """Confidence score with detailed breakdown."""
    level: ConfidenceLevel
    score: float  # 0.0 to 1.0
    reason: str
    details: Dict[str, Any]
    
    def __repr__(self) -> str:
        return f"ConfidenceScore({self.level.value}, {self.score:.2f}, '{self.reason}')"


class ConfidenceScorer:
    """
    Scores confidence of text-to-math extraction.
    
    Scoring Factors:
    - Pattern specificity (0.3): Specific patterns score higher
    - Number extraction (0.25): All numbers must be extractable
    - Text ambiguity (0.25): No ambiguous words
    - Structure match (0.2): Text structure matches pattern
    """
    
    # Words that indicate ambiguity or word problems
    AMBIGUOUS_WORDS = {
        'if', 'when', 'where', 'how', 'why', 'who', 'what',
        'solve', 'find', 'determine',  # Can be okay but need context
        'john', 'mary', 'alice', 'bob',  # Person names
        'apple', 'orange', 'banana', 'fruit',  # Objects
        'train', 'car', 'bike', 'walk',  # Motion
        'time', 'hour', 'minute', 'second', 'day',  # Time units (ambiguous without context)
        'price', 'cost', 'buy', 'sell', 'profit', 'loss',  # Commerce
        'age', 'year', 'ago', 'later',  # Age problems
        'ratio', 'proportion', 'mixture',  # Complex problems
        'prove', 'show', 'demonstrate',  # Proofs
        'explain', 'describe', 'discuss',  # Conceptual
    }
    
    # High-confidence indicator words
    STRONG_MATH_WORDS = {
        'multiply', 'product', 'divide', 'division', 'add', 'sum',
        'subtract', 'minus', 'square', 'cube', 'root', 'lcm', 'gcd',
        'hcf', 'percent', 'simplify', 'evaluate', 'calculate',
    }
    
    # Patterns that are very specific (higher confidence)
    HIGH_SPECIFICITY_PATTERNS = {
        'bare_multiply_x', 'bare_multiply_dot', 'times',
        'multiply_by', 'divide_by', 'square_of', 'cube_of',
        'sqrt_of', 'cbrt_of', 'lcm_of', 'gcd_of', 'percent_of',
    }
    
    BARE_PATTERNS = {'bare_multiply_x', 'bare_multiply_dot'}
    
    # Patterns with lower specificity
    MEDIUM_SPECIFICITY_PATTERNS = {
        'add_list', 'multiply_list', 'power_of', 'simplify_fraction',
    }
    
    def __init__(self):
        self.ambiguous_pattern = re.compile(
            r'\b(' + '|'.join(self.AMBIGUOUS_WORDS) + r')\b',
            re.IGNORECASE
        )
        self.strong_math_pattern = re.compile(
            r'\b(' + '|'.join(self.STRONG_MATH_WORDS) + r')\b',
            re.IGNORECASE
        )
    
    def score_extraction(
        self,
        text: str,
        pattern_name: Optional[str],
        extracted_numbers: List[str],
        expected_operand_count: int,
        has_latex: bool = False
    ) -> ConfidenceScore:
        """
        Calculate confidence score for an extraction.
        
        Args:
            text: Original problem text
            pattern_name: Name of matched pattern (or None)
            extracted_numbers: Numbers extracted from text
            expected_operand_count: Expected number of operands
            has_latex: Whether LaTeX was found in text
            
        Returns:
            ConfidenceScore with level and details
        """
        details = {
            "pattern_name": pattern_name,
            "extracted_numbers": extracted_numbers,
            "expected_operands": expected_operand_count,
            "has_latex": has_latex,
        }
        
        # Base rejection conditions
        if self._should_reject(text, pattern_name, extracted_numbers):
            reason = self._get_rejection_reason(text, pattern_name, extracted_numbers)
            return ConfidenceScore(
                level=ConfidenceLevel.REJECT,
                score=0.0,
                reason=reason,
                details=details
            )
        
        # Calculate component scores
        scores = {
            "pattern_specificity": self._score_pattern_specificity(pattern_name),
            "number_extraction": self._score_number_extraction(extracted_numbers, expected_operand_count),
            "text_clarity": self._score_text_clarity(text),
            "structure_match": self._score_structure_match(text, pattern_name),
        }
        
        # Weighted sum
        weights = {
            "pattern_specificity": 0.30,
            "number_extraction": 0.30,
            "text_clarity": 0.25,
            "structure_match": 0.15,
        }
        
        total_score = sum(scores[k] * weights[k] for k in scores)
        
        # Adjust for LaTeX presence (usually clearer)
        if has_latex:
            total_score = min(1.0, total_score + 0.05)
        
        details["component_scores"] = scores
        details["weighted_score"] = total_score
        
        # Determine level
        if total_score >= 0.85:
            level = ConfidenceLevel.HIGH
            reason = "Clear pattern match with extractable numbers"
        elif total_score >= 0.60:
            level = ConfidenceLevel.MEDIUM
            reason = "Pattern matched with minor ambiguities"
        elif total_score >= 0.40:
            level = ConfidenceLevel.LOW
            reason = "Ambiguous extraction - verify before using"
        else:
            level = ConfidenceLevel.REJECT
            reason = "Too ambiguous or incomplete for reliable extraction"
        
        return ConfidenceScore(
            level=level,
            score=round(total_score, 2),
            reason=reason,
            details=details
        )
    
    def _should_reject(self, text: str, pattern_name: Optional[str], numbers: List[str]) -> bool:
        """Check if extraction should be rejected outright."""
        # No pattern matched
        if pattern_name is None:
            return True
        
        # No numbers found
        if not numbers:
            return True
        
        # Bare math patterns (e.g. "6 x 9") are always valid
        if pattern_name in self.BARE_PATTERNS and len(numbers) >= 2:
            return False
        
        # Contains question words that indicate word problems
        question_words = ['which', 'who', 'what is the', 'how many', 'how much']
        text_lower = text.lower()
        
        # Check for word problem indicators
        word_problem_indicators = [
            'there are', 'there were', 'there is', 'if a', 'if the',
            'person', 'people', 'student', 'teacher',
            'has', 'have', 'had', 'bought', 'sold', 'traveled',
        ]
        
        # Count word problem indicators
        indicator_count = sum(1 for ind in word_problem_indicators if ind in text_lower)
        if indicator_count >= 2:
            return True
        
        # Very long text (likely complex problem)
        if len(text.split()) > 25:
            return True
        
        return False
    
    def _get_rejection_reason(self, text: str, pattern_name: Optional[str], numbers: List[str]) -> str:
        """Get specific reason for rejection."""
        if pattern_name is None:
            return "No matching pattern found"
        if not numbers:
            return "No extractable numbers found"
        if len(text.split()) > 20:
            return "Text too long/complex for pattern matching"
        
        text_lower = text.lower()
        word_problem_indicators = [
            'person', 'people', 'student', 'bought', 'sold', 'traveled',
        ]
        for ind in word_problem_indicators:
            if ind in text_lower:
                return f"Word problem detected (contains '{ind}')"
        
        return "Ambiguous or unsuitable for pattern extraction"
    
    def _score_pattern_specificity(self, pattern_name: Optional[str]) -> float:
        """Score pattern specificity (0.0 to 1.0)."""
        if pattern_name is None:
            return 0.0
        
        if pattern_name in self.HIGH_SPECIFICITY_PATTERNS:
            return 1.0
        elif pattern_name in self.MEDIUM_SPECIFICITY_PATTERNS:
            return 0.7
        else:
            return 0.5
    
    def _score_number_extraction(
        self,
        extracted_numbers: List[str],
        expected_count: int
    ) -> float:
        """Score number extraction success (0.0 to 1.0)."""
        if not extracted_numbers:
            return 0.0
        
        if expected_count == 0:
            # No specific expectation
            return 1.0 if len(extracted_numbers) > 0 else 0.0
        
        extracted_count = len(extracted_numbers)
        
        if extracted_count == expected_count:
            return 1.0
        elif extracted_count > expected_count:
            # Extra numbers - might be okay
            return 0.7
        else:
            # Missing numbers
            ratio = extracted_count / expected_count
            return max(0.0, ratio - 0.2)
    
    def _score_text_clarity(self, text: str) -> float:
        """Score text clarity based on ambiguity indicators (0.0 to 1.0)."""
        text_lower = text.lower()
        
        # Count ambiguous words
        ambiguous_matches = len(self.ambiguous_pattern.findall(text))
        strong_math_matches = len(self.strong_math_pattern.findall(text))
        
        # Word count
        word_count = len(text.split())
        
        # Penalize for ambiguous words
        ambiguity_penalty = min(0.5, ambiguous_matches * 0.15)
        
        # Reward for strong math words
        math_bonus = min(0.3, strong_math_matches * 0.1)
        
        # Penalize for very long text
        length_penalty = 0.0
        if word_count > 15:
            length_penalty = min(0.3, (word_count - 15) * 0.02)
        
        score = 1.0 - ambiguity_penalty + math_bonus - length_penalty
        return max(0.0, min(1.0, score))
    
    def _score_structure_match(self, text: str, pattern_name: Optional[str]) -> float:
        """Score how well text structure matches pattern (0.0 to 1.0)."""
        if pattern_name is None:
            return 0.0
        
        text_lower = text.lower()
        score = 0.5  # Base score
        
        # Check for pattern-specific structural elements
        structure_checks = {
            'multiply_by': ['multiply', 'by', 'product'],
            'divide_by': ['divide', 'by'],
            'square_of': ['square'],
            'cube_of': ['cube'],
            'sqrt_of': ['square root', 'sqrt'],
            'cbrt_of': ['cube root'],
            'lcm_of': ['lcm', 'least common multiple'],
            'gcd_of': ['gcd', 'hcf', 'greatest common', 'highest common'],
            'percent_of': ['percent', '%', 'of'],
        }
        
        if pattern_name in structure_checks:
            keywords = structure_checks[pattern_name]
            matches = sum(1 for kw in keywords if kw in text_lower)
            score = 0.3 + (matches / len(keywords)) * 0.7
        
        return min(1.0, score)
    
    def is_word_problem(self, text: str) -> bool:
        """Quick check if text appears to be a word problem."""
        text_lower = text.lower()
        
        # Strong indicators
        strong_indicators = [
            'if', 'when', 'where', 'how many', 'how much',
            'person', 'people', 'student', 'teacher',
            'bought', 'sold', 'cost', 'price',
        ]
        
        indicator_count = sum(1 for ind in strong_indicators if ind in text_lower)
        
        # Multiple indicators = likely word problem
        if indicator_count >= 2:
            return True
        
        # Long text with questions
        if len(text.split()) > 15 and '?' in text:
            return True
        
        return False
