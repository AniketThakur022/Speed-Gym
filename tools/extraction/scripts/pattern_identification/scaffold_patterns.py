import os
from pathlib import Path

WORKSPACE_ROOT = Path(r"d:\focus 030925\yt_m\Vedic maths\webapp_brain")
PATTERN_DIR = WORKSPACE_ROOT / "pipeline" / "v3_0" / "patterns"

PATTERNS = [
    ("p02_option_extraction", "Extracts MCQ options and checks for roman numerals or composite answers.", "UNIVERSAL"),
    ("p03_answer_identification", "Identifies the correct answer and compares against options.", "UNIVERSAL"),
    ("p04_difficulty_scoring", "Scores difficulty from 1-5 based on trap presence and logic steps.", "UNIVERSAL"),
    ("p05_topic_classification", "Classifies text into canonical topics (e.g., CAT_Quant).", "UNIVERSAL"),
    ("p06_subtopic_enrichment", "Identifies sub-topics and prerequisite topics.", "UNIVERSAL"),
    ("p08_logic_steps", "Extracts step-by-step logical reasoning chains.", "QUANT, LR"),
    ("p10_worked_examples", "Extracts worked examples and alternative solution methods.", "UNIVERSAL"),
    ("p11_pedagogical_notes", "Extracts author notes, warnings, and concept clarifications.", "UNIVERSAL"),
    ("p12_cross_references", "Extracts references to other sections, theorems, or books.", "UNIVERSAL"),
    ("p13_bundle_type_detection", "Detects if bundle is PROBLEM_DENSE, INSTRUCTIONAL, or MIXED.", "UNIVERSAL"),
    ("p14_instructional_split", "Splits instructional content from practice problems.", "UNIVERSAL"),
    ("p15_answer_key_annotation", "Detects tabular answer keys at the end of chapters.", "UNIVERSAL"),
    ("p17_entity_recognition", "Extracts named entities like Sutras, Theorems, and People.", "UNIVERSAL"),
    ("p18_content_hashing", "Generates SHA-256 semantic hashes for deduplication.", "UNIVERSAL"),
    ("p19_provenance_tracking", "Tracks source book, page, and extraction pipeline version.", "UNIVERSAL"),
    ("p20_quality_scoring", "Assigns a final data quality score from 0.0 to 1.0.", "UNIVERSAL")
]

TEMPLATE = """import logging
from typing import Dict, Any, Tuple
from pipeline.v3_0.patterns.base import ExtractionPattern

log = logging.getLogger(__name__)

class {class_name}(ExtractionPattern):
    @property
    def name(self) -> str:
        return "{name}"

    @property
    def description(self) -> str:
        return "{description}"

    def applies_to(self, domain: str) -> bool:
        applicable_domains = [{domains}]
        return domain in applicable_domains or "UNIVERSAL" in applicable_domains

    async def extract(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement full LLM or heuristic extraction logic
        # For now, return a placeholder
        return {{"{mock_field}": "pending_implementation"}}

    def validate(self, extracted_data: Dict[str, Any]) -> Tuple[bool, str]:
        return True, "Valid"

    def score_confidence(self, extracted_data: Dict[str, Any]) -> float:
        return 0.5
"""

def snake_to_camel(name: str) -> str:
    parts = name.split('_')
    # p02_option_extraction -> P02OptionExtraction
    return parts[0].capitalize() + ''.join(word.capitalize() for word in parts[1:])

def main():
    PATTERN_DIR.mkdir(parents=True, exist_ok=True)
    for name, desc, domains in PATTERNS:
        class_name = snake_to_camel(name)
        file_path = PATTERN_DIR / f"{name}.py"
        
        domain_list = ", ".join(f'"{d.strip()}"' for d in domains.split(','))
        mock_field = name.split('_', 1)[1] if '_' in name else name
        
        content = TEMPLATE.format(
            class_name=class_name,
            name=name.upper(),
            description=desc,
            domains=domain_list,
            mock_field=mock_field
        )
        
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Created {file_path.name}")

if __name__ == "__main__":
    main()
