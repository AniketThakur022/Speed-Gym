"""
Compute Verification Module

Converts extracted text-to-math expressions to SymPy,
computes the result, and compares with expected answers.
"""

import math
import re
import sympy as sp
from sympy import sqrt, lcm, gcd, Rational
from typing import Optional, Tuple, Union, Dict, Any


class ComputeVerifier:
    """
    Verifies extracted math expressions by computing with SymPy.
    
    Supports:
    - Basic arithmetic: +, -, *, /
    - Powers: ** operator
    - Special functions: sqrt, lcm, gcd
    - Fractions: Rational
    """
    
    def __init__(self):
        self._setup_sympy_namespace()
    
    def _setup_sympy_namespace(self):
        """Setup namespace for SymPy evaluation."""
        self.safe_namespace = {
            'sp': sp,
            'sqrt': sqrt,
            'lcm': lcm,
            'gcd': gcd,
            'Rational': Rational,
            'abs': abs,
            'max': max,
            'min': min,
            'pow': pow,
        }
    
    def build_expression(
        self,
        operation: str,
        numbers: list,
        sympy_template: str,
        pattern_name: Optional[str] = None
    ) -> Tuple[Optional[sp.Expr], str]:
        """
        Build SymPy expression from extracted components.
        
        Args:
            operation: Operation type
            numbers: List of extracted numbers as strings
            sympy_template: Template for generating expression
            
        Returns:
            (sympy_expression, status)
            status: "ok" | "parse_error" | "invalid_operands"
        """
        if not numbers:
            return None, "invalid_operands"
        
        try:
            # Clean numbers
            cleaned_numbers = [self._clean_number(n) for n in numbers]
            
            # Build expression based on operation type
            if operation == "multiply":
                if len(cleaned_numbers) == 2:
                    expr = f"({cleaned_numbers[0]}) * ({cleaned_numbers[1]})"
                else:
                    expr = " * ".join(f"({n})" for n in cleaned_numbers)
            
            elif operation == "divide":
                if len(cleaned_numbers) >= 2:
                    expr = f"({cleaned_numbers[0]}) / ({cleaned_numbers[1]})"
                else:
                    return None, "invalid_operands"
            
            elif operation == "add":
                expr = " + ".join(f"({n})" for n in cleaned_numbers)
            
            elif operation == "subtract":
                if len(cleaned_numbers) >= 2:
                    if pattern_name and "from" in pattern_name.lower():
                        # "Subtract A from B" means B - A
                        expr = f"({cleaned_numbers[1]}) - ({cleaned_numbers[0]})"
                    else:
                        # "A minus B" means A - B
                        expr = f"({cleaned_numbers[0]}) - ({cleaned_numbers[1]})"
                else:
                    return None, "invalid_operands"
            
            elif operation == "power":
                if len(cleaned_numbers) >= 2:
                    # power_of pattern: "2^10" — first number is base, second is exponent
                    expr = f"({cleaned_numbers[0]}) ** ({cleaned_numbers[1]})"
                elif len(cleaned_numbers) == 1:
                    base = cleaned_numbers[0]
                    if "** 3" in sympy_template:
                        expr = f"({base}) ** 3"
                    elif "** 2" in sympy_template:
                        expr = f"({base}) ** 2"
                    else:
                        expr = f"({base}) ** 2"  # Default to square
                else:
                    return None, "invalid_operands"
            
            elif operation == "sqrt":
                if len(cleaned_numbers) >= 1:
                    expr = f"sqrt({cleaned_numbers[0]})"
                else:
                    return None, "invalid_operands"
            
            elif operation == "cbrt":
                if len(cleaned_numbers) >= 1:
                    expr = f"({cleaned_numbers[0]}) ** (sp.Rational(1, 3))"
                else:
                    return None, "invalid_operands"
            
            elif operation == "lcm":
                if len(cleaned_numbers) >= 2:
                    expr = f"lcm({cleaned_numbers[0]}, {cleaned_numbers[1]})"
                    for n in cleaned_numbers[2:]:
                        expr = f"lcm({expr}, {n})"
                else:
                    return None, "invalid_operands"
            
            elif operation == "gcd":
                if len(cleaned_numbers) >= 2:
                    expr = f"gcd({cleaned_numbers[0]}, {cleaned_numbers[1]})"
                    for n in cleaned_numbers[2:]:
                        expr = f"gcd({expr}, {n})"
                else:
                    return None, "invalid_operands"
            
            elif operation == "percent":
                if len(cleaned_numbers) >= 2:
                    expr = f"({cleaned_numbers[0]}) * ({cleaned_numbers[1]}) / 100"
                else:
                    return None, "invalid_operands"
            
            elif operation == "simplify":
                # Fraction simplification
                # _clean_number already converts fraction strings to sp.Rational(...)
                if len(cleaned_numbers) == 1 and cleaned_numbers[0].startswith("sp.Rational("):
                    expr = cleaned_numbers[0]
                elif len(cleaned_numbers) >= 2:
                    expr = f"sp.Rational({cleaned_numbers[0]}, {cleaned_numbers[1]})"
                else:
                    return None, "invalid_operands"
            
            else:
                # Try to use sympy_template directly
                try:
                    expr = sympy_template.format(*cleaned_numbers)
                except:
                    return None, "template_error"
            
            # Parse to SymPy
            sympy_expr = sp.sympify(expr, locals=self.safe_namespace)
            return sympy_expr, "ok"
            
        except Exception as e:
            return None, f"parse_error: {str(e)}"
    
    def _clean_number(self, num_str: str) -> str:
        """Clean number string for SymPy."""
        # Remove commas
        cleaned = num_str.replace(',', '')
        
        # Check if it's a fraction
        if '/' in cleaned:
            parts = cleaned.split('/')
            if len(parts) == 2:
                return f"sp.Rational({parts[0].strip()}, {parts[1].strip()})"
        
        return cleaned
    
    def compute(self, expr: sp.Expr) -> Tuple[Optional[Union[int, float, sp.Expr]], str]:
        """
        Compute SymPy expression to a value.
        
        Returns:
            (computed_value, status)
            status: "ok" | "symbolic" | "computation_error"
        """
        try:
            if expr.free_symbols:
                # Has variables - try to evaluate
                val = expr.evalf()
                if val.is_number:
                    return val, "ok"
                return expr, "symbolic"
            else:
                # Pure numeric
                val = expr.evalf()
                if val.is_number:
                    return val, "ok"
                return expr, "symbolic"
        except Exception as e:
            return None, f"computation_error: {str(e)}"
    
    def compare_with_expected(
        self,
        computed: Union[int, float, sp.Expr],
        expected_str: str
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Compare computed value with expected answer string.
        
        Args:
            computed: Computed SymPy value
            expected_str: Expected answer as string (from template)
            
        Returns:
            (is_match, match_type, details)
        """
        details = {
            "computed": str(computed),
            "expected_raw": expected_str,
        }
        
        if computed is None or not expected_str:
            return False, "missing_value", details
        
        try:
            # Extract expected value
            expected_val = self._extract_expected_value(expected_str)
            details["expected_parsed"] = str(expected_val) if expected_val else None
            
            if expected_val is None:
                return False, "expected_parse_failed", details
            
            # Exact comparison
            try:
                diff = sp.simplify(computed - expected_val)
                if diff == 0:
                    return True, "exact_symbolic", details
            except:
                pass
            
            # Numeric comparison
            try:
                # Integer comparison via SymPy (no float precision loss)
                comp_int = sp.Integer(computed)
                exp_int = sp.Integer(expected_val)
                match = comp_int == exp_int
                return match, "exact_integer" if match else "mismatch_integer", details
            except (TypeError, ValueError):
                pass
            
            # Float comparison with tolerance
            try:
                comp_num = float(computed.evalf())
                exp_num = float(expected_val.evalf())
                is_close = math.isclose(comp_num, exp_num, rel_tol=1e-9, abs_tol=1e-12)
                match_type = "approximate_float" if is_close else "mismatch_float"
                return is_close, match_type, details
                
            except Exception as e:
                details["numeric_compare_error"] = str(e)
                return False, "comparison_failed", details
                
        except Exception as e:
            details["compare_error"] = str(e)
            return False, "comparison_error", details
    
    def _extract_expected_value(self, expected_str: str) -> Optional[sp.Expr]:
        """Extract numeric value from expected answer string."""
        if not expected_str:
            return None
        
        # Try different extraction strategies
        
        # 0. Remove commas (thousands separators) FIRST
        cleaned = expected_str.replace(',', '')
        
        # 1. Direct sympify with commas removed
        try:
            return sp.sympify(cleaned, locals=self.safe_namespace)
        except:
            pass
        
        # 2. Extract after = sign
        if '=' in cleaned:
            answer_part = cleaned.split('=')[-1].strip()
            try:
                return sp.sympify(answer_part, locals=self.safe_namespace)
            except:
                pass
        
        # 3. Remove other decorations and try
        for char in ['$', '%', 'Answer:', 'Ans:', 'ans']:
            cleaned = cleaned.replace(char, '')
        cleaned = cleaned.strip()
        
        try:
            return sp.sympify(cleaned, locals=self.safe_namespace)
        except:
            pass
        
        # 4. Extract last number (from comma-free version)
        nums = re.findall(r'-?\d+\.?\d*', cleaned)
        if nums:
            try:
                return sp.sympify(nums[-1], locals=self.safe_namespace)
            except:
                pass
        
        return None
    
    def verify_extraction(
        self,
        operation: str,
        numbers: list,
        sympy_template: str,
        expected_answer: str,
        pattern_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Full verification pipeline for an extraction.
        
        Args:
            operation: Operation type
            numbers: Extracted numbers
            sympy_template: Template for expression
            expected_answer: Expected answer from template
            
        Returns:
            Dictionary with full verification results
        """
        result = {
            "operation": operation,
            "extracted_numbers": numbers,
            "expected_answer": expected_answer,
            "status": "pending",
        }
        
        # Build expression
        expr, build_status = self.build_expression(operation, numbers, sympy_template, pattern_name=pattern_name)
        result["expression_build"] = {
            "success": expr is not None,
            "status": build_status,
            "expression": str(expr) if expr else None,
        }
        
        if expr is None:
            result["status"] = "build_failed"
            return result
        
        # Compute
        computed, compute_status = self.compute(expr)
        result["computation"] = {
            "success": computed is not None,
            "status": compute_status,
            "computed_value": str(computed) if computed else None,
        }
        
        if computed is None:
            result["status"] = "compute_failed"
            return result
        
        # Compare
        is_match, match_type, compare_details = self.compare_with_expected(
            computed, expected_answer
        )
        
        result["comparison"] = {
            "is_match": is_match,
            "match_type": match_type,
            "details": compare_details,
        }
        
        if is_match:
            result["status"] = "match"
        else:
            result["status"] = "mismatch"
        
        return result
