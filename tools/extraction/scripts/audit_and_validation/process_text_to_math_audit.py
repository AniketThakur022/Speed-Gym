#!/usr/bin/env python3
"""
Text-to-Math Batch Processor for INCORRECT/STALEMATE Templates

Processes solve_along templates that were flagged as INCORRECT or STALEMATE
by the L2 consensus, attempting to extract computable math from plain text.

Usage:
    source /workspace/venv/bin/activate
    python3 process_text_to_math_audit.py

Output:
    - /workspace/data/audit_results/math_audit/    : Extractable + verified templates
    - /workspace/data/audit_results/llm_audit/     : Requires LLM fallback
    - /workspace/data/reports/text_to_math_audit_report.json : Summary statistics
"""

import sys
import json
import glob
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/workspace/assembly_line')

from text_to_math_extractor.extractor import TextToMathExtractor
from text_to_math_extractor.confidence import ConfidenceLevel
from text_to_math_extractor.batch_processor import BatchProcessor


def load_templates():
    """Load all solve_along templates from JSONL files."""
    template_dir = Path('/workspace/data/enrichment/templates/solve_along')
    templates = []
    
    for jsonl_file in sorted(template_dir.glob('*.jsonl')):
        with open(jsonl_file, 'r') as f:
            for line in f:
                if line.strip():
                    templates.append(json.loads(line))
    
    return templates


def filter_incorrect_stalemate(templates):
    """Filter templates that have INCORRECT or STALEMATE consensus status."""
    filtered = []
    
    for template in templates:
        examples = template.get('examples', [])
        for ex in examples:
            status = ex.get('_llm_consensus_status', '')
            if status in ('INCORRECT', 'STALEMATE'):
                filtered.append({
                    'template_id': template.get('template_id', ''),
                    'template_name': template.get('template_name', template.get('template_id', '')),
                    'example_idx': ex.get('example_num', 0) - 1,
                    'problem_text': ex.get('problem_text', ''),
                    'final_answer': ex.get('final_answer', ''),
                    'problem_statement': ex.get('problem_statement', ''),
                    '_llm_consensus_status': status,
                    '_llm_consensus_details': ex.get('_llm_consensus_details', {}),
                    'source_book': template.get('source', {}).get('book', ''),
                    'technique': template.get('concept', {}).get('technique_name', ''),
                    'full_template': template,
                })
    
    return filtered


def categorize_by_topic(filtered_items):
    """Group items by source book/technique for analysis."""
    topics = defaultdict(list)
    for item in filtered_items:
        key = f"{item['source_book']}_{item['technique']}" if item['source_book'] else 'unknown'
        topics[key].append(item)
    return topics


def main():
    print("=" * 80)
    print("TEXT-TO-MATH AUDIT BATCH PROCESSOR")
    print("=" * 80)
    print()
    
    # Step 1: Load all templates
    print("Step 1: Loading templates...")
    all_templates = load_templates()
    print(f"  Total templates loaded: {len(all_templates)}")
    
    # Step 2: Filter for INCORRECT/STALEMATE
    print("\nStep 2: Filtering for INCORRECT/STALEMATE...")
    targets = filter_incorrect_stalemate(all_templates)
    print(f"  Templates with INCORRECT/STALEMATE consensus: {len(targets)}")
    
    # Show breakdown
    status_counts = defaultdict(int)
    for t in targets:
        status_counts[t['_llm_consensus_status']] += 1
    for status, count in status_counts.items():
        print(f"    {status}: {count}")
    
    # Step 3: Initialize extractor
    print("\nStep 3: Initializing TextToMathExtractor...")
    extractor = TextToMathExtractor()
    processor = BatchProcessor(
        checkpoint_dir='/workspace/data/checkpoints',
        output_dir='/workspace/data/audit_results',
        extractor=extractor,
        batch_size=50
    )
    
    # Step 4: Process templates
    print("\nStep 4: Processing templates...")
    
    results = {
        'math_audit': [],
        'llm_audit': [],
        'errors': [],
    }
    
    stats = {
        'total': len(targets),
        'processed': 0,
        'extracted': 0,
        'verified_match': 0,
        'verified_mismatch': 0,
        'rejected': 0,
        'errors': 0,
        'by_pattern': defaultdict(int),
        'by_technique': defaultdict(lambda: defaultdict(int)),
    }
    
    for i, item in enumerate(targets):
        try:
            # Process through extractor
            result = extractor.process(
                text=item['problem_text'],
                expected_answer=item['final_answer'],
                template_id=item['template_id'],
                metadata={
                    'example_idx': item['example_idx'],
                    'source_book': item['source_book'],
                    'technique': item['technique'],
                    'original_status': item['_llm_consensus_status'],
                }
            )
            
            stats['processed'] += 1
            
            # Categorize
            if result.confidence and result.confidence.level == ConfidenceLevel.REJECT:
                results['llm_audit'].append({
                    'template_id': item['template_id'],
                    'example_idx': item['example_idx'],
                    'problem_text': item['problem_text'],
                    'final_answer': item['final_answer'],
                    'original_status': item['_llm_consensus_status'],
                    'rejection_reason': result.confidence.reason if result.confidence else 'unknown',
                })
                stats['rejected'] += 1
                stats['by_technique'][item['technique']]['rejected'] += 1
            else:
                # Could be extracted
                stats['extracted'] += 1
                pattern = result.pattern_matched or 'unknown'
                stats['by_pattern'][pattern] += 1
                
                if result.verification_status == 'match':
                    stats['verified_match'] += 1
                    stats['by_technique'][item['technique']]['match'] += 1
                    results['math_audit'].append({
                        'template_id': item['template_id'],
                        'example_idx': item['example_idx'],
                        'problem_text': item['problem_text'],
                        'final_answer': item['final_answer'],
                        'original_status': item['_llm_consensus_status'],
                        'pattern': pattern,
                        'computed_value': result.computed_value,
                        'confidence': result.confidence.score if result.confidence else 0,
                        'sympy_expression': result.sympy_expression,
                    })
                elif result.verification_status == 'mismatch':
                    stats['verified_mismatch'] += 1
                    stats['by_technique'][item['technique']]['mismatch'] += 1
                    results['llm_audit'].append({
                        'template_id': item['template_id'],
                        'example_idx': item['example_idx'],
                        'problem_text': item['problem_text'],
                        'final_answer': item['final_answer'],
                        'original_status': item['_llm_consensus_status'],
                        'pattern': pattern,
                        'computed_value': result.computed_value,
                        'rejection_reason': f"mismatch: computed={result.computed_value}, expected={item['final_answer']}",
                    })
                else:
                    # Other status (no expected answer, error, etc.)
                    stats['by_technique'][item['technique']]['other'] += 1
                    results['llm_audit'].append({
                        'template_id': item['template_id'],
                        'example_idx': item['example_idx'],
                        'problem_text': item['problem_text'],
                        'final_answer': item['final_answer'],
                        'original_status': item['_llm_consensus_status'],
                        'pattern': pattern,
                        'computed_value': result.computed_value,
                        'rejection_reason': result.verification_status,
                    })
            
            # Progress
            if (i + 1) % 50 == 0:
                print(f"  Processed {i+1}/{len(targets)}...")
                
        except Exception as e:
            stats['errors'] += 1
            results['errors'].append({
                'template_id': item.get('template_id', ''),
                'error': str(e),
            })
    
    # Step 5: Save results
    print("\nStep 5: Saving results...")
    
    # Math audit results
    math_audit_path = Path('/workspace/data/audit_results/math_audit')
    math_audit_path.mkdir(parents=True, exist_ok=True)
    with open(math_audit_path / 'math_audit_results.jsonl', 'w') as f:
        for item in results['math_audit']:
            f.write(json.dumps(item) + '\n')
    
    # LLM audit results
    llm_audit_path = Path('/workspace/data/audit_results/llm_audit')
    llm_audit_path.mkdir(parents=True, exist_ok=True)
    with open(llm_audit_path / 'llm_audit_results.jsonl', 'w') as f:
        for item in results['llm_audit']:
            f.write(json.dumps(item) + '\n')
    
    # Error log
    if results['errors']:
        with open('/workspace/data/audit_results/processing_errors.json', 'w') as f:
            json.dump(results['errors'], f, indent=2)
    
    # Final report
    report = {
        'metadata': {
            'total_templates': len(all_templates),
            'target_templates': len(targets),
            'processed': stats['processed'],
            'errors': stats['errors'],
        },
        'summary': {
            'extracted': stats['extracted'],
            'verified_match': stats['verified_match'],
            'verified_mismatch': stats['verified_mismatch'],
            'rejected': stats['rejected'],
            'math_audit_eligible': stats['verified_match'],
            'llm_audit_required': stats['verified_mismatch'] + stats['rejected'],
        },
        'by_pattern': dict(stats['by_pattern']),
        'by_technique': {k: dict(v) for k, v in stats['by_technique'].items()},
        'patterns': {p: stats['by_pattern'][p] for p in sorted(stats['by_pattern'], key=stats['by_pattern'].get, reverse=True)},
    }
    
    report_path = Path('/workspace/data/reports/text_to_math_audit_report.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'=' * 80}")
    print("PROCESSING COMPLETE")
    print(f"{'=' * 80}")
    print(f"\nTotal templates:             {len(targets)}")
    print(f"Successfully processed:        {stats['processed']}")
    print(f"  Extracted (computable):    {stats['extracted']}")
    print(f"    Verified MATCH:            {stats['verified_match']}")
    print(f"    Verified MISMATCH:         {stats['verified_mismatch']}")
    print(f"  Rejected (needs LLM):       {stats['rejected']}")
    print(f"Errors:                       {stats['errors']}")
    print(f"\nFiles saved:")
    print(f"  Math audit:  {math_audit_path / 'math_audit_results.jsonl'}")
    print(f"  LLM audit:   {llm_audit_path / 'llm_audit_results.jsonl'}")
    print(f"  Report:      {report_path}")
    
    print(f"\nTop patterns:")
    for pattern, count in sorted(stats['by_pattern'].items(), key=lambda x: -x[1])[:10]:
        print(f"  {pattern}: {count}")
    
    print(f"\nBy technique:")
    for tech, counts in sorted(stats['by_technique'].items(), key=lambda x: -(sum(x[1].values()))):
        total = sum(counts.values())
        match = counts.get('match', 0)
        print(f"  {tech}: {total} total, {match} matches")
    
    print(f"\n✅ Batch processing complete!")


if __name__ == '__main__':
    main()
