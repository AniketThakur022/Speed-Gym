#!/usr/bin/env python3
"""
Regenerate content fields for L1-L2 templates to match their concept names.

Usage:
    .venv/bin/python scripts/regenerate_template_content.py [--limit N]
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))
load_dotenv(WORKSPACE / ".env")

TPL_DIR = Path(__file__).resolve().parent.parent / "content_data" / "templates" / "explainer"
OLLAMA_URL = "https://ollama.com/v1/chat/completions"
OLLAMA_KEYS = [os.getenv(f"OLLAMA_CLOUD_API_KEY_{i}") for i in range(1, 9)]
OLLAMA_KEYS = [k for k in OLLAMA_KEYS if k]


def build_prompt(concept: str, subtopic: str, difficulty: int) -> str:
    level = "L1 (beginner)" if difficulty == 1 else "L2 (early intermediate)"
    return f"""Create educational content for a math explainer template.

Subtopic: {subtopic}
Concept: {concept}
Difficulty: {level}

Return ONLY a JSON object with these exact keys:
{{
  "definition_formal": "A clear, concise formal definition of '{concept}' in the context of {subtopic}.",
  "key_points": ["key point 1", "key point 2", "key point 3"],
  "how_to_solve": "Step-by-step explanation of how to apply or understand '{concept}' for {level} learners.",
  "how_it_helps": "Why learning this concept helps students.",
  "comparison_to_traditional": "How this approach compares to traditional school teaching."
}}

Output ONLY the JSON object. No markdown fences, no explanation. All math must be correct."""


async def regenerate_one(obj: dict, preferred_key: str) -> dict:
    concept = obj["concept"]["name"]
    subtopic = obj["concept"]["sub_topic"]
    difficulty = obj.get("difficulty", 1)
    prompt = build_prompt(concept, subtopic, difficulty)

    # Try preferred key first, then all other keys on 403/subscription error
    keys_to_try = [preferred_key] + [k for k in OLLAMA_KEYS if k != preferred_key]

    async with httpx.AsyncClient() as client:
        for key in keys_to_try:
            resp = await client.post(OLLAMA_URL, headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }, json={
                "model": "glm-5.1",
                "messages": [
                    {"role": "system", "content": "You are a math educator creating JSON content for a learning app. Output ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 2048,
                "temperature": 0.3,
            }, timeout=60)

            if resp.status_code == 200:
                break
            if resp.status_code == 403 and "subscription" in resp.text.lower():
                continue
            raise RuntimeError(f"API error {resp.status_code}: {resp.text[:200]}")
        else:
            raise RuntimeError(f"All keys failed (last: {resp.status_code}: {resp.text[:200]})")

    text = resp.json()["choices"][0]["message"].get("content", "")
    # Extract JSON
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
        text = text.replace("```json", "").replace("```", "").strip()

    new = json.loads(text)
    obj["definition"]["formal"] = new.get("definition_formal", obj["definition"].get("formal", ""))
    obj["key_points"] = new.get("key_points", obj.get("key_points", []))
    reasoning = obj.get("reasoning", {})
    reasoning["how_to_solve"] = new.get("how_to_solve", reasoning.get("how_to_solve", ""))
    reasoning["how_it_helps"] = new.get("how_it_helps", reasoning.get("how_it_helps", ""))
    reasoning["comparison_to_traditional"] = new.get("comparison_to_traditional", reasoning.get("comparison_to_traditional", ""))
    obj["reasoning"] = reasoning
    return obj


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    # Load all generated templates
    all_templates = []
    file_map = {}
    for p in TPL_DIR.iterdir():
        if p.suffix != ".jsonl":
            continue
        with p.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("template_id", "").startswith("L1L2_"):
                    all_templates.append((p, obj))

    if args.limit:
        all_templates = all_templates[:args.limit]

    print(f"Regenerating content for {len(all_templates)} L1-L2 templates...")

    semaphore = asyncio.Semaphore(len(OLLAMA_KEYS) * 2)

    async def process(item):
        p, obj = item
        key = OLLAMA_KEYS[hash(obj["template_id"]) % len(OLLAMA_KEYS)]
        async with semaphore:
            try:
                new_obj = await regenerate_one(obj, key)
                return p, new_obj, None
            except Exception as e:
                return p, obj, str(e)

    results = await asyncio.gather(*[process(item) for item in all_templates])

    # Write back per file
    file_lines = {}
    for p, obj, error in results:
        if error:
            print(f"  ❌ {obj['template_id']}: {error}")
        else:
            print(f"  ✅ {obj['template_id']}: {obj['concept']['name']}")
        if p not in file_lines:
            file_lines[p] = []
        file_lines[p].append(obj)

    for p, new_objs in file_lines.items():
        # Re-read original file and replace generated templates
        out_lines = []
        replaced = set(o["template_id"] for o in new_objs)
        with p.open() as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    out_lines.append(line.strip())
                    continue
                if obj.get("template_id") in replaced:
                    # find matching new obj
                    for no in new_objs:
                        if no["template_id"] == obj["template_id"]:
                            out_lines.append(json.dumps(no, ensure_ascii=False))
                            break
                else:
                    out_lines.append(line.strip())
        p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"💾 Updated {p.name}")


if __name__ == "__main__":
    asyncio.run(main())
