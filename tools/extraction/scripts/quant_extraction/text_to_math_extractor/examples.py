#!/usr/bin/env python3
"""
Usage Examples for Text-to-Math Extractor

Demonstrates all major features and integration patterns.
"""

import json
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from text_to_math_extractor import TextToMathExtractor
from text_to_math_extractor.confidence import ConfidenceLevel


def example_basic_extraction():
    """Example 1: Basic extraction of simple problems."""
    print("=" * 70)
    print("EXAMPLE 1: Basic Extraction")
    print("=" * 70)
    
    extractor = TextToMathExtractor()
    
    test_cases = [
        ("Multiply 87265 by 32117", "2,800,797,005"),
        ("Divide 1000 by 25", "40"),
        ("Add 5, 10, and 15", "30"),
        ("Square of 25", "625"),
        ("Cube root of 27", "3"),
        ("LCM of 12, 18", "36"),
        ("GCD of 48, 18", "6"),
        ("20 percent of 150", "30"),
        ("Square root of 144", "12"),
        ("Evaluate 5²", "25"),
    ]
    
    for text, expected in test_cases:
        result = extractor.process(text, expected_answer=expected)
        
        status_icon = "✓" if result.verification_status == "match" else "✗" if result.verification_status == "mismatch" else "?"
        
        print(f"\n{status_icon} {text}")
        print(f"   Pattern: {result.pattern_matched}")
        print(f"   Numbers: {result.extracted_numbers}")
        print(f"   Expression: {result.sympy_expression}")
        print(f"   Computed: {result.computed_value}")
        print(f"   Expected: {result.expected_answer}")
        if result.confidence:
            print(f"   Confidence: {result.confidence.level.value} ({result.confidence.score:.2f})")


def example_word_problems_rejection():
    """Example 2: Word problems that should be rejected."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 2: Word Problems (Should be Rejected)")
    print("=" * 70)
    
    extractor = TextToMathExtractor()
    
    word_problems = [
        "If a train travels at 60 mph for 2 hours, how far does it go?",
        "John has 5 apples and gives 2 to Mary. How many does he have left?",
        "The ratio of boys to girls in a class is 3:2. If there are 30 students...",
        "Prove that the sum of angles in a triangle is 180 degrees.",
        "What is the value of x if 2x + 5 = 15?",
    ]
    
    for text in word_problems:
        result = extractor.process(text)
        
        status = "✓ REJECTED" if result.confidence and result.confidence.level == ConfidenceLevel.REJECT else "✗ NOT REJECTED"
        
        print(f"\n{status}: {text[:50]}...")
        if result.confidence:
            print(f"   Confidence: {result.confidence.level.value}")
            print(f"   Reason: {result.confidence.reason}")


def example_confidence_levels():
    """Example 3: Demonstrating confidence scoring."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 3: Confidence Levels")
    print("=" * 70)
    
    extractor = TextToMathExtractor()
    
    # High confidence examples
    high_confidence_cases = [
        "Multiply 5 by 3",
        "LCM of 10, 15",
        "Square root of 100",
    ]
    
    print("\nHigh Confidence Cases:")
    for text in high_confidence_cases:
        result = extractor.process(text)
        print(f"  {text:30} -> {result.confidence.level.value if result.confidence else 'N/A'}")
    
    # Low confidence cases (ambiguous)
    low_confidence_cases = [
        "Find the answer when you multiply these numbers",
        "What is the result of dividing something by something else?",
    ]
    
    print("\nLow Confidence Cases:")
    for text in low_confidence_cases:
        result = extractor.process(text)
        print(f"  {text[:40]:40} -> {result.confidence.level.value if result.confidence else 'N/A'}")


def example_batch_processing():
    """Example 4: Batch processing with statistics."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 4: Batch Processing")
    print("=" * 70)
    
    extractor = TextToMathExtractor()
    
    # Create batch of problems
    batch = [
        ("Multiply 10 by 20", "200"),
        ("Divide 100 by 4", "25"),
        ("Add 5, 10, 15", "30"),
        ("Square of 12", "144"),
        ("LCM of 6, 8", "24"),
        ("GCD of 100, 25", "25"),
        ("This is a word problem about trains", ""),  # Should be rejected
        ("25 percent of 80", "20"),
        ("Cube of 3", "27"),
        ("Square root of 81", "9"),
    ]
    
    print(f"\nProcessing {len(batch)} problems...")
    
    results = []
    for text, expected in batch:
        result = extractor.process(text, expected_answer=expected)
        results.append(result)
    
    # Show statistics
    stats = extractor.get_stats()
    
    print("\nBatch Statistics:")
    print(f"  Total Processed: {stats['total_processed']}")
    print(f"  High Confidence: {stats['high_confidence']}")
    print(f"  Medium Confidence: {stats['medium_confidence']}")
    print(f"  Low Confidence: {stats['low_confidence']}")
    print(f"  Rejected: {stats['rejected']}")
    print(f"  Success Rate: {stats['success_rate']:.1%}")
    print(f"  Verified Match: {stats['verified_match']}")
    print(f"  Verified Mismatch: {stats['verified_mismatch']}")


def example_integration():
    """Example 5: Integration with existing compute engine."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 5: Hybrid Validator Integration")
    print("=" * 70)
    
    from text_to_math_extractor.integration import HybridValidatorBridge
    
    bridge = HybridValidatorBridge()
    
    # Test with various problem types
    test_problems = [
        {
            "problem_text": "Multiply $5$ by $3$",
            "final_answer": "15",
            "template_id": "test_001"
        },
        {
            "problem_text": "Multiply 87265 by 32117",
            "final_answer": "2,800,797,005",
            "template_id": "test_002"
        },
        {
            "problem_text": "If John has 5 apples...",
            "final_answer": "5",
            "template_id": "test_003"
        },
    ]
    
    print("\nProcessing with Hybrid Validator Bridge:")
    for prob in test_problems:
        result = bridge.process_problem(
            problem_text=prob["problem_text"],
            final_answer=prob["final_answer"],
            template_id=prob["template_id"]
        )
        
        print(f"\n  Template: {result['template_id']}")
        print(f"  Method: {result['method']}")
        print(f"  Status: {result['status']}")
        print(f"  Match: {result['match']}")


def example_pattern_variations():
    """Example 6: Different variations of the same operation."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 6: Pattern Variations")
    print("=" * 70)
    
    extractor = TextToMathExtractor()
    
    # Multiplication variations
    mult_variations = [
        "Multiply 5 by 3",
        "5 × 3",
        "Product of 5 and 3",
        "5 x 3",
        "5 times 3",
    ]
    
    print("\nMultiplication Variations:")
    for text in mult_variations:
        result = extractor.process(text, expected_answer="15")
        print(f"  {text:30} -> {result.pattern_matched or 'NO MATCH'}")
    
    # Division variations
    div_variations = [
        "Divide 10 by 2",
        "10 divided by 2",
        "Division of 10 by 2",
        "10 ÷ 2",
    ]
    
    print("\nDivision Variations:")
    for text in div_variations:
        result = extractor.process(text, expected_answer="5")
        print(f"  {text:30} -> {result.pattern_matched or 'NO MATCH'}")


def example_checkpoint_system():
    """Example 7: Using checkpoint system for batch processing."""
    print("\n\n" + "=" * 70)
    print("EXAMPLE 7: Checkpoint System")
    print("=" * 70)
    
    from text_to_math_extractor.batch_processor import BatchProcessor
    
    # Create processor
    processor = BatchProcessor(
        checkpoint_dir="/tmp/test_checkpoints",
        output_dir="/tmp/test_output",
        batch_size=5
    )
    
    # Create test templates
    templates = [
        {"template_id": f"test_{i}", "question_text": f"Multiply {i} by 2", "final_answer": str(i * 2)}
        for i in range(1, 11)
    ]
    
    print(f"\nProcessing {len(templates)} templates with checkpointing...")
    
    # Simulate processing with checkpoint
    summary = processor.process_templates(
        templates=templates,
        batch_id="demo_batch_001"
    )
    
    print("\nSummary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    # Show checkpoint
    checkpoint = processor.load_checkpoint("demo_batch_001")
    if checkpoint:
        print(f"\nCheckpoint loaded: {checkpoint.processed_count}/{checkpoint.total_count} processed")


def run_all_examples():
    """Run all examples."""
    examples = [
        example_basic_extraction,
        example_word_problems_rejection,
        example_confidence_levels,
        example_batch_processing,
        example_integration,
        example_pattern_variations,
        example_checkpoint_system,
    ]
    
    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"\nError in {example.__name__}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    run_all_examples()
