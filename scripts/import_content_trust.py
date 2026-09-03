#!/usr/bin/env python3
"""Import the content factory's quarantine decisions into problem_health_scores.

The factory records per-template trust in its bank manifest, but the runtime
cannot read a build artifact at request time — and until this existed, the
serving path had no idea the factory had rejected anything. Tier-1 items were
served with a hardcoded trust of "trusted", so 11 templates the factory
quarantined for empty_solution / empty_problem_statement were reaching learners.

problem_health_scores (migration 20) is the canonical trust table, so the
decisions land there and the API reads one source.

Scope note: the factory's ratings describe the derived SolveAlong TEMPLATE, not
the underlying book problem. A quarantine for `empty_solution` means the
converted walkthrough is unusable — which is why those ids are excluded from
serving. It is deliberately NOT read as a verdict on the book's answer key.

Usage:
  python3 scripts/import_content_trust.py [--manifest PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "data" / "factory" / "solvealong_bank_v1_4.manifest.json"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://vmsg:vmsg@localhost:5432/vmsg")

# Reasons that make the ITEM ITSELF unservable, versus ones that only spoil the
# derived walkthrough. Both are quarantined, but the distinction is recorded so
# a later pass can rescue the salvageable ones rather than re-deriving it.
HARD_REASONS = {"empty_problem_statement", "no_valid_examples"}


def classify(reasons: list[str]) -> str:
    return "QUARANTINED_HARD" if any(r in HARD_REASONS for r in reasons) else "QUARANTINED_SOFT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text())
    quarantined: dict[str, list[str]] = manifest.get("quarantined") or {}
    trust_by_id: dict[str, str] = manifest.get("trust_by_id") or {}

    print(f"manifest: {args.manifest.name}")
    print(f"  quarantined: {len(quarantined)}   rated: {len(trust_by_id)}")

    rows = [
        (content_id, classify(reasons), sorted(set(reasons)))
        for content_id, reasons in sorted(quarantined.items())
    ]
    hard = sum(1 for _, level, _ in rows if level == "QUARANTINED_HARD")
    print(f"  -> QUARANTINED_HARD {hard}, QUARANTINED_SOFT {len(rows) - hard}")

    if args.dry_run:
        for content_id, level, reasons in rows[:10]:
            print(f"    {level}  {content_id}  {reasons}")
        print("  (dry run — nothing written)")
        return 0

    import psycopg

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for content_id, level, reasons in rows:
                cur.execute(
                    """INSERT INTO problem_health_scores (content_id, trust_level, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (content_id) DO UPDATE
                         SET trust_level = EXCLUDED.trust_level, updated_at = NOW()""",
                    (content_id, level),
                )
                cur.execute(
                    """INSERT INTO content_validation_log
                           (content_id, content_kind, gate, passed, details, verifier_version)
                       VALUES (%s, 'solvealong_template', 'trap_taxonomy', FALSE, %s, %s)""",
                    (
                        content_id,
                        json.dumps({"reasons": reasons, "bank": manifest.get("bank")}),
                        # verifier_version is VARCHAR(20); the full bank name lives
                        # in details so nothing is lost to the truncation.
                        str(manifest.get("bank", "unknown"))[:20],
                    ),
                )
        conn.commit()

    print(f"  wrote {len(rows)} quarantine decisions to problem_health_scores")
    return 0


if __name__ == "__main__":
    sys.exit(main())
