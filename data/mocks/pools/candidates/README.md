# Candidate mock-exam pools — NOT BOUND

Built by `tools/extraction/build_mock_pools.py` from `data/exports/vmsg_questions_v1.jsonl`
(the flattened question export), for the pool-independent mock engine in
`services/api/app/mocks/`.

**Nothing here is bound.** `StaticPoolSource` reads `data/mocks/pools/<tag>.json`;
these sit one directory deeper on purpose. Binding is the owner's serving-path
decision — when it lands, wiring a pool is a move:

```bash
mv data/mocks/pools/candidates/cat_dilr.json data/mocks/pools/cat_dilr.json
```

**Except `quant`.** `source_for()` in `sources.py` hardcodes
`if tag == "quant": return GraphSource()`, so a `quant.json` placed in the pools
directory is **silently ignored** — no error, the graph just keeps serving. Binding
the corpus quant pool needs a code change there (or a `set_source_override("quant",
StaticPoolSource("quant"))`), not a file move. Worth knowing before anyone concludes
the file "did not work".

Each `<tag>.json` is the contract payload. Each `<tag>.provenance.json` is the audit
trail for the same items (book, chapter, set_id, pdf_pages, the raw answer key, and
how that key was resolved) and is **not** part of the contract — do not bind it.

## What can actually be served

| Exam | Section | Pool | Needs | Has | Distinct exams |
|---|---|---|---|---|---|
| CAT | VARC | `cat_varc` | 24 | **0** | **cannot fill** |
| CAT | DILR | `cat_dilr` | 20 | 1,138 | 56 |
| CAT | QA | `quant` | 22 | 4,015 | 182 |
| GMAT | Quant | `quant` | 21 | 4,015 | 191 |
| GMAT | Verbal | `gmat_verbal` | 23 | **30** | **1** |
| GMAT | Data Insights | `gmat_di` | 20 | 100 | 5 |
| GRE | Verbal | `gre_verbal` | 27 | 275 | 10 |
| GRE | Quant | `quant` | 27 | 4,015 | 148 |
| GRE | AWA | `gre_awa` | 1 | 139 | 139 |

**GRE is the only exam servable end-to-end (10 distinct mocks). GMAT can run
exactly one. CAT cannot run at all** — a mock is only as deep as its thinnest section.

- **`cat_varc` is empty, deliberately.** No CAT verbal source is inside the 25-book
  corpus scope (the VARC book is staged, not merged — a scope decision on record).
  GRE and GMAT verbal were **not** substituted: a CAT aspirant meeting GRE sentence
  equivalence in a CAT mock is worse than an honest 503, which is what the engine
  already returns for an unbound tag.
- **`gmat_verbal` is one exam deep** — 30 items against a 23-question section, and
  skewed to Critical Reasoning. Needs the Manhattan GMAT Verbal RC chapters re-extracted.

## Do not bind these yet — four blockers this build cannot fix

An adversarial audit (2026-09-06) returned **FAIL: no pool safe to bind as-is**. Every
defect it found *inside* the emitted rows has been fixed and re-verified (see below).
These four are structural and need a decision or a change outside this builder:

1. **`cat_dilr` must not be bound as a timed section yet.** 1,120 of its 1,138 items
   belong to multi-question sets, but `StaticPoolSource._ramp()` picks items
   independently, so a 20-question DILR section becomes up to 20 *separate* puzzles in
   40 minutes. Real CAT DILR is 4 sets × 5 questions — you pay the setup cost once and
   amortise it. Served item-wise the section is not completable by anyone, and
   `weak_areas` would report the learner as weak at everything. Every item now carries a
   `set_id` (an extra key the engine passes through untouched) so a set-aware `fetch`
   can group them; that fetch is a backend change.
2. **`gre_verbal` cannot serve two of the GRE's three verbal formats.** `Section('verbal',
   kinds=('mcq',))` admits single-answer MCQ only, so Sentence Equivalence (select-two)
   and multi-blank Text Completion are excluded — on the real shorter GRE those are
   roughly 12 of 27 verbal questions. Serving this as an exam-faithful verbal section
   needs a `multi_select` kind and set-comparison in `grade()`.
3. **`quant` is 81% four-option but is bound to GRE and GMAT, which are always
   five-option** (2,434 four-option vs 579 five-option). The guessing baseline is 25%
   against the 20% the linear scaled scoring assumes. Exam-faithful GRE/GMAT quant needs
   per-exam pool tags, not one shared `quant`.
4. **`gmat_di` is CAT data interpretation relabelled.** All 100 items also appear in
   `cat_dilr`; none is Data Sufficiency, Two-Part Analysis or Multi-Source Reasoning —
   the formats that actually define GMAT Data Insights. The corpus cannot supply them.
   Treat as approximate practice, not a GMAT DI section.

## The answer convention (the part that must not be got wrong)

`scoring.py::grade()` compares the learner's answer to `correct_answer`, and separately
maps options to letters **by position** (`chr(ord('a') + i)`). So:

- `mcq` → `correct_answer` is the lowercase option **letter**, and `options` are
  re-emitted with their printed tags stripped so that **letter == index**. This grades
  correctly whether the client submits the letter or the option text.
- `tita` / `numeric` → `correct_answer` is a bare number, verified to survive
  `extract_numeric_answer()`. Negative answers are normalised from the corpus's
  Unicode MINUS SIGN (U+2212) to an ASCII hyphen, because `extract_numeric_answer`
  cannot parse U+2212 — a learner typing `-50` would have been string-compared against
  `−50` and **marked wrong while correct**. Note that self-grading cannot detect this
  class of bug: with both sides equally unparseable the string compare succeeds against
  itself. **Suggested backend fix:** normalise U+2212 inside `extract_numeric_answer`
  as well, so no future pool or graph answer can reintroduce it from the other side.
- `essay` → `correct_answer` is `null`; the GRE AWA section is `auto_scored=False`.

Verified by loading every pool through the real `scoring.py`: **all 7,237 items grade
`True` against their own `correct_answer`**, a wrong answer grades `False`, and a blank
grades `None`. Note this proves internal consistency, not that the book's printed answer
was right — that is what the answer-provenance fields in the corpus are for.

## What is excluded, and why

- **Twin/duplicate-numbered rows** — excluded by contract (the export cannot tell which
  twin is the real question).
- **Chart-dependent questions** — the pool contract has no figure field, so a bar/pie/line
  chart item would reach the learner unanswerable. Prose and **table** stimuli are kept:
  a table is re-rendered as text, which is faithful (the learner reads the same numbers the
  book prints), whereas describing a chart in words changes the task.
- **Unresolvable answer keys** — any key that cannot be resolved to exactly one option is
  dropped rather than guessed. This includes Sentence Equivalence items mis-typed as
  single-answer (`'Patronizing, condescending'` names two), derivation remnants
  (`'→ 0, 2, 4, 6, 8'`), and bare ordinals against number-tagged options (`'2'` against
  `'1) 2'` — the ordinal and an option's value collide).
- **Unusable option lists** — empty options, two identical options
  (`['Point','Point','Point','Point']`), punctuation debris. These pass the export's
  `playable` verdict, which tests that an option list *exists*, not that it is coherent.
- **Text completion and multi-select** — no section's `kinds` admits them. They are also
  not safely convertible to `mcq`: the apparently single-blank ones turn out to be
  multi-blank items whose later blanks' options were never captured.
- **Disputed option lists** — where an independent vision read disagreed with the stored
  options.

- **Out-of-syllabus chapters** — calculus, trigonometry and higher-algebra topics that
  no exam in scope tests.
- **Bird ("Basic Engineering Mathematics") entirely.** Not an exam-prep source, and its
  notation does not survive OCR: 1.3³ is served as `Evaluate 1.33` but keyed `2.197`, so
  a learner who reads the stem correctly is marked **wrong**. That is worse than an
  unanswerable question.
- **Items naming a figure whose data is not in the text**, reading-comprehension stems
  with no passage, stimuli truncated before their constraints end, passages replaced by a
  "printed on PDF page" pointer, and sets whose page numbers jump (evidence the questions
  came from a different exercise than the stimulus).
- **MCQs with fewer than four options**, and question types retired from their exam
  (GMAT Sentence Correction; GRE "Analyze an Argument", diverted to
  `gre_awa_argument_retired.json`).

Every exclusion is counted per pool under `dropped` in `MANIFEST.json`.

## Known weaknesses

- **Difficulty is mostly absent** (0% on the CAT/GMAT/GRE-verbal pools, 51% on `quant`).
  `_ramp()` treats a missing difficulty as easy (1), so its 30% easy → 70% hard curve is
  largely inert. Exams will be correctly scored but not correctly *paced*.
- **`skill` is a display grouping, not a mastery join.** `scoring.py` uses it only to
  group the per-skill accuracy breakdown of a finished mock (defaulting to
  `"unclassified"`). These pools emit the corpus taxonomy's `skill_key`, while
  `GraphSource` emits graph `:Skill` names — so a CAT learner's QA breakdown could use
  graph vocabulary while their DILR breakdown uses corpus vocabulary. Cosmetic, but it
  will look inconsistent in one result. Do **not** wire this field to BKT: only 2,594 of
  the 5,389 resolved playable rows are `bkt_joinable`, and that is the flag mastery must
  gate on.
- **`skill` is absent on `cat_dilr`, `gmat_di` and `gmat_verbal`** — Sinha and Arun Sharma
  carry no chapter metadata, so nothing resolves against the taxonomy. Per-skill mock
  analytics will be blank for CAT DILR.
- `quant` is offered to CAT, GMAT and GRE quant sections alike. It mixes sources from all
  three; it is not calibrated per exam.
