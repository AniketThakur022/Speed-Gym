#!/usr/bin/env python3
"""
Text-to-Math Audit Batch Processor
Re-processes INCORRECT/STALEMATE templates through text-to-math extractor
"""

import sys
import json
import traceback
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/workspace/assembly_line')

from text_to_math_extractor.extractor import TextToMathExtractor
from text_to_math_extractor.confidence import ConfidenceLevel


def load_templates():
    template_dir = Path('/workspace/data/enrichment/templates/solve_along')
    templates = []
    if not template_dir.exists():
        raise FileNotFoundError(f"Template dir not found: {template_dir}")
    
    for jsonl_file in sorted(template_dir.glob('*.jsonl')):
        with open(jsonl_file, 'r') as f:
            for line in f:
                if line.strip():
                    templates.append(json.loads(line))
    return templates


def filter_targets(templates):
    targets = []
    for template in templates:
        examples = template.get('examples', [])
        for ex in examples:
            status = ex.get('_llm_consensus_status', '')
            if status in ('INCORRECT', 'STALEMATE'):
                # Handle example_num as int or string safely
                ex_num = ex.get('example_num', 0)
                if isinstance(ex_num, str):
                    try:
                        ex_num = int(ex_num)
                    except (ValueError, TypeError):
                        ex_num = 0
                
                targets.append({
                    'template_id': template.get('template_id', ''),
                    'example_idx': ex_num - 1 if ex_num > 0 else 0,
                    'problem_text': ex.get('problem_text', ''),
                    'final_answer': ex.get('final_answer', ''),
                    'problem_statement': ex.get('problem_statement', ''),
                    'original_status': status,
                    'source_book': template.get('source', {}).get('book', ''),
                    'technique': template.get('concept', {}).get('technique_name', ''),
                    'reasoning_quality': ex.get('_llm_consensus_details', {})
                })
    return targets


def main():
    print("=" * 80)
    print("TEXT-TO-MATH AUDIT BATCH PROCESSOR")
    print("=" * 80)
    
    # Load
    all_templates = load_templates()
    print(f"\nTotal templates loaded: {len(all_templates)}")
    
    targets = filter_targets(all_templates)
    print(f"INCORRECT/STALEMATE targets: {len(targets)}")
    
    if not targets:
        print("No targets to process. Exiting.")
        return
    
    # Extractor
    extractor = TextToMathExtractor()
    
    # Stats
    stats = defaultdict(int)
    by_pattern = defaultdict(int)
    by_technique = defaultdict(lambda: defaultdict(int))
    
    # Results
    math_audit = []
    llm_audit = []
    errors = []
    
    # Process
    print(f"\nProcessing {len(targets)} templates...")
    
    for i, item in enumerate(targets):
        try:
            result = extractor.process(
                text=item['problem_text'],
                expected_answer=item['final_answer'],
                template_id=item['template_id'],
                metadata={
                    'example_idx': item['example_idx'],
                    'original_status': item['original_status'],
                    'technique': item['technique'],
                }
            )
            
            stats['processed'] += 1
            
            if result.confidence and result.confidence.level == ConfidenceLevel.REJECT:
                llm_audit.append({
                    'template_id': item['template_id'],
                    'problem_text': item['problem_text'][:100] if item['problem_text'] else '',
                    'final_answer': item['final_answer'][:50] if item['final_answer'] else '',
                    'original_status': item['original_status'],
                    'reason': result.confidence.reason,
                })
                stats['rejected'] += 1
                by_technique[item['technique']]['rejected'] += 1
            else:
                pattern = result.pattern_matched or 'unknown'
                by_pattern[pattern] += 1
                stats['extracted'] += 1
                
                if result.verification_status == 'match':
                    math_audit.append({
                        'template_id': item['template_id'],
                        'problem_text': item['problem_text'][:100] if item['problem_text'] else '',
                        'final_answer': item['final_answer'][:50] if item['final_answer'] else '',
                        'original_status': item['original_status'],
                        'pattern': pattern,
                        'computed_value': result.computed_value,
                        'confidence': result.confidence.score if result.confidence else 0,
                    })
                    stats['verified_match'] += 1
                    by_technique[item['technique']]['match'] += 1
                else:
                    llm_audit.append({
                        'template_id': item['template_id'],
                        'problem_text': item['problem_text'][:100] if item['problem_text'] else '',
                        'final_answer': item['final_answer'][:50] if item['final_answer'] else '',
                        'original_status': item['original_status'],
                        'pattern': pattern,
                        'computed_value': result.computed_value,
                        'reason': result.verification_status,
                    })
                    by_technique[item['technique']]['mismatch'] += 1
            
            if (i + 1) % 100 == 0:
                print(f"  Processed {i+1}/{len(targets)} (Match: {stats['verified_match']}, Rejected: {stats['rejected']})")
                
        except Exception as e:
            stats['errors'] += 1
            errors.append({
                'template_id': item.get('template_id', ''),
                'error': str(e),
                'traceback': traceback.format_exc()[:500],
            })
    
    # Save
    out_dir = Path('/workspace/data/audit_results')
    out_dir.mkdir(parents=True, exist_ok=True)
    
    with open(out_dir / 'math_audit' / 'math_audit_results.jsonl', 'w') as f:
        for item in math_audit:
            f.write(json.dumps(item) + '\n')
    
    with open(out_dir / 'llm_audit' / 'llm_audit_results.jsonl', 'w') as f:
        for item in llm_audit:
            f.write(json.dumps(item) + '\n')
    
    # Report
    report = {
        'metadata': {
            'total_templates': len(all_templates),
            'targets': len(targets),
            'processed': stats['processed'],
            'errors': stats['errors'],
        },
        'summary': {
            'extracted': stats['extracted'],
            'verified_match': stats['verified_match'],
            'verified_mismatch': stats.get('verified_mismatch', max(0, stats['extracted'] - stats['verified_match'])),
            'rejected': stats['rejected'],
        },
        'coverage': {
            'math_audit': len(math_audit),
            'llm_audit': len(llm_audit),
            'resolution_rate': f"{100 * stats['verified_match'] / len(targets) if targets else 0:.1f}%",
            'extraction_rate': f"{100 * stats['extracted'] / len(targets) if targets else 0:.1f}%",
        },
        'by_pattern': dict(by_pattern),
        'by_technique': {k: dict(v) for k, v in by_technique.items()},
    }
    
    report_path = Path('/workspace/data/reports')
    report_path.mkdir(parents=True, exist_ok=True)
    with open(report_path / 'text_to_math_audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    if errors:
        with open(report_path / 'processing_errors.json', 'w') as f:
            json.dump(errors[:20], f, indent=2)
    
    # Print
    print(f"\n{'=' * 80}")
    print(f"PROCESSING COMPLETE")
    print(f"{'=' * 80}")
    print(f"\nTotal:     {len(targets)}")
    print(f"Processed: {stats['processed']}")
    print(f"  MATCH:   {stats['verified_match']} ({100*stats['verified_match']/len(targets):.1f}%)")
    mismatch = stats['extracted'] - stats['verified_match']
    print(f"  MISMATCH:{mismatch} ({100*mismatch/len(targets):.1f}%)")
    print(f"  REJECTED:{stats['rejected']} ({100*stats['rejected']/len(targets):.1f}%)")
    print(f"  ERRORS:  {stats['errors']}")
    
    print(f"\nFiles saved:")
    print(f"  Math audit: {len(math_audit)} items")
    print(f"  LLM audit:  {len(llm_audit)} items")
    print(f"  Report:     {report_path / 'text_to_math_audit_report.json'}")
    
    print(f"\nTop patterns:")
    for p, c in sorted(by_pattern.items(), key=lambda x: -x[1])[:10]:
        print(f"  {p}: {c}")
    
    print(f"\n✅ Complete!")


if __name__ == '__main__':
    main()
