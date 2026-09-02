"""
Math Pattern Definitions for Text-to-Math Extraction

Defines regex patterns for various mathematical operations in priority order.
Each pattern includes:
    - regex: The matching pattern
    - operation: Operation type identifier
    - priority: Priority for matching (lower = higher priority)
    - sympy_template: Template for generating SymPy expression
    - variations: List of natural language variations this pattern handles
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class PatternDefinition:
    """Definition of a text-to-math pattern."""
    name: str
    regex: re.Pattern
    operation: str
    priority: int
    sympy_template: str
    variations: List[str]
    description: str
    example: str


class MathPatterns:
    """
    Comprehensive regex patterns for extracting math operations from plain text.
    
    Priority Order (1 = highest):
    1. Basic arithmetic: Multiply, Divide, Add, Subtract
    2. Powers: Square, Cube, Square Root, Cube Root
    3. Special functions: LCM, GCD/HCF
    4. Percentages
    5. Evaluation expressions
    """
    
    # Number formats: integers, decimals, fractions
    NUMBER_INT = r'-?\d{1,9}(?:,\d{3})*'
    NUMBER_DEC = r'-?\d{1,9}(?:,\d{3})*\.\d+'
    NUMBER_FRAC = r'-?\d+\s*/\s*\d+'
    NUMBER_MIXED = r'-?\d+\s+\d+\s*/\s*\d+'
    
    # Combined number capture
    NUMBER = rf"(?:{NUMBER_DEC}|{NUMBER_FRAC}|{NUMBER_MIXED}|{NUMBER_INT})"
    
    # Number list for multi-operand operations
    NUMBER_LIST = rf"{NUMBER}(?:\s*,\s*{NUMBER})+"
    
    def __init__(self):
        self._compile_patterns()
        self._sort_patterns()
    
    def _compile_patterns(self):
        """Compile all regex patterns."""
        
        patterns_data = [
            # ───────────────────────────────────────────
            # PRIORITY 0: BARE MATH NOTATION (no keyword)
            # ───────────────────────────────────────────
            
            {
                "name": "bare_multiply_x",
                "regex": rf"^\s*({self.NUMBER})\s*[xX×]\s*({self.NUMBER})\s*$",
                "operation": "multiply",
                "priority": 0,
                "sympy_template": "({num1}) * ({num2})",
                "variations": ["A x B", "A × B", "A X B"],
                "description": "Bare multiplication with x/× operator, no keyword prefix",
                "example": "6 x 9",
            },
            {
                "name": "bare_multiply_dot",
                "regex": rf"^\s*({self.NUMBER})\s*[·.]\s*({self.NUMBER})\s*$",
                "operation": "multiply",
                "priority": 0,
                "sympy_template": "({num1}) * ({num2})",
                "variations": ["A · B"],
                "description": "Bare multiplication with dot operator",
                "example": "6 · 9",
            },
            
            # ───────────────────────────────────────────
            # PRIORITY 1: BASIC ARITHMETIC
            # ───────────────────────────────────────────
            
            # Multiplication patterns
            {
                "name": "multiply_by",
                "regex": rf"(?:multiply|product\s+of)\s+{self.NUMBER}\s+(?:by|and|×|x)\s+{self.NUMBER}",
                "operation": "multiply",
                "priority": 1,
                "sympy_template": "({num1}) * ({num2})",
                "variations": ["multiply A by B", "product of A and B"],
                "description": "Multiplication of two numbers with keyword",
                "example": "Multiply 87265 by 32117",
            },
            {
                "name": "times",
                "regex": rf"({self.NUMBER})\s+times\s+({self.NUMBER})",
                "operation": "multiply",
                "priority": 1,
                "sympy_template": "({num1}) * ({num2})",
                "variations": ["A times B"],
                "description": "Multiplication using 'times' keyword",
                "example": "87265 times 32117",
            },
            {
                "name": "multiply_list",
                "regex": rf"(?:multiply|product\s+of)\s+({self.NUMBER_LIST})",
                "operation": "multiply",
                "priority": 1,
                "sympy_template": " * ".join(["({})"] * 3),  # Template with placeholders
                "variations": ["multiply A, B, C", "product of A, B, and C"],
                "description": "Multiplication of multiple numbers",
                "example": "Multiply 2, 3, and 4",
            },
            
            # Division patterns
            {
                "name": "divide_by",
                "regex": rf"(?:divide|division)\s+({self.NUMBER})\s+(?:by|÷)\s+({self.NUMBER})",
                "operation": "divide",
                "priority": 1,
                "sympy_template": "({num1}) / ({num2})",
                "variations": ["divide X by Y", "division of X by Y"],
                "description": "Division of two numbers",
                "example": "Divide 100 by 5",
            },
            {
                "name": "divided_by",
                "regex": rf"({self.NUMBER})\s+(?:divided)\s+by\s+({self.NUMBER})",
                "operation": "divide",
                "priority": 1,
                "sympy_template": "({num1}) / ({num2})",
                "variations": ["X divided by Y"],
                "description": "Infix division of two numbers",
                "example": "100 divided by 5",
            },
            
            # Addition patterns
            {
                "name": "add_two",
                "regex": rf"(?:add|sum\s+of)\s+({self.NUMBER})\s+(?:and|,)\s+({self.NUMBER})",
                "operation": "add",
                "priority": 1,
                "sympy_template": "({num1}) + ({num2})",
                "variations": ["add A and B", "sum of A and B", "A plus B"],
                "description": "Addition of two numbers",
                "example": "Add 5 and 3",
            },
            {
                "name": "add_list",
                "regex": rf"(?:add|sum\s+of)\s+({self.NUMBER_LIST})",
                "operation": "add",
                "priority": 1,
                "sympy_template": " + ".join(["({})"] * 3),
                "variations": ["add A, B, C", "sum of A, B, and C"],
                "description": "Addition of multiple numbers",
                "example": "Add 2, 3, and 4",
            },
            
            # Subtraction patterns
            {
                "name": "subtract_from",
                "regex": rf"(?:subtract)\s+({self.NUMBER})\s+(?:from)\s+({self.NUMBER})",
                "operation": "subtract",
                "priority": 1,
                "sympy_template": "({num2}) - ({num1})",
                "variations": ["subtract A from B", "B minus A"],
                "description": "Subtraction (order matters)",
                "example": "Subtract 5 from 10",
            },
            {
                "name": "minus",
                "regex": rf"({self.NUMBER})\s+(?:minus|less)\s+({self.NUMBER})",
                "operation": "subtract",
                "priority": 1,
                "sympy_template": "({num1}) - ({num2})",
                "variations": ["A minus B", "A less B"],
                "description": "Subtraction using minus",
                "example": "10 minus 5",
            },
            
            # ───────────────────────────────────────────
            # PRIORITY 2: POWERS AND ROOTS
            # ───────────────────────────────────────────
            
            # Square patterns
            {
                "name": "square_of",
                "regex": rf"(?:square\s+of)\s+({self.NUMBER})|({self.NUMBER})\s+(?:squared|²)",
                "operation": "power",
                "priority": 2,
                "sympy_template": "({num}) ** 2",
                "variations": ["square of N", "N squared", "N²"],
                "description": "Square of a number",
                "example": "Square of 5",
            },
            
            # Cube patterns
            {
                "name": "cube_of",
                "regex": rf"(?:cube\s+of)\s+({self.NUMBER})|({self.NUMBER})\s+(?:cubed|³)",
                "operation": "power",
                "priority": 2,
                "sympy_template": "({num}) ** 3",
                "variations": ["cube of N", "N cubed", "N³"],
                "description": "Cube of a number",
                "example": "Cube of 3",
            },
            
            # Square root patterns
            {
                "name": "sqrt_of",
                "regex": rf"(?:square\s+root\s+of)\s+({self.NUMBER})|√({self.NUMBER})",
                "operation": "sqrt",
                "priority": 2,
                "sympy_template": "sqrt({num})",
                "variations": ["square root of N", "√N"],
                "description": "Square root of a number",
                "example": "Square root of 16",
            },
            
            # Cube root patterns
            {
                "name": "cbrt_of",
                "regex": rf"(?:cube\s+root\s+of)\s+({self.NUMBER})",
                "operation": "cbrt",
                "priority": 2,
                "sympy_template": "({num}) ** (sp.Rational(1, 3))",
                "variations": ["cube root of N", "∛N"],
                "description": "Cube root of a number",
                "example": "Cube root of 27",
            },
            
            # General power
            {
                "name": "power_of",
                "regex": rf"({self.NUMBER})\s*\^\s*(\d+)",
                "operation": "power",
                "priority": 2,
                "sympy_template": "({num}) ** {exp}",
                "variations": ["N^X"],
                "description": "Number raised to a power",
                "example": "2^10",
            },
            
            # ───────────────────────────────────────────
            # PRIORITY 3: SPECIAL FUNCTIONS
            # ───────────────────────────────────────────
            
            # LCM patterns
            {
                "name": "lcm_of",
                "regex": rf"(?:lcm|least\s+common\s+multiple)\s+of\s+({self.NUMBER_LIST})",
                "operation": "lcm",
                "priority": 3,
                "sympy_template": "lcm({nums})",
                "variations": ["LCM of A, B", "least common multiple of A, B, C"],
                "description": "Least common multiple",
                "example": "LCM of 150, 210",
            },
            
            # GCD/HCF patterns
            {
                "name": "gcd_of",
                "regex": rf"(?:gcd|hcf|greatest\s+common\s+divisor|highest\s+common\s+factor)\s+of\s+({self.NUMBER_LIST})",
                "operation": "gcd",
                "priority": 3,
                "sympy_template": "gcd({nums})",
                "variations": ["GCD of A, B", "HCF of A, B", "greatest common divisor"],
                "description": "Greatest common divisor / Highest common factor",
                "example": "GCD of 48, 18",
            },
            
            # ───────────────────────────────────────────
            # PRIORITY 4: PERCENTAGES AND FRACTIONS
            # ───────────────────────────────────────────
            
            # Percentage patterns
            {
                "name": "percent_of",
                "regex": rf"({self.NUMBER})\s*(?:%|percent)\s+(?:of)\s+({self.NUMBER})",
                "operation": "percent",
                "priority": 4,
                "sympy_template": "({num1}) * ({num2}) / 100",
                "variations": ["A% of B", "A percent of B"],
                "description": "Percentage calculation",
                "example": "20% of 150",
            },
            
            # Simplify fraction
            {
                "name": "simplify_fraction",
                "regex": rf"(?:simplify)\s+({self.NUMBER_FRAC})",
                "operation": "simplify",
                "priority": 4,
                "sympy_template": "sp.Rational({num}, {den})",
                "variations": ["simplify A/B"],
                "description": "Simplify a fraction",
                "example": "Simplify 6/8",
            },
            
            # ───────────────────────────────────────────
            # PRIORITY 5: EVALUATION EXPRESSIONS
            # ───────────────────────────────────────────
            
            # Evaluate expression with superscript
            {
                "name": "evaluate_power",
                "regex": rf"(?:evaluate|find\s+value\s+of)\s+({self.NUMBER})\s*[²³]",
                "operation": "power",
                "priority": 5,
                "sympy_template": "({num}) ** {exp}",
                "variations": ["evaluate N²", "evaluate N³"],
                "description": "Evaluate number with power",
                "example": "Evaluate 5²",
            },
            
            # Evaluate square root
            {
                "name": "evaluate_sqrt",
                "regex": rf"(?:evaluate|find\s+value\s+of)\s+[√]?({self.NUMBER})",
                "operation": "sqrt",
                "priority": 5,
                "sympy_template": "sqrt({num})",
                "variations": ["evaluate √N"],
                "description": "Evaluate square root",
                "example": "Evaluate √25",
            },
        ]
        
        self.patterns: List[PatternDefinition] = []
        for p in patterns_data:
            try:
                compiled = re.compile(p["regex"], re.IGNORECASE | re.VERBOSE)
                self.patterns.append(PatternDefinition(
                    name=p["name"],
                    regex=compiled,
                    operation=p["operation"],
                    priority=p["priority"],
                    sympy_template=p["sympy_template"],
                    variations=p["variations"],
                    description=p["description"],
                    example=p["example"],
                ))
            except re.error as e:
                print(f"Warning: Failed to compile pattern {p['name']}: {e}")
    
    def _sort_patterns(self):
        """Sort patterns by priority (lower = higher priority)."""
        self.patterns.sort(key=lambda p: p.priority)
    
    def get_patterns_by_priority(self, max_priority: int) -> List[PatternDefinition]:
        """Get patterns up to a certain priority level."""
        return [p for p in self.patterns if p.priority <= max_priority]
    
    def find_matching_pattern(self, text: str) -> Optional[PatternDefinition]:
        """Find the first matching pattern for given text."""
        for pattern in self.patterns:
            if pattern.regex.search(text):
                return pattern
        return None
    
    def extract_numbers(self, text: str) -> List[str]:
        """Extract all numbers from text."""
        number_pattern = re.compile(self.NUMBER)
        numbers = number_pattern.findall(text)
        # Clean numbers (remove commas)
        return [n.replace(',', '') for n in numbers]
    
    def clean_number(self, num_str: str) -> str:
        """Clean a number string for SymPy parsing."""
        # Remove commas from thousands separators
        cleaned = num_str.replace(',', '')
        # Handle fractions
        if '/' in cleaned:
            parts = cleaned.split('/')
            if len(parts) == 2:
                return f"sp.Rational({parts[0].strip()}, {parts[1].strip()})"
        return cleaned


# Pre-instantiated singleton for convenience
DEFAULT_PATTERNS = MathPatterns()
