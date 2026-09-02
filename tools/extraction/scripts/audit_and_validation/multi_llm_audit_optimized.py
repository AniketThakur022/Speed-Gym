#!/usr/bin/env python3
"""
Multi-LLM Audit Processor - OPTIMIZED
Parallel processing, incremental saves, resume capability, ETA tracking

Strategy:
- STALEMATE (616 items): Single model final-answer check → fast recovery
- INCORRECT (279 items): 2-model jury (beta+gamma) → deep validation

Usage:
    source /workspace/venv/bin/activate
    cd /workspace/assembly_line
    python3 /workspace/multi_llm_audit_optimized.py

Output:
    - /workspace/data/audit_results/llm_audit/resolved_stalemate.jsonl
    - /workspace/data/audit_results/llm_audit/resolved_incorrect.jsonl
    - /workspace/data/reports/multi_llm_audit_report.json
"""

import sys
sys.path.insert(0, '/workspace/assembly_line')
sys.path.insert(0, '/workspace/assembly_line/hybrid_validator_v3')

import json
import time
import os
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from hybrid_validator_v3.l2_jury import query_model

# Configuration
MODELS = {
    'beta': 'qwen3-vl:235b-instruct',
    'gamma': 'deepseek-v3.1:671b',
}

OLLAMA_URL = "https://ollama.com/v1/chat/completions"


def p(msg, flush=True):
    """Print with flush for immediate visibility."""
    print(msg)
    if flush:
        sys.stdout.flush()


def append_result(filepath, result):
    """Append result to JSONL with fsync for crash safety."""
    with open(filepath, 'a') as f:
        f.write(json.dumps(result) + '\n')
        f.flush()
        os.fsync(f.fileno())


def save_checkpoint(filepath, data):
    """Save checkpoint with timing metadata."""
    checkpoint_path = str(filepath) + '.checkpoint'
    with open(checkpoint_path, 'w') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def load_processed_ids(filepath):
    """Load already-processed template IDs from JSONL."""
    processed = set()
    if not Path(filepath).exists():
        return processed
    
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    processed.add(data.get('template_id', ''))
    except (json.JSONDecodeError, FileNotFoundError):
        pass
    
    return processed


def load_llm_audit_items():
    """Load items from text-to-math LLM audit output."""
    items = []
    path = Path('/workspace/data/audit_results/llm_audit/llm_audit_results.jsonl')
    
    with open(path, 'r') as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def build_stalemate_prompt(item):
    """Build focused prompt for STALEMATE recovery."""
    problem = item.get('problem_text', '')[:200]
    answer = item.get('final_answer', '')[:100]
    
    return f"""You are a math verification specialist. Check if the final answer is mathematically correct.

Problem: {problem}
Expected Answer: {answer}

Check ONLY the final answer (not the solution steps). Return JSON:
{{"final_answer_correct": true/false, "correct_answer": "the exact correct answer if wrong", "confidence": 0.0-1.0, "explanation": "brief reason"}}

Respond with ONLY the JSON object, no markdown."""


def build_incorrect_prompt(item):
    """Build comprehensive prompt for INCORRECT deep-dive."""
    problem = item.get('problem_text', '')[:300]
    answer = item.get('final_answer', '')[:100]
    
    return f"""You are a math verification specialist. Verify this template thoroughly.

Problem: {problem}
Expected Answer: {answer}

Check:
1. Is the final answer mathematically correct?
2. Are the solution steps logically valid?
3. Is there any trap or error?

Return JSON:
{{"final_answer_correct": true/false, "correct_answer": "the exact correct answer if wrong", "step_logic_valid": true/false, "trap_detected": "description or null", "error_category": "MATH_ERROR|LOGIC_ERROR|NOTATION_ERROR|CORRECT", "reasoning_quality": 1-5, "confidence": 0.0-1.0, "explanation": "detailed reasoning"}}

Respond with ONLY the JSON object, no markdown."""


def audit_stalemate_item(item):
    """Audit a single STALEMATE item with one model."""
    prompt = build_stalemate_prompt(item)
    
    # Try gamma first (most reliable)
    result = query_model(prompt, MODELS['gamma'], max_tokens=500, timeout=45)
    
    if result and not result.get('_parse_error'):
        return {
            'template_id': item['template_id'],
            'original_status': 'STALEMATE',
            'model': 'gamma',
            'verdict': result.get('final_answer_correct', False),
            'correct_answer': result.get('correct_answer', ''),
            'confidence': result.get('confidence', 0.0),
            'explanation': result.get('explanation', '')[:200],
            'raw': result,
        }
    
    # Fallback to beta
    result = query_model(prompt, MODELS['beta'], max_tokens=500, timeout=45)
    if result and not result.get('_parse_error'):
        return {
            'template_id': item['template_id'],
            'original_status': 'STALEMATE',
            'model': 'beta',
            'verdict': result.get('final_answer_correct', False),
            'correct_answer': result.get('correct_answer', ''),
            'confidence': result.get('confidence', 0.0),
            'explanation': result.get('explanation', '')[:200],
            'raw': result,
        }
    
    return {
        'template_id': item['template_id'],
        'original_status': 'STALEMATE',
        'model': 'both_failed',
        'verdict': None,
        'error': 'API failure',
    }


def audit_incorrect_item(item):
    """Audit a single INCORRECT item with 2-model jury."""
    prompt = build_incorrect_prompt(item)
    
    # Query both models
    gamma_result = query_model(prompt, MODELS['gamma'], max_tokens=800, timeout=60)
    beta_result = query_model(prompt, MODELS['beta'], max_tokens=800, timeout=60)
    
    results = {
        'template_id': item['template_id'],
        'original_status': 'INCORRECT',
        'verdicts': [],
    }
    
    # Parse gamma
    if gamma_result and not gamma_result.get('_parse_error'):
        results['verdicts'].append({
            'model': 'gamma',
            'correct': gamma_result.get('final_answer_correct', False),
            'confidence': gamma_result.get('confidence', 0.0),
            'reasoning_quality': gamma_result.get('reasoning_quality', 0),
            'trap': gamma_result.get('trap_detected'),
        })
    
    # Parse beta
    if beta_result and not beta_result.get('_parse_error'):
        results['verdicts'].append({
            'model': 'beta',
            'correct': beta_result.get('final_answer_correct', False),
            'confidence': beta_result.get('confidence', 0.0),
            'reasoning_quality': beta_result.get('reasoning_quality', 0),
            'trap': beta_result.get('trap_detected'),
        })
    
    # Consensus logic
    valid_votes = [v for v in results['verdicts'] if v['confidence'] >= 0.5]
    
    if len(valid_votes) >= 2:
        if all(v['correct'] for v in valid_votes):
            results['consensus'] = 'PROMOTE_TO_CORRECT'
        elif all(not v['correct'] for v in valid_votes):
            results['consensus'] = 'CONFIRMED_INCORRECT'
        else:
            results['consensus'] = 'STALEMATE'
    elif len(valid_votes) == 1:
        results['consensus'] = 'SINGLE_VOTE_' + ('CORRECT' if valid_votes[0]['correct'] else 'INCORRECT')
    else:
        results['consensus'] = 'NO_VALID_VOTES'
    
    return results


def process_batch(items, output_path, process_fn, batch_size=8, max_workers=4):
    """Process items in parallel batches with progress tracking."""
    processed_ids = load_processed_ids(output_path)
    
    # Filter already processed
    remaining = [item for item in items if item['template_id'] not in processed_ids]
    skipped = len(items) - len(remaining)
    
    if skipped:
        p(f"  Resuming: {skipped} already processed, {len(remaining)} remaining")
    
    if not remaining:
        p("  All items already processed!")
        return []
    
    results = []
    start_time = time.time()
    total = len(remaining)
    processed_count = 0
    
    # Process in batches
    for batch_start in range(0, total, batch_size):
        batch = remaining[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (total - 1) // batch_size + 1
        
        p(f"\n  Batch {batch_num}/{total_batches} ({len(batch)} items)...")
        batch_start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_fn, item): item for item in batch}
            
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    append_result(output_path, result)
                    processed_count += 1
                    
                    # Progress display
                    if result.get('verdict') is True or 'PROMOTE' in str(result.get('consensus', '')):
                        icon = "⬆️"
                    elif result.get('verdict') is False or 'CONFIRMED' in str(result.get('consensus', '')):
                        icon = "✅"
                    elif result.get('verdict') is None or 'NO_VALID' in str(result.get('consensus', '')):
                        icon = "⚠️"
                    else:
                        icon = "➡️"
                    
                except Exception as e:
                    p(f"  💥 {item['template_id'][:40]:40} → ERROR: {e}")
                    error_result = {
                        'template_id': item['template_id'],
                        'error': str(e),
                    }
                    append_result(output_path, error_result)
        
        # Batch timing
        batch_elapsed = time.time() - batch_start_time
        items_per_sec = len(batch) / batch_elapsed if batch_elapsed > 0 else 0
        items_per_min = items_per_sec * 60
        remaining_items = total - processed_count
        eta_seconds = remaining_items / items_per_sec if items_per_sec > 0 else 0
        
        p(f"  Batch complete: {len(batch)} items in {batch_elapsed:.1f}s ({items_per_min:.1f}/min)")
        p(f"  Progress: {processed_count}/{total} ({100*processed_count/total:.1f}%) ETA: {eta_seconds/60:.1f}min")
        
        # Save checkpoint
        save_checkpoint(output_path, {
            'phase': 'in_progress',
            'processed_count': processed_count,
            'total': total,
            'elapsed_seconds': time.time() - start_time,
            'items_per_second': items_per_sec,
            'eta_seconds': eta_seconds,
            'last_save': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        })
    
    return results


def main():
    p("=" * 80)
    p("MULTI-LLM AUDIT PROCESSOR - OPTIMIZED")
    p("=" * 80)
    
    # Load items
    p("\nLoading LLM audit items...")
    items = load_llm_audit_items()
    
    stalemates = [i for i in items if i['original_status'] == 'STALEMATE']
    incorrects = [i for i in items if i['original_status'] == 'INCORRECT']
    
    p(f"  Total: {len(items)}")
    p(f"  STALEMATE: {len(stalemates)}")
    p(f"  INCORRECT: {len(incorrects)}")
    
    out_dir = Path('/workspace/data/audit_results/llm_audit')
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # --- Phase 1: STALEMATE Recovery ---
    stalemate_path = out_dir / 'resolved_stalemate.jsonl'
    
    p(f"\n{'=' * 80}")
    p(f"PHASE 1: STALEMATE RECOVERY ({len(stalemates)} items)")
    p(f"{'=' * 80}")
    
    start_p1 = time.time()
    resolved_stalemates = process_batch(
        stalemates, stalemate_path, audit_stalemate_item,
        batch_size=8, max_workers=4
    )
    p1_elapsed = time.time() - start_p1
    
    # --- Phase 2: INCORRECT Deep Dive ---
    incorrect_path = out_dir / 'resolved_incorrect.jsonl'
    
    p(f"\n{'=' * 80}")
    p(f"PHASE 2: INCORRECT DEEP DIVE ({len(incorrects)} items)")
    p(f"{'=' * 80}")
    
    start_p2 = time.time()
    resolved_incorrects = process_batch(
        incorrects, incorrect_path, audit_incorrect_item,
        batch_size=4, max_workers=2  # Fewer workers for 2-call items
    )
    p2_elapsed = time.time() - start_p2
    
    # --- Generate Report ---
    p(f"\n{'=' * 80}")
    p(f"GENERATING REPORT")
    p(f"{'=' * 80}")
    
    # Count results from output files (handles resume case)
    stalemate_correct = 0
    stalemate_incorrect = 0
    stalemate_failed = 0
    
    if stalemate_path.exists():
        with open(stalemate_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if data.get('verdict') is True:
                        stalemate_correct += 1
                    elif data.get('verdict') is False:
                        stalemate_incorrect += 1
                    else:
                        stalemate_failed += 1
    
    incorrect_promoted = 0
    incorrect_confirmed = 0
    
    if incorrect_path.exists():
        with open(incorrect_path) as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    consensus = str(data.get('consensus', ''))
                    if 'PROMOTE' in consensus:
                        incorrect_promoted += 1
                    elif 'CONFIRMED' in consensus:
                        incorrect_confirmed += 1
    
    report = {
        'metadata': {
            'total_items': len(items),
            'stalemate_items': len(stalemates),
            'incorrect_items': len(incorrects),
            'processed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
        'stalemate_recovery': {
            'promoted_to_correct': stalemate_correct,
            'confirmed_incorrect': stalemate_incorrect,
            'api_failed': stalemate_failed,
            'recovery_rate': f"{100*stalemate_correct/len(stalemates) if stalemates else 0:.1f}%",
            'elapsed_seconds': round(p1_elapsed, 1),
        },
        'incorrect_deep_dive': {
            'promoted_to_correct': incorrect_promoted,
            'confirmed_incorrect': incorrect_confirmed,
            'recovery_rate': f"{100*incorrect_promoted/len(incorrects) if incorrects else 0:.1f}%",
            'elapsed_seconds': round(p2_elapsed, 1),
        },
        'summary': {
            'total_resolved': stalemate_correct + incorrect_promoted,
            'total_confirmed': stalemate_incorrect + incorrect_confirmed,
            'total_elapsed_seconds': round(p1_elapsed + p2_elapsed, 1),
        }
    }
    
    report_path = Path('/workspace/data/reports/multi_llm_audit_report.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    p(f"\n{'=' * 80}")
    p(f"AUDIT COMPLETE")
    p(f"{'=' * 80}")
    p(f"\nSTALEMATE Recovery ({round(p1_elapsed, 1)}s):")
    p(f"  Promoted to CORRECT: {stalemate_correct} ({report['stalemate_recovery']['recovery_rate']})")
    p(f"  Confirmed INCORRECT: {stalemate_incorrect}")
    p(f"  API failed: {stalemate_failed}")
    p(f"\nINCORRECT Deep Dive ({round(p2_elapsed, 1)}s):")
    p(f"  Promoted to CORRECT: {incorrect_promoted} ({report['incorrect_deep_dive']['recovery_rate']})")
    p(f"  Confirmed INCORRECT: {incorrect_confirmed}")
    p(f"\nTotal Impact:")
    p(f"  Templates resolved to CORRECT: {report['summary']['total_resolved']}")
    p(f"  Templates confirmed INCORRECT: {report['summary']['total_confirmed']}")
    p(f"  Total elapsed: {round(p1_elapsed + p2_elapsed, 1)}s ({round((p1_elapsed + p2_elapsed)/3600, 2)}h)")
    p(f"\nFiles saved:")
    p(f"  {stalemate_path}")
    p(f"  {incorrect_path}")
    p(f"  {report_path}")
    p(f"\n✅ Multi-LLM audit complete!")


if __name__ == '__main__':
    main()
