# Reference Library — intake of the recovered pages

**Workstream:** Speed Gym RAG · **Date:** 2026-09-05
**Spec:** `incoming/Resources/6-19-26-full architect/architecture/topic_browser/REFERENCE_LIBRARY.md` (v2.0) · **Schema:** `subtopic_reference_schema.json` · **Loader:** `factory/reference/load_reference_pages.py`

## The pages were not lost

The block was carried as "25 of 28 per-technique pages unwritten." That was wrong. The June package holds **43 distinct subtopic reference pages**: 40 auto-generated ones in `content_data/subtopic_explainer_enriched/`, plus the **3 human-approved Phase-1A pages** (`nikhilam_sutra`, `urdhva_tiryak`, `yavadunam`) that exist only in the plain `subtopic_explainer/` directory. Backend's `topic_browser_subtopics` table was empty — the content existed and nothing served it. The block is therefore a validation-and-gate problem, not an authoring one.

## Validation — what held and what did not

| check | result |
|---|---|
| schema (required keys, quick_ref sub-keys) | **43/43 pass** |
| `formula_latex` renders in KaTeX 0.18.5 | 98/100 — the 2 failures are one page's `\text{working_base}` (bare underscore in text mode); notation, fixed on load |
| quick-example arithmetic, where machine-checkable | 14 correct, **2 wrong**, 27 not machine-checkable (word problems, dates) |
| thin pages (<3 mental steps or no traps) | 0 |
| `applicability_type` | free text — 28 spellings across 40 pages, one 37 chars long against a `varchar(32)` column |

### Two content defects — annotated, never edited

- **`ekanyunena_purvena`** teaches the wrong rule in its own headline example. It computes 42 × 99 as `41 | 57 = 4157` with right part "99 − 42 = 57". The sutra's right part is the complement of the left part from the base: 100 − 42 = 58 (equivalently 99 − 41), giving **4158**. This is a wrong *method* in a reference page for that method, in content self-declared "complete." Severity: blocking.
- **`seshanyakena_caramena`** gives "123 ÷ 8 → 3". The answer 3 is the *remainder*; either the problem should ask for it or the answer is wrong. The page also has no sutra name or translation. Severity: needs review.

A loader that quietly rewrote a page's mathematics would be committing exactly the fault the re-narration pass was faulted for. Both defects are recorded in `metadata_json.content_defects`, where they are visible in-data, drive the badge, and hold the page at `needs_human_review` until a person fixes it.

## `content_status` is recomputed, not trusted

All 43 pages self-declare `content_status: "complete"`. The spec's own rule (§8.2) says auto-generated content can never be complete. Applying it: **4 complete, 39 needs_human_review**. The declared value is preserved as `declared_content_status` so the discrepancy is auditable.

## Loaded

Upserted into `topic_browser_subtopics` with `techniques_by_difficulty` normalised to `level → [technique…]` (the source is inconsistent: one page uses a list per level, the rest a single object). The one over-width `applicability_type` — "Addition, Subtraction, Multiplication", a list of operations rather than a type — is remapped to the spec's `universal` and the original kept in metadata. Every other width is checked and reported rather than truncated.

## What is still open

- The two content defects need a human editor; the ekanyunena one is a one-line fix but it is a *fix to mathematics*, so it is not mine to make silently.
- `applicability_type` needs a controlled vocabulary; 28 spellings for 40 pages is a taxonomy problem, and it belongs with the taxonomy work.
- `gunaka_samuccayah` is a Vedic sutra with no sutra name on its page — the other 24 nameless pages are non-Vedic subtopics where the field legitimately does not apply.
- `yavadunam_tavadunam` duplicates the human-approved `yavadunam` page (same sutra). Retire or merge it; the join routes everything to the approved page.

## Templates joined to pages (`factory/reference/join_templates_to_pages.py`)

The junction `topic_browser_subtopic_templates` needed template ids the pages do not carry, so the join runs from the factory side. It is an **explicit alias table, not string similarity**: the first attempt was a token-overlap join and it filed the bank's 41 *Ekadhikena* Purvena templates (one MORE than the previous, squaring numbers ending in 5) under the *Ekanyunena* Purvena page (one LESS, the ×99 rule) because the two share "purvena" and "previous". A fuzzy join cannot be trusted with two sutras that differ by one syllable, so every mapping is written out and everything unmapped is declined with a reason.

| bank templates (v1.4) | 823 |
|---|---|
| joined, exact sub-topic match — **loaded** | 424 → 15 pages, tab = bank difficulty L1–L5 |
| topic-level candidates (e.g. "Triangles" → `geometry_basics`) — reported, **not loaded** | 170 |
| declined | 229 |

Declines, by reason: "Basic Operations" bucket needs a per-template operation split across four pages (63); no Calculus page (52); Ekadhikena has no page and is *not* Ekanyunena (41); no Statistics page (25); Paravartya Yojayet no page (18); Dhvajanka no page (18); the rest are singletons, including one bank template that is not mathematics at all (neuropsychology).

Generator patterns: `mult_near_base` and `nikhilam_complement` → `nikhilam_sutra`, `square_near_base` → `yavadunam`, `urdhva_2x2` → `urdhva_tiryak`; `mult_by_11` and `ekadhikena_square_5` have no page. Generated instances are run-stamped, so the generator side is recorded as pattern→page in the report rather than as junction rows; the junction gets generated rows when the factory's DB sink writes a promoted batch.

The biggest content gap the join exposes is the same one the bank has: **Ekadhikena Purvena has no reference page** despite 41 bank templates and a generator pattern. That is an authoring item, not a join item.
