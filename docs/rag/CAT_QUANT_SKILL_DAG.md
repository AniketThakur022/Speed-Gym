# CAT quant skills — evidence-derived, and four things that need a decision

**Workstream:** Speed Gym RAG · **Date:** 2026-09-09
**Artifacts:** `factory/closure/create_cat_quant_skills.{cypher,params.json}` · `data/taxonomy/cat_quant_subject_aliases.json` · panel `data/factory/verdicts/` (18 agents, 0 errors)

The directive was "build the ~7 CAT quant skills with evidence-based REQUIRES edges, no invented pedagogy." Derived by one analyst per subject over **real sampled corpus questions**, then an adversarial reviewer per subject whose default was to strike. **33 edges proposed, 9 struck, 24 upheld.**

## Only 3 of the 9 subjects need a new node

Six map onto skills that already exist. Creating them as named would re-fragment the vocabulary the 2026-09-08 migration spent 48 merges consolidating.

| taxonomy subject | q | disposition |
|---|---|---|
| Number Systems | 612 | **CREATE** (see naming caveat) |
| Geometry and Mensuration | 422 | **CREATE** |
| Profit and Loss | 281 | **CREATE** |
| Time, Speed and Distance | 195 | alias → `Speed, Time, Distance` |
| Time and Work | 191 | alias → `Work and Time` |
| Interest | 192 | alias → `Simple and Compound Interest` |
| Progressions | 168 | alias → `Sequences and Series` |
| Ratio, Proportion and Variation | 140 | alias → `Ratios and Proportions` |
| Averages and Alligations | 40 | alias → `Averages` |

Two labels in the directive were wrong: "Ratio and Proportion 140" is the key `Ratio, Proportion and Variation`, and "Averages 40" is `Averages and Alligations` — plain `Averages` is 197 and already graph-backed. The 1,855 total was arithmetically right. Adding `Time, Speed and Distance` and `Time and Work`, both unbacked and larger than three subjects on the original list, takes coverage to **2,241 questions**.

## Verified before writing anything

- All 24 prerequisite names exist **verbatim** as `:Skill`. 0 name failures.
- The 24 edges introduce **0 new cycles**.

## Four escalations

**1. The live graph is not acyclic. It has 3 cycles today.**

```
Basic Operations → Number Bases → Basic Operations
Basic Operations → Divisibility Rules → Basic Operations
Basic Operations → Divisibility Rules → Modular Arithmetic → Basic Operations
```

A prerequisite graph with cycles has no valid ordering for the skills inside them. My CAT quant edges neither cause nor fix this. The structural re-derivation held back in `data/factory/skill_dag_structural_proposal_v2.json` removes exactly the arms that close all three: **288 edges, 0 cycles**, verified.

But the cycle-breaker keeps the higher-support arm, and on `Divisibility Rules ↔ Basic Operations` that means keeping `Basic Operations REQUIRES Divisibility Rules` — which reads backwards, since divisibility rules build *on* basic operations. So the repair is right that a cycle must be broken and may be wrong about which arm to drop. **That choice is a human call, not a support count.**

**2. `Ratio, Proportion and Variation` got 0 upheld edges, and the reason is a graph defect.** The three prerequisites its questions genuinely demand — Linear Equations, Quadratic Equations, Polynomials and Factoring — are all unreachable because the graph already contains `Linear Equations REQUIRES Ratios and Proportions`, so every one would close a cycle. The evidence is strong (`If 3x² + 3y² = 10xy, what is the ratio of x to y?` is unsolvable without solving `3t² − 10t + 3 = 0`). Either that existing edge is wrong, or this chapter's content sits *above* the node it is being mapped to. Left unresolved, the BKT model credits ratio mastery for what are really linear-equation failures.

**3. Four prerequisites are demanded by the evidence but blocked by the vocabulary** — each exists only as an unpromoted stub, so no edge could be proposed without inventing a name:
- **Factorials** — 7 of 14 Number Systems questions are `157!`-shaped; the `!` is the object of the question and no upheld edge supplies it.
- **Pythagorean Theorem** — the most-demanded fact in Geometry and Mensuration, present only as two *spelling variants* (`Pythagorean Theorem`, `Pythagoras' theorem`) that should themselves be merged.
- **Unit Conversion** — `18 months … compounded half-yearly` needs months→years and annual→per-period before any interest formula applies.
- **Profit and Loss** — needed by Averages and Alligations (4 of 14 questions recover a cost price from a selling price), and now created by this pass, so that edge becomes available once this lands.

**4. `Number Systems` is a defensible node under a questionable name.** It collides conceptually with `Number Bases` (base conversion, which the new node must exclude) and overlaps `NumberTheory`. Do **not** resolve it by merging into `NumberTheory`: that node is used as an upstream *foundation* (`Basic Operations REQUIRES NumberTheory`), so merging would put 612 advanced CAT questions upstream of Fractions and Decimals and close a hard cycle. Give the node a display label that names the exam chapter explicitly.

## What is deliberately not in the script

Re-pinning `:Problem.mastery_key` to split Arithmetic 296 / Algebra 200 / Basic Operations 103. That is the change that actually moves learner mastery, and it belongs in `scripts/migrate_skill_vocabulary.py`'s pinning path with its paired Postgres/JSONB migration — not a loose `SET` at the end of a Cypher file. **Run the whole thing with backend.**
