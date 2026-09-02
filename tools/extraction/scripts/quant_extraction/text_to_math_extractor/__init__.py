"""
Text-to-Math Extractor Module
=============================

Converts plain-text math problems into computable SymPy expressions.
Part of the math audit workflow for validating solve_along templates.

Modules:
    - extractor: Core TextToMathExtractor class
    - patterns: Pattern definitions for math operations
    - confidence: Confidence scoring system
    - compute: Verification via SymPy computation

Usage:
    from text_to_math_extractor import TextToMathExtractor
    
    extractor = TextToMathExtractor()
    result = extractor.process("Multiply 87265 by 32117")
"""

from .extractor import TextToMathExtractor, ExtractionResult
from .patterns import MathPatterns
from .confidence import ConfidenceScorer
from .compute_verifier import ComputeVerifier

__version__ = "1.0.0"
__all__ = [
    "TextToMathExtractor",
    "ExtractionResult",
    "MathPatterns",
    "ConfidenceScorer",
    "ComputeVerifier",
]
