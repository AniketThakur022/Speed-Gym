#!/usr/bin/env python3
"""
Generate L1-L2 difficulty templates to fill the difficulty gap.

Usage:
    .venv/bin/python scripts/generate_l1l2_templates.py \
        --subtopic "Number Bases" --difficulty 1 --count 10
"""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))
load_dotenv(WORKSPACE / ".env")

TPL_DIR = Path(__file__).resolve().parent.parent / "content_data" / "templates" / "explainer"
OLLAMA_URL = "https://ollama.com/v1/chat/completions"
OLLAMA_KEYS = [os.getenv(f"OLLAMA_CLOUD_API_KEY_{i}") for i in range(1, 7)]
OLLAMA_KEYS = [k for k in OLLAMA_KEYS if k]


def load_examples(subtopic: str, max_examples: int = 3) -> list[dict]:
    """Load existing templates for the subtopic as style examples."""
    examples = []
    for p in TPL_DIR.iterdir():
        if p.suffix != ".jsonl":
            continue
        with p.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                st = obj.get("concept", {}).get("sub_topic") or obj.get("sub_topic")
                if st == subtopic:
                    examples.append(obj)
                    if len(examples) >= max_examples:
                        return examples
    return examples


def extract_topic_category(subtopic: str, examples: list[dict]) -> tuple[str, str]:
    """Infer topic and technique_name from examples."""
    if examples:
        concept = examples[0].get("concept", {})
        return concept.get("topic", "Maths"), concept.get("technique_name", subtopic)
    return "Maths", subtopic


def build_prompt(subtopic: str, topic: str, technique: str, difficulty: int, count: int, examples: list[dict]) -> str:
    diff_name = {1: "L1 (beginner, one-step, familiar numbers)", 2: "L2 (early intermediate, two-step, slight twist)"}[difficulty]
    example_json = json.dumps(examples[:2], indent=2, ensure_ascii=False) if examples else "No examples available."
    return f"""Generate {count} new math explainer templates for the subtopic "{subtopic}".

Topic: {topic}
Technique: {technique}
Difficulty: {diff_name}

These templates are for a math learning app. Follow the JSON schema of the examples below closely.
Each template must be a single JSON object on one line (JSONL format) with these fields:
- template_type: "explainer"
- template_id: unique ID like "L1L2_<subtopic_snake>_<number>"
- source: {{"book": "Generated", "page": 1, "chunk_idx": N, "source_reference": "Generated"}}
- concept: {{"name": "...", "topic": "{topic}", "sub_topic": "{subtopic}", "technique_name": "{technique}", "category": "explanation", "is_root_skill": false, "lock_threshold": "FLUID"}}
- ui_mode_mapping: {{"fluid": "quick_read", "fragile": "interactive_walkthrough", "fractured": "full_scaffold"}}
- difficulty: {difficulty}
- cognitive_load_score: {difficulty}
- prerequisite_chain: []
- definition: {{"formal": "concise explanation", "informal": "", "formula": []}}
- key_points: ["point 1", "point 2"]
- common_mistakes: []
- visual_description: ""
- real_world_application: ""
- related_concepts: []
- warnings: []
- tags: ["{subtopic.lower()}"]
- linked_diagrams: []
- linked_tables: []
- _enrichment_version: "c1_structural"
- _pending_reasoning: false
- _pending_visual: false
- _pending_realworld: true
- _generated_at: "{datetime.now(timezone.utc).isoformat()}"
- reasoning: {{"how_to_solve": "step-by-step solution", "how_it_helps": "why it matters", "comparison_to_traditional": "", "confidence": 0.9}}

Example templates:
{example_json}

Output ONLY {count} JSON objects, one per line, with NO markdown fences and NO commentary.
All mathematical content must be correct and appropriate for {diff_name} learners."""


def _snake(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


async def generate_templates(subtopic: str, difficulty: int, count: int) -> list[dict]:
    examples = load_examples(subtopic)
    topic, technique = extract_topic_category(subtopic, examples)
    prompt = build_prompt(subtopic, topic, technique, difficulty, count, examples)
    key = OLLAMA_KEYS[0]

    async with httpx.AsyncClient() as client:
        resp = await client.post(OLLAMA_URL, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }, json={
            "model": "glm-5.1",
            "messages": [
                {"role": "system", "content": (
                    "You are a JSON generator for a math learning app. "
                    "Output ONLY valid JSON objects, one per line. "
                    "Never include markdown fences or explanation text."
                )},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 8192,
            "temperature": 0.4,
        }, timeout=180)

    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:300]}")

    text = resp.json()["choices"][0]["message"].get("content", "")
    templates = []
    existing_ids = {e.get("template_id") for e in examples}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # Try stripping markdown fences
            line = re.sub(r"^```(?:json)?\s*", "", line)
            line = re.sub(r"\s*```$", "", line)
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                print(f"  ⚠ Skipping unparseable line: {line[:80]}")
                continue
        # Normalize
        obj["difficulty"] = difficulty
        obj["concept"]["sub_topic"] = subtopic
        obj["concept"]["topic"] = topic
        obj["concept"]["technique_name"] = technique
        # Ensure unique ID
        base_id = _snake(subtopic)
        n = len(existing_ids) + len(templates) + 1
        obj["template_id"] = f"L1L2_{base_id}_{n}"
        obj["source"] = {"book": "Generated", "page": 1, "chunk_idx": n, "source_reference": "Generated L1-L2 gap fill"}
        templates.append(obj)

    return templates


def append_templates(subtopic: str, templates: list[dict]):
    """Append generated templates to the first JSONL file that already contains the subtopic."""
    target_file = None
    for p in TPL_DIR.iterdir():
        if p.suffix != ".jsonl":
            continue
        with p.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                st = obj.get("concept", {}).get("sub_topic") or obj.get("sub_topic")
                if st == subtopic:
                    target_file = p
                    break
        if target_file:
            break

    if not target_file:
        # Create new file
        target_file = TPL_DIR / f"L1L2_gap_fill_{_snake(subtopic)}.jsonl"

    with target_file.open("a", encoding="utf-8") as f:
        for obj in templates:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    return target_file


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subtopic", required=True)
    parser.add_argument("--difficulty", type=int, choices=[1, 2], required=True)
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()

    print(f"Generating {args.count} L{args.difficulty} templates for '{args.subtopic}'...")
    templates = await generate_templates(args.subtopic, args.difficulty, args.count)
    target = append_templates(args.subtopic, templates)
    print(f"✅ Appended {len(templates)} templates to {target}")


if __name__ == "__main__":
    asyncio.run(main())
