#!/usr/bin/env python3
"""
Multi-LLM Audit Processor for Text-to-Math LLM Audit Items (Optimized)

Strategy:
- STALEMATE (616 items): Single model final-answer check → fast recovery
- INCORRECT (279 items): 2-model jury (kimi + deepseek) → deep validation

Features:
- Incremental save every batch
- Resume from where it left off
- Parallel API calls with ThreadPoolExecutor
- Real-time progress with ETA
- Flushed stdout for live logs

Usage:
    source /workspace/venv/bin/activate
    cd /workspace/assembly_line
    python3 /workspace/multi_llm_audit.py

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
from datetime import datetime, timedelta

from hybrid_validator_v3.l2_jury import query_model

MODELS = {
    'beta': 'qwen3-vl:235b-instruct',
    'gamma': 'deepseek-v3.1:671b',
    'kimi': 'ollama-cloud/kimi-k2.5',
    'deepseek_v4': 'deepseek-v4-pro:cloud',
}

OLLAMA_URL = "https://ollama.com/v1/chat/completions"

BATCH_SIZE = 10
MAX_WORKERS = 4


def p(msg):
    """Print with immediate flush."""
    print(msg)
    sys.stdout.flush()


def load_processed_ids(filepath):
    """Load set of already processed template IDs."""
    if not Path(filepath).exists():
        return set()
    processed = set()
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                processed.add(data['template_id'])
    return processed


def append_result(filepath, result):
    """Append single result to JSONL file (fsync for crash safety)."""
    with open(filepath, 'a') as f:
        f.write(json.dumps(result) + '\n')
        f.flush()
        os.fsync(f.fileno())


def save_checkpoint(phase, checkpoint_path, processed_count, total_items, start_time):
    """Write timing/metadata checkpoint."""
    elapsed = time.time() - start_time
    rate = processed_count / elapsed if elapsed > 0 else 0
    remaining = max(0, (total_items - processed_count) / rate) if rate > 0 else 0
    ckpt = {
        'phase': phase,
        'processed_count': processed_count,
        'total_items': total_items,
        'elapsed_seconds': round(elapsed, 1),
        'items_per_second': round(rate, 2),
        'eta_seconds': round(remaining, 1),
        'last_save': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with open(checkpoint_path, 'w') as f:
        json.dump(ckpt, f, indent=2)


def load_llm_audit_items():
    """Load items from text-to-math LLM audit output."""
    items = []
    path = Path('/workspace/data/audit_results/llm_audit/llm_audit_results.jsonl')
    if not path.exists():
        raise FileNotFoundError(f"LLM audit file not found: {path}")
    
    with open(path, 'r') as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line))
    return items


def build_stalemate_prompt(item):
    """Build focused prompt for STALEMATE recovery."""
    problem = item.get('problem_text', '')[:200]
    answer = item.get('final_answer', '')[:100]
    
    return f"""You are a math verification specialist. Your task is to check if the final answer in this template is mathematically correct.

Problem: {problem}
Expected Answer: {answer}

Check ONLY the final answer (not the solution steps). Return JSON:
{{
  "final_answer_correct": true/false,
  "correct_answer": "the exact correct answer if the template's answer is wrong",
  "confidence": 0.0-1.0,
  "explanation": "brief reason"
}}

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
{{
  "final_answer_correct": true/false,
  "correct_answer": "the exact correct answer if wrong",
  "step_logic_valid": true/false,
  "trap_detected": "description or null",
  "error_category": "MATH_ERROR|LOGIC_ERROR|NOTATION_ERROR|CORRECT",
  "reasoning_quality": 1-5,
  "confidence": 0.0-1.0,
  "explanation": "detailed reasoning"
}}

Respond with ONLY the JSON object, no markdown."""


def audit_stalemate_item(item):
    """Audit a single STALEMATE item with one model."""
    prompt = build_stalemate_prompt(item)
    
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
    
    gamma_result = query_model(prompt, MODELS['gamma'], max_tokens=800, timeout=60)
    beta_result = query_model(prompt, MODELS['beta'], max_tokens=800, timeout=60)
    
    results = {
        'template_id': item['template_id'],
        'original_status': 'INCORRECT',
        'verdicts': [],
    }
    
    if gamma_result and not gamma_result.get('_parse_error'):
        results['verdicts'].append({
            'model': 'gamma',
            'correct': gamma_result.get('final_answer_correct', False),
            'confidence': gamma_result.get('confidence', 0.0),
            'reasoning_quality': gamma_result.get('reasoning_quality', 0),
            'trap': gamma_result.get('trap_detected'),
        })
    
    if beta_result and not beta_result.get('_parse_error'):
        results['verdicts'].append({
            'model': 'beta',
            'correct': beta_result.get('final_answer_correct', False),
            'confidence': beta_result.get('confidence', 0.0),
            'reasoning_quality': beta_result.get('reasoning_quality', 0),
            'trap': beta_result.get('trap_detected'),
        })
    
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


def format_eta(seconds):
    """Format seconds into human-readable ETA."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m {int(seconds % 60)}s"
    else:
        return f"{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m"


def process_batch_parallel(items, audit_func, out_file, processed_ids, batch_num, total_batches):
    """Process a batch of items in parallel and save incrementally."""
    to_process = [item for item in items if item['template_id'] not in processed_ids]
    
    if not to_process:
        return []
    
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {executor.submit(audit_func, item): item for item in to_process}
        
        completed = 0
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                result = future.result()
                results.append(result)
                
                append_result(out_file, result)
                processed_ids.add(item['template_id'])
                
                completed += 1
                status = result.get('verdict') if 'verdict' in result else result.get('consensus')
                if status is True or 'PROMOTE' in str(status):
                    p(f"  ✅ {item['template_id'][:40]:40} → {status}")
                elif status is False or 'CONFIRMED' in str(status):
                    p(f"  ❌ {item['template_id'][:40]:40} → {status}")
                else:
                    p(f"  ⚠️  {item['template_id'][:40]:40} → {status}")
                    
            except Exception as e:
                p(f"  💥 {item['template_id'][:40]:40} → ERROR: {e}")
                error_result = {
                    'template_id': item['template_id'],
                    'error': str(e),
                }
                results.append(error_result)
                append_result(out_file, error_result)
                processed_ids.add(item['template_id'])
    
    return results


def main():
    p("=" * 80)
    p("MULTI-LLM AUDIT PROCESSOR (Optimized)")
    p("=" * 80)
    
    out_dir = Path('/workspace/data/audit_results/llm_audit')
    out_dir.mkdir(parents=True, exist_ok=True)
    
    stalemate_file = out_dir / 'resolved_stalemate.jsonl'
    incorrect_file = out_dir / 'resolved_incorrect.jsonl'
    
    p("\nLoading LLM audit items...")
    items = load_llm_audit_items()
    
    stalemates = [i for i in items if i['original_status'] == 'STALEMATE']
    incorrects = [i for i in items if i['original_status'] == 'INCORRECT']
    
    p(f"  Total: {len(items)}")
    p(f"  STALEMATE: {len(stalemates)}")
    p(f"  INCORRECT: {len(incorrects)}")
    
    stalemate_processed = load_processed_ids(stalemate_file)
    incorrect_processed = load_processed_ids(incorrect_file)
    
    p(f"\nResuming from previous runs:")
    p(f"  STALEMATE already processed: {len(stalemate_processed)}")
    p(f"  INCORRECT already processed: {len(incorrect_processed)}")
    
    p(f"\n{'=' * 80}")
    p(f"PHASE 1: STALEMATE RECOVERY")
    p(f"{'=' * 80}")
    p(f"Remaining: {len(stalemates) - len(stalemate_processed)}/{len(stalemates)}")
    
    start_time = time.time()
    stalemate_ckpt = stalemate_file.parent / (stalemate_file.name + '.checkpoint')
    total_stalemate = len([i for i in stalemates if i['template_id'] not in stalemate_processed])
    
    if total_stalemate > 0:
        num_batches = (total_stalemate + BATCH_SIZE - 1) // BATCH_SIZE
        
        for batch_num in range(num_batches):
            remaining_stalemates = [i for i in stalemates if i['template_id'] not in stalemate_processed]
            
            if not remaining_stalemates:
                break
                
            batch = remaining_stalemates[:BATCH_SIZE]
            p(f"\n  Batch {batch_num + 1}/{num_batches} - {len(batch)} items")
            
            batch_start = time.time()
            process_batch_parallel(batch, audit_stalemate_item, stalemate_file, stalemate_processed, batch_num + 1, num_batches)
            batch_time = time.time() - batch_start

            elapsed = time.time() - start_time
            rate = len(stalemate_processed) / elapsed if elapsed > 0 else 0
            eta = format_eta((total_stalemate - len(stalemate_processed)) / rate) if rate > 0 else "N/A"
            p(f"  Rate: {rate:.1f} items/min | ETA: {eta}")

            save_checkpoint('STALEMATE', stalemate_ckpt, len(stalemate_processed), len(stalemates), start_time)
    
    phase1_elapsed = time.time() - start_time
    p(f"\n  Phase 1 done: {len(stalemate_processed)} items in {phase1_elapsed:.0f}s")
    
    p(f"\n{'=' * 80}")
    p(f"PHASE 2: INCORRECT DEEP DIVE")
    p(f"{'=' * 80}")
    p(f"Remaining: {len(incorrects) - len(incorrect_processed)}/{len(incorrects)}")
    
    phase2_start = time.time()
    incorrect_ckpt = incorrect_file.parent / (incorrect_file.name + '.checkpoint')
    total_incorrect = len([i for i in incorrects if i['template_id'] not in incorrect_processed])
    
    if total_incorrect > 0:
        num_batches = (total_incorrect + BATCH_SIZE - 1) // BATCH_SIZE
        
        for batch_num in range(num_batches):
            remaining_incorrects = [i for i in incorrects if i['template_id'] not in incorrect_processed]
            
            if not remaining_incorrects:
                break
                
            batch = remaining_incorrects[:BATCH_SIZE]
            p(f"\n  Batch {batch_num + 1}/{num_batches} - {len(batch)} items")
            
            batch_start = time.time()
            process_batch_parallel(batch, audit_incorrect_item, incorrect_file, incorrect_processed, batch_num + 1, num_batches)
            batch_time = time.time() - batch_start

            elapsed = time.time() - phase2_start
            rate = len(incorrect_processed) / elapsed if elapsed > 0 else 0
            eta = format_eta((total_incorrect - len(incorrect_processed)) / rate) if rate > 0 else "N/A"
            p(f"  Rate: {rate:.1f} items/min | ETA: {eta}")

            save_checkpoint('INCORRECT', incorrect_ckpt, len(incorrect_processed), len(incorrects), phase2_start)
    
    phase2_elapsed = time.time() - phase2_start
    p(f"\n  Phase 2 done: {len(incorrect_processed)} items in {phase2_elapsed:.0f}s")
    
    p(f"\n{'=' * 80}")
    p(f"GENERATING FINAL REPORT")
    p(f"{'=' * 80}")
    
    resolved_stalemates = []
    with open(stalemate_file, 'r') as f:
        for line in f:
            if line.strip():
                resolved_stalemates.append(json.loads(line))
    
    resolved_incorrects = []
    with open(incorrect_file, 'r') as f:
        for line in f:
            if line.strip():
                resolved_incorrects.append(json.loads(line))
    
    stalemate_correct = sum(1 for r in resolved_stalemates if r.get('verdict') is True)
    stalemate_incorrect = sum(1 for r in resolved_stalemates if r.get('verdict') is False)
    stalemate_failed = len(resolved_stalemates) - stalemate_correct - stalemate_incorrect
    
    incorrect_promoted = sum(1 for r in resolved_incorrects if 'PROMOTE' in str(r.get('consensus', '')))
    incorrect_confirmed = sum(1 for r in resolved_incorrects if 'CONFIRMED' in str(r.get('consensus', '')))
    
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
        },
        'incorrect_deep_dive': {
            'promoted_to_correct': incorrect_promoted,
            'confirmed_incorrect': incorrect_confirmed,
            'recovery_rate': f"{100*incorrect_promoted/len(incorrects) if incorrects else 0:.1f}%",
        },
        'summary': {
            'total_resolved': stalemate_correct + incorrect_promoted,
            'total_confirmed': stalemate_incorrect + incorrect_confirmed,
        }
    }
    
    report_path = Path('/workspace/data/reports/multi_llm_audit_report.json')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    p(f"\n{'=' * 80}")
    p(f"AUDIT COMPLETE")
    p(f"{'=' * 80}")
    p(f"\nSTALEMATE Recovery:")
    p(f"  Promoted to CORRECT: {stalemate_correct} ({report['stalemate_recovery']['recovery_rate']})")
    p(f"  Confirmed INCORRECT: {stalemate_incorrect}")
    p(f"  API failed: {stalemate_failed}")
    p(f"\nINCORRECT Deep Dive:")
    p(f"  Promoted to CORRECT: {incorrect_promoted} ({report['incorrect_deep_dive']['recovery_rate']})")
    p(f"  Confirmed INCORRECT: {incorrect_confirmed}")
    p(f"\nTotal Impact:")
    p(f"  Templates resolved to CORRECT: {report['summary']['total_resolved']}")
    p(f"  Templates confirmed INCORRECT: {report['summary']['total_confirmed']}")
    p(f"\nFiles saved:")
    p(f"  {stalemate_file}")
    p(f"  {incorrect_file}")
    p(f"  {report_path}")
    p(f"\n✅ Multi-LLM audit complete!")


if __name__ == '__main__':
    main()