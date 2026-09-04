#!/usr/bin/env python3
"""Stage-7 verdict intake — session-panel backend, capped at SANDBOX.

Contract: docs/rag/STAGE7_SESSION_PANEL_INTAKE.md.

The cap is enforced HERE rather than trusted to the caller: a verdict from a
deviating judge backend can move an item QUARANTINED -> SANDBOX and no further,
because SANDBOX never feeds BKT mastery or mock exams. A same-base-model panel
has correlated blind spots, so being wrong must stay cheap.

Validation is adversarial toward the verdict file itself — a verdict that merely
*claims* a result is not trusted; the result is recomputed from the panel votes.

  python3 -m factory.audit.jester_intake data/factory/verdicts/stage7_*.jsonl
"""

import argparse
import glob
import json
from collections import Counter
from pathlib import Path

MAX_PROMOTION = "sandbox"          # hard ceiling for any non-configured backend
CONFIGURED_TRIO = {"glm-5.1", "kimi-k2.6", "deepseek-v4-flash"}
LADDER_STATE = Path("data/factory/state/trust_ladder.json")


def validate(v: dict) -> list[str]:
    """Returns a list of problems; empty means the verdict is admissible."""
    errs = []
    # "item" is the coordinator's word for a single bank template — the same thing my
    # spec calls "template". Aliased explicitly rather than by loosening the check,
    # so an genuinely unknown kind is still rejected.
    if v.get("target_kind") not in ("pattern", "template", "item"):
        errs.append("target_kind must be 'pattern', 'template' or 'item'")
    if not v.get("target_id"):
        errs.append("missing target_id")
    backend = v.get("judge_backend")
    if not backend:
        errs.append("missing judge_backend — provenance is what makes re-judge mechanical")
    panel = v.get("panel") or []
    lenses = [p.get("lens") for p in panel if isinstance(p, dict)]
    if len(panel) < 3:
        errs.append(f"panel has {len(panel)} members; at least 3 required")
    if len(set(lenses)) != len(lenses):
        errs.append("duplicate lenses — redundant lenses are not a panel")
    if any(not l for l in lenses):
        errs.append("every panel member needs a named lens")
    votes = Counter(p.get("verdict") for p in panel if isinstance(p, dict))
    if set(votes) - {"pass", "fail"}:
        errs.append(f"panel verdicts must be pass/fail, saw {sorted(set(votes))}")
    # Recompute rather than trust the stated result.
    rule = v.get("consensus_rule", "2_of_3")
    need = int(rule.split("_")[0]) if rule[:1].isdigit() else 2
    computed = "pass" if votes.get("pass", 0) >= need else "fail"
    if v.get("result") != computed:
        errs.append(f"stated result {v.get('result')!r} does not follow from votes "
                    f"{dict(votes)} under {rule} (computed {computed!r})")
    if v.get("target_kind") == "pattern" and not (v.get("spot_check_ids") or []):
        errs.append("pattern-level verdicts require spot_check_ids to detect drift")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("verdicts", nargs="+", help="verdict JSONL files (globs ok)")
    ap.add_argument("--apply", action="store_true",
                    help="write the ladder state (default is a dry run)")
    ap.add_argument("--stale", nargs="*", default=[],
                    help="substrings of target_ids whose SKELETON changed after judging; "
                         "their verdicts describe content that no longer exists and are "
                         "held for re-judge instead of promoted")
    ap.add_argument("--resolves-held", action="store_true",
                    help="assert every target_id is ALREADY in the ladder. Use when a "
                         "batch claims to resolve held targets: a re-slugged id (hyphens "
                         "for underscores) would otherwise create NEW targets and leave "
                         "the held ones held forever, silently.")
    ap.add_argument("--fingerprints", default=None,
                    help="JSON map target_id -> current skeleton fingerprint, recorded so "
                         "future staleness is detected automatically rather than by hand")
    args = ap.parse_args()

    fps = json.loads(Path(args.fingerprints).read_text()) if args.fingerprints else {}

    paths = [p for pat in args.verdicts for p in sorted(glob.glob(pat))]
    if not paths:
        print("no verdict files matched")
        return 1

    state = json.loads(LADDER_STATE.read_text()) if LADDER_STATE.exists() else {"targets": {}}
    stats = Counter()
    rejected, promoted = [], []

    for path in paths:
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            v = json.loads(line)
            stats["verdicts_seen"] += 1
            errs = validate(v)
            if args.resolves_held and v.get("target_id") not in state["targets"]:
                errs.append(f"target_id {v.get('target_id')!r} is not already in the ladder; "
                            "a batch resolving held targets must match existing ids exactly "
                            "(check underscore/hyphen slugging)")
            if errs:
                stats["rejected_invalid"] += 1
                rejected.append({"target_id": v.get("target_id"), "reasons": errs,
                                 "file": path})
                continue
            backend = v["judge_backend"]
            interim = backend not in CONFIGURED_TRIO
            tid = v["target_id"]

            # A verdict is evidence about the skeleton it judged. If that skeleton has
            # since changed, the verdict is not evidence about anything currently
            # generated — neither a pass nor a fail may carry over.
            current_fp = fps.get(tid)
            stated_fp = v.get("skeleton_fingerprint")
            drifted = bool(stated_fp and current_fp and stated_fp != current_fp)
            if drifted or any(s and s in tid for s in args.stale):
                stats["held_stale_skeleton_changed"] += 1
                state["targets"][tid] = {
                    "state": "quarantined_pending_consensus",
                    "held_reason": "skeleton changed after this verdict was rendered; "
                                   "re-judge required",
                    "prior_verdict": v["result"], "judge_backend": backend,
                    "skeleton_fingerprint": current_fp,
                }
                continue
            if v["result"] == "fail":
                new_state = "quarantined"
                stats["quarantined_by_panel"] += 1
            else:
                # The ceiling: a deviating backend cannot reach trusted/live.
                new_state = MAX_PROMOTION if interim else "trusted"
                stats[f"promoted_to_{new_state}"] += 1
            entry = {
                "state": new_state, "judge_backend": backend,
                "stage7_interim": interim,
                "target_kind": v["target_kind"],
                "panel_lenses": [p["lens"] for p in v["panel"]],
                "judged_at": v.get("judged_at"),
                "spot_check_ids": v.get("spot_check_ids") or [],
                "requires_rejudge_by": "configured_trio" if interim else None,
            }
            state["targets"][v["target_id"]] = entry
            promoted.append({"target_id": v["target_id"], "state": new_state,
                             "interim": interim})

    state["ceiling_note"] = (
        "Any judge_backend outside the configured trio is capped at "
        f"'{MAX_PROMOTION}' — it never feeds BKT mastery or mock exams. "
        "See docs/rag/STAGE7_SESSION_PANEL_INTAKE.md.")
    state["configured_trio"] = sorted(CONFIGURED_TRIO)

    print(json.dumps({"files": len(paths), "stats": dict(stats),
                      "rejected": rejected[:10],
                      "rejected_total": len(rejected)}, indent=1))
    if args.apply:
        LADDER_STATE.parent.mkdir(parents=True, exist_ok=True)
        LADDER_STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        print(f"ladder state written: {LADDER_STATE} ({len(state['targets'])} targets)")
    else:
        print("DRY RUN — pass --apply to write the ladder state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
