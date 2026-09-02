# taxonomy_v1_candidate — RAG review

**Reviewer:** Speed Gym RAG (corpus→graph mapping lane) · **Date:** 2026-09-03
**Input:** `data/taxonomy/taxonomy_v1_candidate.json` (extraction commit 441c80e; 238 entries — 136 curated / 73 derived / 29 excluded; 344 label_mappings)
**Checked against:** the live Neo4j graph, `prerequisite_closure_v1`, `problem_requirements_v1` (the Q-matrix, now the BKT join spine), and `ontology_registry.yaml`
**Status: REVIEWED, NOT PROMOTED.** Promotion is held for owner acknowledgement per the coordinator's window, because some recommendations change user-visible topic names.

## Headline: the migration is almost certainly unnecessary

Backend's constraint assumed every merge/rename needs a mastery-key migration plus a closure rebuild. That was true *before* they resolved BKT keying onto the `(:Skill)-[:PREREQUISITE_OF]->(:Problem)` edges and made display labels display-only.

Given that change, **taxonomy_v1 should map display labels ONTO existing `:Skill.name` values rather than renaming skill nodes.** `:Skill.name` stays the stable machine key; the taxonomy supplies the human-facing label. With that shape:

- mastery keys are untouched → **no `user_technique_states` / `bkt_state_snapshots` migration**,
- the DAG is untouched → **no closure rebuild**,
- and the only thing needing owner sign-off is what learners *see*.

I recommend the candidate carry two explicit fields per entry: `skill_key` (existing `:Skill.name`, never rewritten by a display decision) and `display_label`. Renaming a `:Skill` node should be reserved for cases where the key itself is wrong, not merely ugly.

## Merge decisions

### Class A — corpus-only labels (no `:Skill` node, zero mastery/closure cost). APPROVED.

Verified: none of these exist as `:Skill` nodes, so merging them cannot affect mastery or the closure.

| Survivor | Absorbs | Note |
|---|---|---|
| **Logical Reasoning** (309) | Logic Reasoning (42), Logic and Reasoning, Logic Reasoning Problems | dominant form by an order of magnitude |
| **Competitive Reasoning** (13) | Competition Reasoning, Competitive Exam Reasoning | spelling variants |
| **Direction and Distance Reasoning** (16) | Direction and Distance | truncation variant |
| **Logic Puzzles** (19) | Logic Puzzle | singular/plural only |
| **Arithmetic Reasoning** | Arithmetical Reasoning (7) | close call — occurrences slightly favour "Arithmetical" (7 v 6); chose the standard form, and it is trivially reversible since neither is a graph key |

### Class B — REJECTED merges (the candidate points at these; do not take them)

- **Verbal Reasoning ↮ Non-Verbal Reasoning** — flagged NEGATION MISMATCH and the flag is correct. These are opposites; a 0.67 token overlap is an artefact of sharing the word "Reasoning". Merging would collapse a real distinction.
- **Verbal and Non-Verbal Reasoning**, **Verbal and Logical Reasoning** — compounds, not duplicates. They belong in `compound_needs_split`, not merged into either parent.
- **Number Theory / Arithmetic** — compound.
- **Logic Grid Puzzles** — a genuine *subtype* of Logic Puzzles, not a spelling of it. Keep separate.
- **Logic Puzzle Data**, **Logical Reasoning and Data Interpretation** family — the LRDI section name is a legitimate CAT section, distinct from Logical Reasoning as a skill. Merge the three LRDI spellings with each other; do not fold them into Logical Reasoning.

### Class C — display-label mappings onto existing skills (needs owner ack, but NO migration under the recommendation above)

| Corpus label | Existing `:Skill.name` | Footprint if the *key* were renamed |
|---|---|---|
| Vedic Mathematics (146) | `VedicMath` (root, non-stub) | 9 REQUIRES edges, 62 closure rows, 2 Q-matrix problems |
| Number Theory (8) | `NumberTheory` (root, non-stub) | 5 edges, 16 closure rows, **150 Q-matrix problems** |
| numerical cognition (15) | `Numerical cognition` (stub) | casing only — 0 closure impact |
| Spatial Reasoning (23) | `Spatial reasoning` (stub) | casing only — 0 closure impact |

These are the same concepts under machine-ish versus human-facing spellings. Map them; do not rename the keys.

## Findings the candidate did not carry

1. **A real 4-way variant cluster of one DAG hub.** `Basic Operations (+, -, ×, ÷)` (34 edges, 75 closure rows, **289 Q-matrix problems**) has three unmerged surface variants: `Arithmetic: Basic Operations (+, -, ×, ÷)` (3 edges, 43 closure rows, 13 problems), `Arithmetic:Basic Operations` (1 problem), `Arithmetic:Basic Operations (+, -, ×, ÷)` (2 problems). This is the single highest-value merge available and it splits a mastery hub four ways. **This one does touch keys** — merging it needs the Q-matrix re-point and a closure rebuild, so it is the one case where backend's full migration path genuinely applies.

2. **Exclusion reason #5 must not be applied to `:Skill` as a blanket rule.** "Difficulty bands masquerading as subjects" is real, but a regex over band words hits 292 closure rows and 371 Q-matrix rows, nearly all legitimate — `Basic Algebra`, `Basic Geometry`, `Basic Operations` are subjects, not bands. The genuine offenders are *bare* band names: `Advance Level` (1 Q-matrix row, 0 closure), `Basic Level` and `Intermediate Level` (0/0). Excise those three by exact match; leave "Basic <subject>" alone.

3. **13 `:Problem` nodes have no incoming `PREREQUISITE_OF` edge** (e.g. `Schaums_College_Math_sa_11/13/14/16/19`). Now that the Q-matrix is the BKT join spine, these are invisible to mastery forever — a learner can answer them and no skill updates. Worth an explicit backlog item rather than silent absence.

## Promotion plan (single operation, when acked)

1. Add `skill_key` + `display_label` to every entry; record Class A merges in `label_mappings` as `semantic_merge`, Class C as `display_alias` (explicitly **not** a rename).
2. Excise the three bare band names by exact match.
3. Apply the Class A + C mappings — no graph write, no migration, no closure rebuild.
4. **Separately**, as its own gated change: the `Basic Operations` 4-way merge — re-point the Q-matrix, rebuild the closure into the shadow table, diff, then promote. Mastery-key migration applies only here.
5. Re-run the closure shadow diff and record `stub_share` again afterwards.

## Open, not decided here

The remaining 46 long-tail and 7 compound entries need a splitting convention (how a compound like "Verbal and Logical Reasoning" maps to two skills) before they can be promoted. That convention is a taxonomy decision, not a merge decision, and I have not invented one unilaterally.
