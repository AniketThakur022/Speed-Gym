#!/usr/bin/env python3
"""
CLI for Text-to-Math Extractor

Usage:
    python cli.py process-file templates.json --batch-id batch_001
    python cli.py test "Multiply 87265 by 32117" --expected "2,800,797,005"
    python cli.py stats --batch-id batch_001
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from text_to_math_extractor import TextToMathExtractor
from text_to_math_extractor.batch_processor import BatchProcessor, load_solve_along_templates


def cmd_test(args):
    """Test single problem extraction."""
    extractor = TextToMathExtractor()
    
    result = extractor.process(
        text=args.text,
        expected_answer=args.expected,
        template_id="test"
    )
    
    print("=" * 60)
    print("EXTRACTION RESULT")
    print("=" * 60)
    print(f"Original Text: {result.original_text}")
    print(f"Cleaned Text: {result.cleaned_text}")
    print(f"Pattern Matched: {result.pattern_matched}")
    print(f"Operation: {result.operation}")
    print(f"Extracted Numbers: {result.extracted_numbers}")
    print(f"SymPy Expression: {result.sympy_expression}")
    print(f"Computed Value: {result.computed_value}")
    print(f"Expected Answer: {result.expected_answer}")
    print(f"Verification Status: {result.verification_status}")
    
    if result.confidence:
        print(f"\nConfidence Level: {result.confidence.level.value}")
        print(f"Confidence Score: {result.confidence.score}")
        print(f"Confidence Reason: {result.confidence.reason}")
        print(f"Component Scores:")
        for key, val in result.confidence.details.get("component_scores", {}).items():
            print(f"  - {key}: {val:.2f}")
    
    print("=" * 60)


def cmd_process_file(args):
    """Process a template file."""
    # Load templates
    templates = load_solve_along_templates([args.input_file])
    
    print(f"Loaded {len(templates)} templates from {args.input_file}")
    
    # Create processor
    processor = BatchProcessor(
        checkpoint_dir=args.checkpoint_dir,
        output_dir=args.output_dir,
        batch_size=args.batch_size
    )
    
    # Process
    summary = processor.process_templates(
        templates=templates,
        batch_id=args.batch_id
    )
    
    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Batch ID: {summary['batch_id']}")
    print(f"Total Processed: {summary['total_processed']}")
    print(f"\nConfidence Distribution:")
    print(f"  - High: {summary['high_confidence']}")
    print(f"  - Medium: {summary['medium_confidence']}")
    print(f"  - Low: {summary['low_confidence']}")
    print(f"  - Rejected: {summary['rejected']}")
    print(f"\nVerification:")
    print(f"  - Verified Match: {summary['verified_match']}")
    print(f"  - Verified Mismatch: {summary['verified_mismatch']}")
    print(f"\nRouting:")
    print(f"  - Math Audit Eligible: {summary['math_audit_eligible']}")
    print(f"  - LLM Audit Required: {summary['llm_audit_required']}")
    print("=" * 60)


def cmd_stats(args):
    """Show batch statistics."""
    processor = BatchProcessor(
        checkpoint_dir=args.checkpoint_dir,
        output_dir=args.output_dir
    )
    
    checkpoint = processor.load_checkpoint(args.batch_id)
    
    if checkpoint is None:
        print(f"No checkpoint found for batch: {args.batch_id}")
        return
    
    print("=" * 60)
    print(f"BATCH STATISTICS: {args.batch_id}")
    print("=" * 60)
    print(f"Processed: {checkpoint.processed_count} / {checkpoint.total_count}")
    print(f"Last Updated: {checkpoint.last_updated}")
    print(f"\nConfidence Distribution:")
    print(f"  - High: {checkpoint.high_confidence_count}")
    print(f"  - Medium: {checkpoint.medium_confidence_count}")
    print(f"  - Low: {checkpoint.low_confidence_count}")
    print(f"  - Rejected: {checkpoint.rejected_count}")
    print(f"\nVerification:")
    print(f"  - Match: {checkpoint.verified_match}")
    print(f"  - Mismatch: {checkpoint.verified_mismatch}")
    
    # Calculate percentages
    if checkpoint.processed_count > 0:
        print(f"\nPercentages:")
        total = checkpoint.processed_count
        print(f"  - High Confidence: {checkpoint.high_confidence_count / total * 100:.1f}%")
        print(f"  - Success Rate: {(checkpoint.high_confidence_count + checkpoint.medium_confidence_count) / total * 100:.1f}%")
    
    print("=" * 60)


def cmd_export_llm(args):
    """Export LLM audit items."""
    processor = BatchProcessor(
        checkpoint_dir=args.checkpoint_dir,
        output_dir=args.output_dir
    )
    
    output_path = processor.export_for_llm_audit(
        batch_id=args.batch_id,
        output_path=args.output
    )
    
    print(f"Exported LLM audit items to: {output_path}")


def cmd_demo(args):
    """Run demo with example problems."""
    test_cases = [
        ("Multiply 87265 by 32117", "2,800,797,005"),
        ("Divide 1000 by 25", "40"),
        ("Find the square of 25", "625"),
        ("What is the cube of 3", "27"),
        ("LCM of 150, 210", "1050"),
        ("GCD of 48, 18", "6"),
        ("Square root of 144", "12"),
        ("20 percent of 150", "30"),
        ("Add 5, 10, and 15", "30"),
        ("If a train travels at 60 mph for 2 hours, how far does it go?", ""),  # Word problem - should reject
    ]
    
    extractor = TextToMathExtractor()
    
    print("=" * 80)
    print("TEXT-TO-MATH EXTRACTOR DEMO")
    print("=" * 80)
    
    for text, expected in test_cases:
        result = extractor.process(text, expected_answer=expected)
        
        print(f"\nProblem: {text}")
        print(f"  Pattern: {result.pattern_matched or 'None'}")
        print(f"  Numbers: {result.extracted_numbers}")
        print(f"  Expression: {result.sympy_expression or 'N/A'}")
        print(f"  Computed: {result.computed_value or 'N/A'}")
        print(f"  Expected: {result.expected_answer or 'N/A'}")
        print(f"  Verification: {result.verification_status}")
        if result.confidence:
            print(f"  Confidence: {result.confidence.level.value} ({result.confidence.score:.2f})")
    
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    stats = extractor.get_stats()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2%}")
        else:
            print(f"  {key}: {value}")


def main():
    parser = argparse.ArgumentParser(
        description="Text-to-Math Extractor CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single problem
  python cli.py test "Multiply 5 by 3" --expected "15"
  
  # Process template file
  python cli.py process-file templates.json --batch-id batch_001
  
  # View batch stats
  python cli.py stats --batch-id batch_001
  
  # Run demo
  python cli.py demo
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Test command
    test_parser = subparsers.add_parser("test", help="Test single extraction")
    test_parser.add_argument("text", help="Problem text to process")
    test_parser.add_argument("--expected", help="Expected answer")
    test_parser.set_defaults(func=cmd_test)
    
    # Process file command
    process_parser = subparsers.add_parser("process-file", help="Process template file")
    process_parser.add_argument("input_file", help="Path to template JSON file")
    process_parser.add_argument("--batch-id", required=True, help="Batch identifier")
    process_parser.add_argument("--checkpoint-dir", default="/workspace/data/checkpoints")
    process_parser.add_argument("--output-dir", default="/workspace/data/audit_results")
    process_parser.add_argument("--batch-size", type=int, default=50)
    process_parser.set_defaults(func=cmd_process_file)
    
    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show batch statistics")
    stats_parser.add_argument("--batch-id", required=True, help="Batch identifier")
    stats_parser.add_argument("--checkpoint-dir", default="/workspace/data/checkpoints")
    stats_parser.add_argument("--output-dir", default="/workspace/data/audit_results")
    stats_parser.set_defaults(func=cmd_stats)
    
    # Export LLM command
    export_parser = subparsers.add_parser("export-llm", help="Export LLM audit items")
    export_parser.add_argument("--batch-id", required=True, help="Batch identifier")
    export_parser.add_argument("--output", help="Custom output path")
    export_parser.add_argument("--checkpoint-dir", default="/workspace/data/checkpoints")
    export_parser.add_argument("--output-dir", default="/workspace/data/audit_results")
    export_parser.set_defaults(func=cmd_export_llm)
    
    # Demo command
    demo_parser = subparsers.add_parser("demo", help="Run demo with example problems")
    demo_parser.set_defaults(func=cmd_demo)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
