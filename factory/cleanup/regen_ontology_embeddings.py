#!/usr/bin/env python3
"""Regenerate the zeroed ontology-registry embeddings (17 of 58 entries).

Key policy (owner, 2026-09-02): the ONLY key source is the owner-supplied .env
(OPENAI_API_KEY) — never a key found in recovered files. Without a key this
script reports what it WOULD do and exits 2.

Embeds `label + ': ' + description` (NFKC-normalized) with text-embedding-3-small
(1536-dim — the store's dimension), stdlib urllib only. Emits a patch file rather
than mutating the export:
  data/factory/ontology_registry_embeddings_patch_v1.jsonl  {id, label, embedding}

Apply at ingest (station 5) or via a one-off UPDATE against the Ledger.
Use --all to re-embed all 58 entries (e.g. after alias/description edits).
"""

import argparse
import json
import os
import unicodedata
import urllib.request
from pathlib import Path

MODEL = "text-embedding-3-small"
DIM = 1536


def load_env_key(env_path: Path) -> str | None:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def embed(texts: list[str], key: str) -> list[list[float]]:
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=json.dumps({"model": MODEL, "input": texts, "dimensions": DIM}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    return [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registry", default="incoming/topic_browser_full_package/db_exports/registry.jsonl")
    ap.add_argument("--env", default=".env")
    ap.add_argument("--out", default="data/factory/ontology_registry_embeddings_patch_v1.jsonl")
    ap.add_argument("--all", action="store_true", help="re-embed every entry, not just zeroed ones")
    args = ap.parse_args()

    entries = [json.loads(l) for l in Path(args.registry).read_text().splitlines()]
    targets = [e for e in entries
               if args.all or all(v == 0 for v in (e.get("embedding") or [0]))]
    print(f"registry entries: {len(entries)}; needing embedding: {len(targets)}")
    for e in targets:
        print(f"  - {e['label']} ({e['category']})")
    if not targets:
        return 0

    key = load_env_key(Path(args.env))
    if not key:
        print("\nNO KEY: set OPENAI_API_KEY in .env (owner-supplied only — key policy "
              "2026-09-02). Nothing embedded; exiting.")
        return 2

    texts = [unicodedata.normalize("NFKC", f"{e['label']}: {e.get('description') or ''}").strip()
             for e in targets]
    vectors = embed(texts, key)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for e, v in zip(targets, vectors):
            assert len(v) == DIM
            f.write(json.dumps({"id": e["id"], "label": e["label"], "embedding": v}) + "\n")
    print(f"wrote {len(targets)} embeddings -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
