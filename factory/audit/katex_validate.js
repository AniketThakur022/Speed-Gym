#!/usr/bin/env node
/* Stage-2 ground truth: does the bank's LaTeX actually render in KaTeX?
 *
 * KaTeX is the approved renderer (backend, 2026-09-03), so "renders in KaTeX" is
 * the real acceptance test — the Python auditor's balance heuristic is only a
 * cheap proxy. Reads a bank JSONL and reports every formula KaTeX rejects.
 *
 *   node factory/audit/katex_validate.js <bank.jsonl> [--json out.json]
 */
const fs = require('fs');
const katex = require('katex');

const bankPath = process.argv[2];
const jsonIdx = process.argv.indexOf('--json');
if (!bankPath) { console.error('usage: katex_validate.js <bank.jsonl> [--json out.json]'); process.exit(2); }

function check(tex) {
  try {
    katex.renderToString(tex, { throwOnError: true, strict: false });
    return null;
  } catch (e) {
    return (e && e.message ? e.message : String(e)).replace(/\s+/g, ' ').slice(0, 160);
  }
}

// The bank mixes two conventions: some formulas are wrapped in $...$ (auto-render
// delimiters) and some are raw math-mode strings. EITHER render strategy breaks one
// subset, so classify instead of assuming which is "wrong".
function stripDelims(tex) {
  const t = tex.trim();
  const m = t.match(/^\$\$?([\s\S]*?)\$\$?$/);
  return m ? m[1] : null;
}

let templates = 0, formulas = 0, failures = [];
const failedTemplates = new Set();
const cls = { raw_ok: 0, dollar_wrapped_ok_after_strip: 0, fails_either_way: 0, mixed_inline_dollars: 0 };

for (const line of fs.readFileSync(bankPath, 'utf8').split('\n')) {
  if (!line.trim()) continue;
  const t = JSON.parse(line);
  templates++;
  (t.examples || []).forEach((ex, ei) => {
    (ex.solution || []).forEach((s) => {
      if (typeof s.result !== 'string' || !s.result.trim()) return;
      formulas++;
      const err = check(s.result);
      if (!err) { cls.raw_ok++; return; }
      const inner = stripDelims(s.result);
      if (inner !== null && !check(inner)) { cls.dollar_wrapped_ok_after_strip++; return; }
      if (inner === null && s.result.includes('$')) cls.mixed_inline_dollars++;
      cls.fails_either_way++;
      failedTemplates.add(t.id);
      failures.push({ template_id: t.id, example: ei, step_num: s.step_num, error: err,
                      latex: s.result.slice(0, 120) });
    });
  });
}

const byError = {};
for (const f of failures) {
  const key = f.error.split(':')[0].slice(0, 60);
  byError[key] = (byError[key] || 0) + 1;
}
const summary = {
  bank: bankPath, templates, formulas_checked: formulas,
  failing_formulas: failures.length,
  failing_templates: failedTemplates.size,
  failure_rate: formulas ? Number((failures.length / formulas).toFixed(4)) : 0,
  error_kinds: byError,
  classification: cls,
  katex_version: require('katex/package.json').version,
};
console.log(JSON.stringify(summary, null, 1));
for (const f of failures.slice(0, 12)) {
  console.log(`  ${f.template_id} step ${f.step_num}: ${f.error}\n      ${JSON.stringify(f.latex)}`);
}
if (jsonIdx > -1 && process.argv[jsonIdx + 1]) {
  fs.writeFileSync(process.argv[jsonIdx + 1], JSON.stringify({ summary, failures }, null, 1));
}
