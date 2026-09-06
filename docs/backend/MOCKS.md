# Mock exams (block 6)

Code: `services/api/app/mocks/` (blueprints, scoring, sources), router `mocks.py`,
migration `140_mocks.sql`; tests `test_mocks_scoring.py` (pure) and `test_mocks_api.py`.
Flag: `mock_exams` (on).

**Pool-independent by design.** The owner's serving-path decision (June 6-book
graph vs 25-book corpus vs both) is still parked, so the engine never knows which
pool a question came from. Each blueprint section names a *pool tag*; a tag is bound
to a `QuestionSource` in `sources.py`. Today: `quant` → the live graph with the
practice-loop guards (skill edge, verified question AND answer, not quarantined),
served as numeric questions; every other tag → `data/mocks/pools/<tag>.json` if it
exists. **An unbound pool is an honest 503 naming the tag**, never a mock padded with
the wrong subject. Binding the corpus later is a change in `sources.py` only.

## Blueprints — authored, because the graph has none

The live export has zero `:MockExam` / `:ExamBlueprint` / `:Section` nodes, so the
three blueprints and nine sections are code (`blueprints.py`), from the specs:

| Exam | Sections (questions / minutes) | Marking | Total |
| --- | --- | --- | --- |
| CAT | VARC 24/40 · DILR 20/40 · QA 22/40 | +3 correct, **−1 wrong MCQ** (= −1/3, MOCK-EXM-01), TITA no negative | raw, max 198, 120 min |
| GMAT Focus | Quant 21/45 · Verbal 23/45 · Data Insights 20/45 | no negative marking | section 60–90, total 205–805 (step 10) |
| GRE | Verbal 27/41 · Quant 27/47 · AWA 1 task/30 (recorded, not auto-scored) | no negative marking | 130–170 per measure |

GMAT/GRE scaled scores are **approximate linear scalings** (official concordances are
not in the specs and not public); every response labels them `scaled_approximate`.
Difficulty curve: linear ramp 30 % easy → 70 % hard, ascending within a section.

## Flow (`/api/v1/mocks`)

`GET /blueprints` (with per-section pool availability) → `POST /configure {exam, sections?, mode}`
(full = every section; sectional = a subset) → the questions are snapshotted with their
correct answers (never sent) → `POST /submit-answer` per question, server-timestamped →
`POST /submit` scores, computes percentile among completed attempts of the same
blueprint + section set (0 with no peers, not 50), weak areas (skills < 70 % accuracy,
skipped questions count against the skill), and `deferred_sinking_skills` for the
post-mock remediation deck → `GET /results/{id}` (answers revealed only after
completion) → `GET /history` (score trend). XP 75 per completed mock.

Timing: answers arriving after `started_at + limit + 60 s` are discarded and counted
in `late_answers_discarded`. Kids mode suppresses timers (nothing is late). An
offline-taken mock arrives as one bulk `/submit` with `answers[]` + `elapsed_seconds`;
the server cannot verify that timing, so it is accepted only within the limit and the
result is labelled `timing: client_reported`.

Rules the response declares for the client (user journey §11.2): ads disabled,
sinking skills deferred, phase transitions muted. Telemetry: `mock_exam_started`,
`mock_problem_attempt`, `mock_exam_submitted`, `deferred_workout_*` are psychometric
(never sampled). Damage-control (ML-predicted score) and the frequency curve are
client/DE concerns, not built here.

## Review fixes (blocks 5–9 adversarial pass, 2026-09-06)

- **Answers round-trip.** The graph source stored the correct answer with
  `"%g"`, which switches to 6-significant-digit exponential at 1e6 — so
  `99900024` became `"9.99e+07"`, which `extract_numeric_answer` cannot parse
  back, and grading fell through to a string compare that marked the CORRECT
  answer wrong. Two live problems even collapsed onto the same string. All
  persisted answers now use `content.format_answer` (plain decimal, never
  exponential). The duel path in `internal.py` had the identical defect and is
  fixed with it.
- **The whole trust ladder applies, not just quarantine.** The graph source read
  only `quarantined_ids`, so a stage-7 SANDBOX verdict had no effect here even
  though `content.servable_trust` and `session.py` both state that sandbox
  content "never feeds BKT or mock exams". `trust_levels` is now applied.
- **`/results` honours the late cutoff.** Review graded the stored row blind, so
  an answer the scorer discarded as late came back attempted-and-correct while
  the section counts in the same payload said unattempted. Rows now carry
  `counted` and `late`, and a discarded answer is never reported correct.
