# Text-to-Math Extractor - Implementation Specification

## Overview

This module provides a robust text-to-math extraction system for the math audit workflow, converting plain-text math problems into computable SymPy expressions.

## Project Structure

```
/workspace/assembly_line/text_to_math_extractor/
├── __init__.py           # Module initialization
├── patterns.py           # Regex pattern definitions
├── confidence.py         # Confidence scoring system
├── compute_verifier.py   # SymPy computation verification
├── extractor.py          # Core TextToMathExtractor class
├── batch_processor.py    # Batch processing with checkpointing
├── integration.py        # Hybrid Validator v3 integration
├── cli.py               # Command-line interface
├── examples.py          # Usage examples
└── IMPLEMENTATION_SPEC.md # This file
```

## File Paths

### Module Location
- **Root Module**: `/workspace/assembly_line/text_to_math_extractor/`

### Output Directories
- **Checkpoints**: `/workspace/data/checkpoints/`
- **Math Audit Results**: `/workspace/data/audit_results/math_audit/`
- **LLM Audit Results**: `/workspace/data/audit_results/llm_audit/`

## Core Classes

### 1. TextToMathExtractor

**File**: `extractor.py`

**Purpose**: Main entry point for extracting math from text.

**Key Methods**:
```python
def process(self, text: str, expected_answer: Optional[str] = None, 
            template_id: Optional[str] = None) -> ExtractionResult
```

**Usage**:
```python
from text_to_math_extractor import TextToMathExtractor

extractor = TextToMathExtractor()
result = extractor.process("Multiply 87265 by 32117")
print(result.pattern_matched)  # "multiply_by"
print(result.extracted_numbers)  # ["87265", "32117"]
print(result.confidence.level)  # ConfidenceLevel.HIGH
```

### 2. MathPatterns

**File**: `patterns.py`

**Purpose**: Defines all regex patterns for text-to-math extraction.

**Pattern Priority**:
1. **Priority 1**: Basic arithmetic (multiply, divide, add, subtract)
2. **Priority 2**: Powers and roots (square, cube, sqrt, cbrt)
3. **Priority 3**: Special functions (LCM, GCD/HCF)
4. **Priority 4**: Percentages and fractions
5. **Priority 5**: Evaluation expressions

**Supported Patterns**:

| Pattern | Regex | SymPy Template | Example |
|---------|-------|----------------|---------|
| multiply_by | `multiply\s+\d+\s+by\s+\d+` | `({num1}) * ({num2})` | "Multiply 5 by 3" |
| divide_by | `divide\s+\d+\s+by\s+\d+` | `({num1}) / ({num2})` | "Divide 100 by 4" |
| add_two | `add\s+\d+\s+and\s+\d+` | `({num1}) + ({num2})` | "Add 5 and 3" |
| square_of | `square\s+of\s+\d+` | `({num}) ** 2` | "Square of 25" |
| cube_of | `cube\s+of\s+\d+` | `({num}) ** 3` | "Cube of 3" |
| sqrt_of | `square\s+root\s+of\s+\d+` | `sqrt({num})` | "Square root of 16" |
| cbrt_of | `cube\s+root\s+of\s+\d+` | `({num}) ** (1/3)` | "Cube root of 27" |
| lcm_of | `lcm\s+of\s+\d+,\s*\d+` | `lcm({nums})` | "LCM of 12, 18" |
| gcd_of | `gcd\s+of\s+\d+,\s*\d+` | `gcd({nums})` | "GCD of 48, 18" |
| percent_of | `\d+%\s+of\s+\d+` | `({num1}) * ({num2}) / 100` | "20% of 150" |

### 3. ConfidenceScorer

**File**: `confidence.py`

**Purpose**: Scores extraction confidence based on multiple factors.

**Scoring Weights**:
- Pattern specificity: 30%
- Number extraction: 30%
- Text clarity: 25%
- Structure match: 15%

**Confidence Levels**:
- **HIGH (≥0.85)**: Clear pattern with extractable numbers
- **MEDIUM (0.60-0.85)**: Pattern matched with minor ambiguities
- **LOW (0.40-0.60)**: Ambiguous extraction - verify before using
- **REJECT (<0.40)**: Cannot extract - needs LLM

**Rejection Criteria**:
- No pattern matched
- No numbers found
- Contains word problem indicators ("if", "person", "bought", "train", etc.)
- Text length > 20 words
- Multiple ambiguous indicators

### 4. ComputeVerifier

**File**: `compute_verifier.py`

**Purpose**: Verifies extraction by computing with SymPy and comparing results.

**Verification Flow**:
1. Build SymPy expression from extracted components
2. Compute the result
3. Extract expected value from template's final_answer
4. Compare computed vs expected

**Comparison Methods**:
- Exact symbolic comparison (`simplify(computed - expected) == 0`)
- Integer exact match
- Float comparison with tolerance (1e-9 relative, 1e-12 absolute)

### 5. BatchProcessor

**File**: `batch_processor.py`

**Purpose**: Processes solve_along templates in batches with checkpointing.

**Features**:
- Automatic checkpointing every N items (configurable)
- Resumable processing
- Output categorization (math_audit vs llm_audit)
- Statistics tracking

**Usage**:
```python
processor = BatchProcessor(
    checkpoint_dir="/workspace/data/checkpoints",
    output_dir="/workspace/data/audit_results",
    batch_size=50
)

summary = processor.process_templates(
    templates=template_list,
    batch_id="solve_along_batch_001"
)
```

## Integration with Existing System

### HybridValidatorBridge

**File**: `integration.py`

**Purpose**: Bridge between TextToMathExtractor and Hybrid Validator v3.

**Strategy**:
1. Check for LaTeX in problem text
2. If LaTeX present → use existing `compute_engine.py`
3. If no LaTeX → use TextToMathExtractor
4. Return unified result format

**Usage**:
```python
from text_to_math_extractor.integration import HybridValidatorBridge

bridge = HybridValidatorBridge()
result = bridge.process_problem(
    problem_text="Multiply 87265 by 32117",
    final_answer="2,800,797,005",
    template_id="template_001"
)

# Result includes:
# - method: "latex" or "text_extraction"
# - status: verification status
# - match: True/False
# - computed: computed value
```

## CLI Usage

### Commands

```bash
# Test single extraction
python cli.py test "Multiply 5 by 3" --expected "15"

# Process template file
python cli.py process-file templates.json --batch-id batch_001

# View batch statistics
python cli.py stats --batch-id batch_001

# Export LLM audit items
python cli.py export-llm --batch-id batch_001 --output llm_input.jsonl

# Run demo
python cli.py demo
```

## Expected Coverage

Based on the analysis:

| Category | Count | Coverage by Text-to-Math |
|----------|-------|--------------------------|
| Total solve_along templates | 807 | - |
| Total examples | 1,992 | - |
| LaTeX (computable) | 140 | Handled by existing compute_engine |
| Plain-text extractable | 280-320 | **This module** |
| Requires LLM | 420-470 | Rejected, sent to LLM audit |

**Expected Extraction Rate**: 35-40% of non-LaTeX plain-text problems

## Regex Patterns Detail

### Number Formats

```python
NUMBER_INT = r'-?\d{1,9}(?:,\d{3})*'      # Integers with commas
NUMBER_DEC = r'-?\d{1,9}(?:,\d{3})*\.\d+'  # Decimals
NUMBER_FRAC = r'-?\d+\s*/\s*\d+'          # Fractions
NUMBER = rf"(?:{NUMBER_DEC}|{NUMBER_FRAC}|{NUMBER_INT})"
```

### Multiplication Patterns

```python
# Primary pattern
multiply_by: "multiply\s+\d+\s+by\s+\d+"

# Variations handled:
# - "Multiply A by B"
# - "Product of A and B"
# - "A × B" (unicode)
# - "A x B" (ASCII)
# - "A times B"
```

### Division Patterns

```python
# Primary pattern
divide_by: "divide\s+\d+\s+by\s+\d+"

# Variations handled:
# - "Divide X by Y"
# - "X divided by Y"
# - "Division of X by Y"
# - "X ÷ Y" (unicode)
```

### Power Patterns

```python
# Square
square_of: "square\s+of\s+\d+|\d+\s+squared"

# Cube
cube_of: "cube\s+of\s+\d+|\d+\s+cubed"

# General power
power_of: "\d+\s*\^\s*\d+"
```

### Special Functions

```python
# LCM
lcm_of: "lcm\s+of\s+\d+[,\s]+\d+"

# GCD/HCF
gcd_of: "gcd|hcf|greatest\s+common\s+divisor"

# Square root
sqrt_of: "square\s+root\s+of\s+\d+|√\d+"

# Cube root
cbrt_of: "cube\s+root\s+of\s+\d+"
```

## Confidence Scoring

### Pattern Specificity Scores

| Pattern Category | Score | Examples |
|------------------|-------|----------|
| High specificity | 1.0 | multiply_by, divide_by, sqrt_of, lcm_of, gcd_of |
| Medium specificity | 0.7 | add_list, multiply_list, power_of |
| Low specificity | 0.5 | All other patterns |

### Ambiguous Words

Words that reduce confidence:
- "if", "when", "where", "how", "who"
- Person names: "john", "mary", "alice"
- Objects: "apple", "train", "car"
- Verbs: "prove", "explain", "describe"
- Commerce: "price", "cost", "buy", "sell"
- Time: "ago", "later", "hour", "day"

### Strong Math Indicators

Words that increase confidence:
- "multiply", "product", "divide", "sum"
- "square", "cube", "root"
- "lcm", "gcd", "hcf", "percent"
- "evaluate", "calculate", "simplify"

## Output Format

### ExtractionResult JSON

```json
{
  "original_text": "Multiply 87265 by 32117",
  "cleaned_text": "Multiply 87265 by 32117",
  "pattern_matched": "multiply_by",
  "operation": "multiply",
  "extracted_numbers": ["87265", "32117"],
  "sympy_expression": "(87265) * (32117)",
  "computed_value": "2800797005",
  "expected_answer": "2800797005",
  "verification_status": "match",
  "confidence": {
    "level": "high",
    "score": 0.95,
    "reason": "Clear pattern match with extractable numbers"
  },
  "extraction_time": "2024-01-15T10:30:00",
  "metadata": {}
}
```

## Testing

### Run Examples

```bash
cd /workspace/assembly_line/text_to_math_extractor
python examples.py
```

### Run Demo

```bash
python cli.py demo
```

### Test Single Extraction

```bash
python cli.py test "Multiply 5 by 3" --expected "15"
```

## Performance Considerations

1. **Regex Compilation**: Patterns are compiled once at initialization
2. **Checkpointing**: Saves progress every N items (default: 50)
3. **Batch Processing**: Supports large batches with resume capability
4. **Memory**: Results streamed to disk, not kept in memory

## Error Handling

| Error | Handling |
|-------|----------|
| Pattern mismatch | Return REJECT confidence |
| Number extraction failure | Return REJECT confidence |
| SymPy parse error | Return verification_error status |
| Computation error | Return compute_failed status |
| Comparison error | Return comparison_failed status |

## Future Enhancements

1. **Additional Patterns**:
   - Fraction operations
   - Mixed number operations
   - Decimal operations
   - Scientific notation

2. **LLM Fallback**:
   - Integration with LLM for rejected problems
   - Confidence-based routing

3. **Optimization**:
   - Parallel processing for large batches
   - Caching of computed results
   - Pattern learning from successful extractions

## Dependencies

- `sympy`: SymPy symbolic math library
- `re`: Python regex module
- `json`: JSON serialization
- `pathlib`: Path manipulation

## Integration Points

1. **Hybrid Validator v3**: `integration.py` provides bridge
2. **Compute Engine**: Existing `compute_engine.py` for LaTeX
3. **Batch Processor**: `batch_processor.py` for workflow integration
4. **Audit Pipeline**: CLI for pipeline integration
