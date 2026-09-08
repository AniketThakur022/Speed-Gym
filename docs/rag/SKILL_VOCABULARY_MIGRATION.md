# :Skill vocabulary migration — applied 2026-09-08, and what RAG must do next

**Workstream:** backend · **Script:** `scripts/migrate_skill_vocabulary.py` (idempotent, `--dry-run`)
**Audit record:** `data/migrations/skill_vocabulary_applied_2026-09-08.json`
**Status:** graph + Postgres applied. **Closure shadow built but NOT promoted — that is the RAG decision below.**

## What changed

470 → **422** `:Skill` nodes: 24 case duplicates, 16 resolvable namespaced variants,
3 Basic Operations variants merged, 5 structural names deleted.

| Edge | before | after | why it moved |
|---|---|---|---|
| `PREREQUISITE_OF` | 2457 | **2439** | 13 dedup onto survivor + 5 structural deletions |
| `REQUIRES` | 262 | **255** | 7 collapsed onto pairs the survivor already had |
| `FRONTIER_OF` | 2678 | **2486** | dedup + self-loop removal; still **100% reciprocal** |
| `TEACHES` | 318 | **307** | dedup |
| `EXPLAINS` | 165 | **147** | dedup |
| `NEXT_TOPIC` / `MANIFESTS_AS` / `HAS_SKILL_LEVEL` | 82 / 16 / 1 | unchanged | — |

Verified against a pre-migration snapshot: the live edge set is the **exact image** of the old
set under the merge map — 0 edges missing, 0 unexpected. **0 problems newly orphaned.**

## The thing that would have silently reverted this

`factory/closure/live_load.py` is add-and-reconcile, not add-only:

1. it **prunes** every `REQUIRES` edge tagged `created_by:'skill_dag_builder_v1'` that
   `skill_requires_edges_v1.jsonl` no longer asserts — so re-pointed edges would be deleted;
2. it **`TRUNCATE`s `problem_requirements`** and reloads it from `problem_requirements_v1.jsonl` —
   so the Q-matrix re-point would be overwritten with pre-merge names;
3. it **refuses to promote** the closure unless the live result matches
   `prerequisite_closure_v1.jsonl` **exactly** — so after any merge it would fail forever.

The migration therefore rewrites all three artefacts in the same run:

| file | before | after |
|---|---|---|
| `data/factory/skill_requires_edges_v1.jsonl` | 262 | **255** |
| `data/factory/problem_requirements_v1.jsonl` | 2457 | **2439** |
| `data/factory/prerequisite_closure_v1.jsonl` | 1544 | **1441** |

`prerequisite_closure_v1.jsonl` is **recomputed** from the rewritten edges (same BFS, depth ≤ 5,
min-depth), not string-substituted. Two independent code paths agree on 1441: the projection from
live `REQUIRES`, and the regeneration from the edge file.

**Do not re-run `build_closure.py` from the old inputs** — it would resurrect the pre-merge names.

## Closure: shadow built, promotion is yours

Per `STRATEGY_A_CLOSURE_DESIGN.md` the migration wrote the shadow and stopped:

```
prerequisite_closure_test = 1441 rows   (prerequisite_closure still 1544)
diff vs production: +118 / −221 / 1 depth change
```

- **−221** are rows whose descendant or ancestor was a merged-away name
  (`… <- Multiplication tables`, `… <- Arithmetic: Basic Operations (+, -, ×, ÷)`, `… <- Number sense`).
- **+118** are the same relationships re-expressed under survivor names, plus genuinely new
  reachability where a merge joined two previously separate chains
  (e.g. `Basic Operations (+, -, ×, ÷) <- Divisibility Rules` via `NumberTheory:Divisibility Rules`).

To promote once you agree:

```bash
python3 scripts/migrate_skill_vocabulary.py --promote-closure
```

It writes `sync_manifest` rows (`dry_run` for the shadow, `production` on promote), same convention
as `live_load.py`.

## The part that affects mastery — read this before any future rename

Mastery was keyed on `:Skill.name` resolved at read time by an **alphabetical sort over a problem's
skill parents**. 746 of 766 servable problems have 2–7 parents, so the key was decided by a string
sort. Consequences measured on this very migration:

- 21 problems would have changed mastery key; only 17 were expressible as old-name → new-name.
- `Bird_Engineering_Math_sa_187` would have lost the key `'Angle and Side Relationships'` — a node
  **not renamed, not deleted, not in any duplicate group** — because a *sibling* was recased.
- `Bird_Engineering_Math_sa_45` would have jumped `'Fractions and Decimals'` → `'Decimals'`,
  a different skill.
- Two keys **split** rather than vanished, which a vanish/appear diff cannot detect at all.

So the migration **pins** the key first: `:Problem.mastery_key` is frozen for all 794 problems with a
skill parent, and `session.py` now reads `coalesce(p.mastery_key, <sorted pick>)`. All 21 movements
were absorbed; the served key is now stable under any future vocabulary edit.

**This makes future renames cheap and safe — but only if you maintain the pin.** Newly ingested
problems have no pin; re-run the migration (it is idempotent, and `coalesce` makes pinning a no-op
for anything already pinned) after any factory run that adds `:Problem` nodes.

Without the pin the exposure is not small: renaming `Basic Operations (+, -, ×, ÷)` to a
string that sorts earlier would capture **183 problems it does not currently key — 36% of the
servable pool — in a single edit**.

## Stubs: deliberately not fixed

374 of 470 skills were `is_stub` with no topic/sub_topic, and **all of them carry problem edges**.
Deleting them changes 119 of 766 mastery keys, strands 45 problems with no skill parent, and
collapses the key vocabulary from 116 to 28. Only the provable subset was repaired: a stub named
`<root topic><sep><name of an existing :Skill>` is a namespacing artifact (18 of 20 such stubs
resolved; every prefix was one of the 9 `is_root` topics).

**~356 stubs remain.** They are not duplicates — they are real names missing metadata. Backfilling
`topic`/`sub_topic` for them needs taxonomy input, not a graph operation. That is the open item.

## Corrections to the brief this work was scoped from

- **"63 questions nearly mapped onto Chapter 11"** — real but historical, and not a graph fact.
  63 corpus questions in `Schaum :: Chapter 33` collided because `norm()` mapped both
  `"Chapter 33"` and `"Chapter 11"` to `""`. Already fixed at `factory/taxonomy/build_v1_1.py:112`.
  The live `Chapter 11` node had exactly **1** problem edge.
- **Structural names were 5, not 1.** `session.py`'s regex only matches whole strings, so it missed
  `Chapter 11 on simple equations`, `Chapter on Cubing Numbers`, `Advance Level` and
  `Previous sutras (referencing crosswise subtraction)` — and **two of those were winning the
  mastery key**. They are removed by explicit allowlist, because a regex loose enough to catch them
  also catches `Unit Circle` and `Unit Conversion`.
- **The survivor holds 40 `REQUIRES` edges (20 out + 20 in), not 34.** `promote_v1.py:73` understates it.
- **The 26 pending `sync_outbox` rows key on `'nikhilam'`, not on a live `:Skill.name`.** `'nikhilam'`
  has no `:Skill` node, so those rows **already fail their drain** and will keep failing — a
  pre-existing bug (`outbox.py:141`), unrelated to this migration. Do not use "outbox drains clean"
  as a post-migration pass criterion.
- **`verify_seed.py --db` was already failing** before this work: it expected `REQUIRES` = 294, but
  the `NEXT_TOPIC` retraction took it to 262 and the expectation was never updated. Now 255 and passing.
- **The API suite is 99 tests, not 74.**
