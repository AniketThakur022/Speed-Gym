"""
Batch Processor with Checkpoint System

Processes solve_along templates in batches with progress tracking
and resumable checkpoints.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

from .extractor import TextToMathExtractor, ExtractionResult
from .confidence import ConfidenceLevel


@dataclass
class BatchCheckpoint:
    """Checkpoint for batch processing."""
    batch_id: str
    processed_count: int
    total_count: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    rejected_count: int
    verified_match: int
    verified_mismatch: int
    last_updated: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "processed_count": self.processed_count,
            "total_count": self.total_count,
            "high_confidence_count": self.high_confidence_count,
            "medium_confidence_count": self.medium_confidence_count,
            "low_confidence_count": self.low_confidence_count,
            "rejected_count": self.rejected_count,
            "verified_match": self.verified_match,
            "verified_mismatch": self.verified_mismatch,
            "last_updated": self.last_updated,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BatchCheckpoint":
        return cls(
            batch_id=data.get("batch_id", ""),
            processed_count=data.get("processed_count", 0),
            total_count=data.get("total_count", 0),
            high_confidence_count=data.get("high_confidence_count", 0),
            medium_confidence_count=data.get("medium_confidence_count", 0),
            low_confidence_count=data.get("low_confidence_count", 0),
            rejected_count=data.get("rejected_count", 0),
            verified_match=data.get("verified_match", 0),
            verified_mismatch=data.get("verified_mismatch", 0),
            last_updated=data.get("last_updated", ""),
        )


class BatchProcessor:
    """
    Batch processor for solving math problems with checkpoint support.
    
    Usage:
        processor = BatchProcessor(
            checkpoint_dir="/workspace/data/checkpoints",
            output_dir="/workspace/data/audit_results"
        )
        
        # Process templates
        results = processor.process_templates(
            templates=template_list,
            batch_id="solve_along_batch_001"
        )
    """
    
    def __init__(
        self,
        checkpoint_dir: str = "/workspace/data/checkpoints",
        output_dir: str = "/workspace/data/audit_results",
        extractor: Optional[TextToMathExtractor] = None,
        batch_size: int = 50
    ):
        """
        Initialize batch processor.
        
        Args:
            checkpoint_dir: Directory for checkpoint files
            output_dir: Directory for output files
            extractor: TextToMathExtractor instance (creates default if None)
            batch_size: Number of items to process before saving checkpoint
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.output_dir = Path(output_dir)
        self.extractor = extractor or TextToMathExtractor()
        self.batch_size = batch_size
        
        # Create directories
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Ensure subdirectories exist
        (self.output_dir / "math_audit").mkdir(exist_ok=True)
        (self.output_dir / "llm_audit").mkdir(exist_ok=True)
    
    def _get_checkpoint_path(self, batch_id: str) -> Path:
        """Get checkpoint file path for a batch."""
        return self.checkpoint_dir / f"{batch_id}_checkpoint.json"
    
    def _get_output_path(self, batch_id: str, category: str) -> Path:
        """Get output file path for results."""
        return self.output_dir / category / f"{batch_id}_results.jsonl"
    
    def load_checkpoint(self, batch_id: str) -> Optional[BatchCheckpoint]:
        """Load existing checkpoint."""
        checkpoint_path = self._get_checkpoint_path(batch_id)
        
        if checkpoint_path.exists():
            with open(checkpoint_path, 'r') as f:
                data = json.load(f)
            return BatchCheckpoint.from_dict(data)
        
        return None
    
    def save_checkpoint(self, checkpoint: BatchCheckpoint):
        """Save checkpoint to disk."""
        checkpoint_path = self._get_checkpoint_path(checkpoint.batch_id)
        checkpoint.last_updated = datetime.now().isoformat()
        
        with open(checkpoint_path, 'w') as f:
            json.dump(checkpoint.to_dict(), f, indent=2)
    
    def save_result(
        self,
        result: ExtractionResult,
        batch_id: str,
        category: str
    ):
        """Save a single result to output file."""
        output_path = self._get_output_path(batch_id, category)
        
        with open(output_path, 'a') as f:
            f.write(json.dumps(result.to_dict()) + '\n')
    
    def categorize_result(self, result: ExtractionResult) -> str:
        """
        Categorize result for routing.
        
        Returns:
            "math_audit" - High/medium confidence, computable
            "llm_audit" - Low confidence or rejected
        """
        if result.confidence is None:
            return "llm_audit"
        
        if result.confidence.level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM]:
            return "math_audit"
        else:
            return "llm_audit"
    
    def process_templates(
        self,
        templates: List[Dict[str, Any]],
        batch_id: str,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Process a batch of templates.
        
        Args:
            templates: List of template dictionaries with 'problem_text' and 'final_answer'
            batch_id: Unique identifier for this batch
            progress_callback: Optional callback(current, total) for progress updates
            
        Returns:
            Summary statistics
        """
        # Load existing checkpoint
        checkpoint = self.load_checkpoint(batch_id)
        
        if checkpoint is None:
            checkpoint = BatchCheckpoint(
                batch_id=batch_id,
                processed_count=0,
                total_count=len(templates),
                high_confidence_count=0,
                medium_confidence_count=0,
                low_confidence_count=0,
                rejected_count=0,
                verified_match=0,
                verified_mismatch=0,
                last_updated=datetime.now().isoformat()
            )
        
        # Resume from checkpoint
        start_index = checkpoint.processed_count
        
        print(f"Processing batch {batch_id}")
        print(f"Total templates: {checkpoint.total_count}")
        print(f"Resuming from: {start_index}")
        
        # Process remaining templates
        for i, template in enumerate(templates[start_index:], start=start_index):
            # Extract problem info
            problem_text = template.get("question_text") or template.get("problem", "")
            final_answer = template.get("final_answer") or template.get("answer", "")
            template_id = template.get("template_id") or template.get("id", f"item_{i}")
            
            if not problem_text:
                checkpoint.processed_count += 1
                continue
            
            # Process
            result = self.extractor.process(
                text=problem_text,
                expected_answer=final_answer,
                template_id=template_id,
                metadata={
                    "batch_index": i,
                    "template_data": template
                }
            )
            
            # Categorize and save
            category = self.categorize_result(result)
            self.save_result(result, batch_id, category)
            
            # Update checkpoint stats
            checkpoint.processed_count += 1
            
            if result.confidence:
                if result.confidence.level == ConfidenceLevel.HIGH:
                    checkpoint.high_confidence_count += 1
                elif result.confidence.level == ConfidenceLevel.MEDIUM:
                    checkpoint.medium_confidence_count += 1
                elif result.confidence.level == ConfidenceLevel.LOW:
                    checkpoint.low_confidence_count += 1
                else:
                    checkpoint.rejected_count += 1
            
            if result.verification_status == "match":
                checkpoint.verified_match += 1
            elif result.verification_status == "mismatch":
                checkpoint.verified_mismatch += 1
            
            # Save checkpoint periodically
            if checkpoint.processed_count % self.batch_size == 0:
                self.save_checkpoint(checkpoint)
                print(f"  Checkpoint saved: {checkpoint.processed_count}/{checkpoint.total_count}")
            
            # Call progress callback
            if progress_callback:
                progress_callback(checkpoint.processed_count, checkpoint.total_count)
        
        # Final checkpoint save
        self.save_checkpoint(checkpoint)
        
        # Generate summary
        summary = {
            "batch_id": batch_id,
            "total_processed": checkpoint.processed_count,
            "high_confidence": checkpoint.high_confidence_count,
            "medium_confidence": checkpoint.medium_confidence_count,
            "low_confidence": checkpoint.low_confidence_count,
            "rejected": checkpoint.rejected_count,
            "verified_match": checkpoint.verified_match,
            "verified_mismatch": checkpoint.verified_mismatch,
            "math_audit_eligible": checkpoint.high_confidence_count + checkpoint.medium_confidence_count,
            "llm_audit_required": checkpoint.low_confidence_count + checkpoint.rejected_count,
        }
        
        # Save summary
        summary_path = self.output_dir / f"{batch_id}_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        return summary
    
    def get_results(
        self,
        batch_id: str,
        category: str
    ) -> List[Dict[str, Any]]:
        """
        Load results from a category.
        
        Args:
            batch_id: Batch identifier
            category: "math_audit" or "llm_audit"
            
        Returns:
            List of result dictionaries
        """
        output_path = self._get_output_path(batch_id, category)
        
        if not output_path.exists():
            return []
        
        results = []
        with open(output_path, 'r') as f:
            for line in f:
                if line.strip():
                    results.append(json.loads(line))
        
        return results
    
    def export_for_llm_audit(
        self,
        batch_id: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        Export rejected/low-confidence items for LLM audit.
        
        Args:
            batch_id: Batch identifier
            output_path: Optional custom output path
            
        Returns:
            Path to exported file
        """
        llm_results = self.get_results(batch_id, "llm_audit")
        
        if output_path is None:
            output_path = self.output_dir / "llm_audit" / f"{batch_id}_llm_input.jsonl"
        else:
            output_path = Path(output_path)
        
        with open(output_path, 'w') as f:
            for result in llm_results:
                # Export minimal fields needed for LLM
                export_data = {
                    "template_id": result.get("metadata", {}).get("template_id"),
                    "problem_text": result["original_text"],
                    "final_answer": result.get("expected_answer"),
                    "confidence_level": result.get("confidence", {}).get("level"),
                    "confidence_reason": result.get("confidence", {}).get("reason"),
                    "rejection_reason": result.get("confidence", {}).get("reason") if result.get("verification_status") == "rejected" else None,
                }
                f.write(json.dumps(export_data) + '\n')
        
        return str(output_path)


def load_solve_along_templates(template_paths: List[str]) -> List[Dict[str, Any]]:
    """
    Load solve_along templates from JSON files.
    
    Args:
        template_paths: List of paths to template JSON files
        
    Returns:
        List of template dictionaries with problem_text and final_answer
    """
    templates = []
    
    for path in template_paths:
        with open(path, 'r') as f:
            data = json.load(f)
        
        # Extract problems from solve_along_sequence
        sequence = data.get("solve_along_sequence", {})
        current_problem = sequence.get("current_problem", {})
        
        if current_problem:
            templates.append({
                "template_id": data.get("template_name", ""),
                "problem_text": current_problem.get("question_text", ""),
                "final_answer": sequence.get("final_answer", ""),
                "multiplicand": current_problem.get("multiplicand"),
                "multiplier": current_problem.get("multiplier"),
                "digits_n": current_problem.get("digits_n"),
                "source_file": path,
            })
    
    return templates
