# LaTeX render contract — measured against KaTeX

**Workstream:** Speed Gym RAG · **Date:** 2026-09-03
**Trigger:** backend approved **KaTeX** as the renderer. KaTeX is not yet implemented in the frontend (the recovered APK sources contain no math renderer at all), so the invocation style is still an open decision — and it should be made with these numbers in hand.
**Tool:** `factory/audit/katex_validate.js` (real KaTeX 0.18.5, not a heuristic) · raw data `data/factory/katex_report_v1_1.json`

## The finding: the recovered bank mixes three incompatible conventions in one field

Over the 823-template bank v1.1, **6,471 formulas** in `examples[].solution[].result`:

| Convention | Count | Share | Renders with… |
|---|---|---|---|
| Raw math-mode LaTeX (`5 \times 7 = 35`) | 2,809 | 43% | `renderToString` ✓ / auto-render ✗ (shows as plain text) |
| Whole string wrapped in `$…$` | 2,717 | 42% | `renderToString` ✗ / auto-render ✓ |
| Mixed prose + inline `$…$` (+ `✓`, embedded newlines) | 898 | 14% | neither, as a single call |
| Other genuine breakage | 47 | 1% | neither |

**No single render call handles the bank.** Whichever strategy the frontend picks, roughly half the content breaks — silently, as unrendered text rather than an error. 55.9% of all formulas contain a `$`.

## Genuine defects behind the residual 945 failures (14.6%)

These fail KaTeX even after stripping outer delimiters:

- **898 mixed prose+math** — e.g. `"Equation (1): $3 + 2(-2) = -1$ ✓"`. Prose in a math field; belongs in `description`.
- **44 newline-escape corruption** — a backslash-n followed by a letter, e.g. `"…= 2.5 m\nBC = shed height"`, which KaTeX reads as the undefined control sequence `\nBC`. A real data bug from JSON escaping, not a style choice.
- **30 `align*` / `align`** — KaTeX rejects these outside display mode; `aligned` or `gathered` is the fix.
- **~5 alignment/`&` errors** in array environments.

## Recommendation

1. **One convention for `result`: raw math-mode LaTeX, no `$` delimiters**, rendered with `katex.renderToString(tex, {throwOnError: false})`. Prose belongs in `description`, which is already a separate field in the frontend schema.
2. **Normalization pass over the recovered bank** before it ships: strip outer `$`; split mixed prose into `description`; `align*` → `aligned`; repair the 44 newline escapes. This rewrites stored content, so it wants an explicit go — it is not applied yet.
3. **Render defensively**: `throwOnError: false` so a bad formula degrades to visible source rather than blanking a step.

## What the factory already guarantees

Generated (T2) content was validated against the same KaTeX build: **328/328 formulas render, zero `$`, zero failures.** The auditor's stage 2 now enforces the rules KaTeX actually applies — `$` in a math field, `align*` outside display, backslash-n control-sequence corruption, unbalanced braces/environments — so new generation cannot drift into any of these classes. The rules were derived from the measured failures above, not guessed.
