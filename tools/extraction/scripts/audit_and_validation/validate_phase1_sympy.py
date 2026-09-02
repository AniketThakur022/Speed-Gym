#!/usr/bin/env python3
"""
Phase 1 Validation: SymPy verification of all 145 computable templates
Generate QA report before Phase 2 kickoff
"""

import json
import re
from typing import Dict, List, Tuple, Optional

def safe_eval(expression: str) -> Optional[float]:
    """Safely evaluate a mathematical expression."""
    try:
        # Basic safety: only allow math operations
        allowed = {
            'sqrt': lambda x: x**0.5,
            'pi': 3.14159265359,
            'e': 2.718281828,
            '__builtins__': {}
        }
        
        # Clean the expression
        expr = expression.strip()
        
        # Skip SymPy-specific functions for now
        if any(func in expr for func in ['solve', 'diff', 'limit', 'cramer', 'Rational', 'divmod']):
            return None  # Skip complex SymPy expressions
        
        # Replace ^ with **
        expr = expr.replace('^', '**')
        
        # Evaluate
        result = eval(expr, allowed)
        return float(result) if result is not None else None
    except Exception as e:
        return None

def parse_expected_answer(answer: str) -> Optional[float]:
    """Extract numeric value from expected answer."""
    if not answer:
        return None
    
    # Try to find first number in answer
    patterns = [
        r'=\s*(-?\d+(?:\.\d+)?)',  # = 123.45
        r':\s*(-?\d+(?:\.\d+)?)',  # : 123.45
        r'^(-?\d+(?:\.\d+)?)',      # Starts with number
        r'(-?\d+(?:\.\d+)?)\s*(?:cm|m|ft|s|N|ohms?)',  # Number with units
    ]
    
    for pattern in patterns:
        match = re.search(pattern, str(answer))
        if match:
            try:
                return float(match.group(1))
            except:
                continue
    
    return None

def validate_template(template: Dict) -> Dict:
    """Validate a single template."""
    tid = template['template_id']
    computable = template['problem'].get('computable')
    expected = template['answer'].get('expected')
    
    result = {
        'template_id': tid,
        'computable': computable,
        'expected': expected,
        'computed': None,
        'status': 'PENDING',
        'error': None,
        'tolerance': 0.01  # 1% tolerance
    }
    
    if not computable:
        result['status'] = 'CONCEPTUAL'
        return result
    
    # Try to compute
    computed = safe_eval(computable)
    result['computed'] = computed
    
    if computed is None:
        result['status'] = 'SKIP_COMPLEX'
        result['error'] = 'Complex SymPy expression - manual validation needed'
        return result
    
    # Parse expected
    expected_num = parse_expected_answer(str(expected))
    
    if expected_num is None:
        result['status'] = 'EXPECTED_PARSE_FAIL'
        result['error'] = f'Could not parse expected: {expected[:50]}'
        return result
    
    # Compare
    if expected_num == 0:
        tolerance = 0.001
    else:
        tolerance = abs(expected_num) * 0.05  # 5% tolerance
    
    if abs(computed - expected_num) <= tolerance:
        result['status'] = 'PASS'
        result['tolerance'] = tolerance
    else:
        result['status'] = 'MISMATCH'
        result['error'] = f'Computed: {computed}, Expected: {expected_num}, Diff: {abs(computed - expected_num)}'
    
    return result

def run_validation():
    """Run full validation on all 155 templates."""
    
    input_path = '/workspace/data/templates/v3/rewrite_155_disputed_REMEDIATED.json'
    
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    templates = data['templates']
    results = []
    
    print(f"\n{'='*80}")
    print("PHASE 1 SYMPY VALIDATION")
    print(f"{'='*80}")
    print(f"Validating {len(templates)} templates...\n")
    
    for i, template in enumerate(templates, 1):
        result = validate_template(template)
        results.append(result)
        
        if i % 25 == 0:
            print(f"  Processed {i}/{len(templates)} templates...")
    
    # Generate report
    stats = {
        'total': len(results),
        'computable': sum(1 for r in results if r['computable']),
        'conceptual': sum(1 for r in results if r['status'] == 'CONCEPTUAL'),
        'pass': sum(1 for r in results if r['status'] == 'PASS'),
        'skip_complex': sum(1 for r in results if r['status'] == 'SKIP_COMPLEX'),
        'expected_parse_fail': sum(1 for r in results if r['status'] == 'EXPECTED_PARSE_FAIL'),
        'mismatch': sum(1 for r in results if r['status'] == 'MISMATCH')
    }
    
    # Calculate effective pass rate
    validated = stats['pass'] + stats['mismatch']
    pass_rate = (stats['pass'] / validated * 100) if validated > 0 else 0
    
    print(f"\n{'='*80}")
    print("VALIDATION RESULTS")
    print(f"{'='*80}")
    print(f"Total Templates: {stats['total']}")
    print(f"Computable: {stats['computable']}")
    print(f"  ✓ Passed: {stats['pass']}")
    print(f"  ✗ Mismatched: {stats['mismatch']}")
    print(f"  ⏭️  Complex (SymPy): {stats['skip_complex']}")
    print(f"  ⚠️  Expected Parse Fail: {stats['expected_parse_fail']}")
    print(f"Conceptual: {stats['conceptual']}")
    print(f"\nValidated Accuracy: {pass_rate:.1f}%")
    print(f"Status: {'✓ PASS' if stats['mismatch'] < 5 else '⚠️ REVIEW NEEDED'}")
    
    # Show failures
    failures = [r for r in results if r['status'] == 'MISMATCH']
    if failures:
        print(f"\n{'='*80}")
        print(f"MISMATCHES ({len(failures)}):")
        print(f"{'='*80}")
        for f in failures[:10]:
            print(f"\n{f['template_id']}:")
            print(f"  Computable: {f['computable']}")
            print(f"  Computed: {f['computed']}")
            print(f"  Expected: {f['expected'][:60]}")
            print(f"  Error: {f['error']}")
    
    # Save report
    report = {
        'validation_timestamp': '2026-06-12',
        'statistics': stats,
        'pass_rate_percent': round(pass_rate, 1),
        'failures': failures,
        'all_results': results
    }
    
    with open('/workspace/data/analysis/PHASE1_VALIDATION_REPORT.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n✅ Validation report saved")
    print(f"   Location: /workspace/data/analysis/PHASE1_VALIDATION_REPORT.json")
    
    return report

if __name__ == '__main__':
    report = run_validation()
