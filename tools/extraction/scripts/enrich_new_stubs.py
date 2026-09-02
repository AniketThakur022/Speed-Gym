#!/usr/bin/env python3
"""Enrich the 10 newly-created subtopic stubs."""
import asyncio
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE))

from topic_browser_full_package.scripts.enrichment_launcher import enrich_one

NEW_STUBS = [
    # Re-run failing / partial Vedic sutras after launcher fixes
    "anurupyena",              # structural fix: quick_example position
    "shunyam_saamyasamuccaye", # mode switch simple -> consensus
    "vilokanam",               # unwrap + flat-JSON instruction
    "yavadunam_tavadunam",     # complex cubing sutra
]


async def main():
    results = []
    for stub_id in NEW_STUBS:
        try:
            r = await enrich_one(stub_id, mode="auto")
            results.append((stub_id, r))
        except Exception as e:
            print(f"❌ {stub_id}: {e}")
            results.append((stub_id, None))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for stub_id, r in results:
        if r and r.get("metadata"):
            score = r["metadata"].get("completeness_score", 0)
            status = r["metadata"].get("content_status", "unknown")
            print(f"  {'✅' if score >= 0.6 else '⚠️'} {stub_id}: score={score}, status={status}")
        else:
            print(f"  ❌ {stub_id}: FAILED")


if __name__ == "__main__":
    asyncio.run(main())
