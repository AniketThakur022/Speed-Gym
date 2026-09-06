/**
 * Validates delivery records against the REAL frontend contract —
 * packages/shared-types/src/template.ts, ported verbatim from the recovered
 * APK source (recovered/exam-arena-src/src_lib_types_template.ts_cf55).
 *
 * Usage: tsx demo/zod_validate.ts <file.jsonl>   (JSON per line, or {"delivery":...})
 * Emits one JSON object on stdout.
 */
import { readFileSync } from "node:fs";
import { SolveAlongTemplateSchema } from "../packages/shared-types/src/template";

const path = process.argv[2];
const lines = readFileSync(path, "utf8").split("\n").filter((l) => l.trim());

let valid = 0;
const failures: unknown[] = [];
for (const line of lines) {
  const obj = JSON.parse(line);
  const candidate = obj && obj.delivery ? obj.delivery : obj;
  const res = SolveAlongTemplateSchema.safeParse(candidate);
  if (res.success) valid++;
  else
    failures.push({
      id: candidate?.id ?? null,
      issues: res.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`),
    });
}
console.log(
  JSON.stringify({
    schema_source: "packages/shared-types/src/template.ts (SolveAlongTemplateSchema)",
    zod_version: require("zod/package.json").version,
    checked: lines.length,
    valid,
    invalid: failures.length,
    failures: failures.slice(0, 5),
  })
);
