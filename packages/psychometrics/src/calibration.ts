/**
 * Trinary cold-start calibration — 6-problem warm-up priors, ANS baseline,
 * and 3-path routing (users.active_path enum).
 */
import { WARMUP_PRIORS } from "./constants.js";

export type WarmupOutcome = keyof typeof WARMUP_PRIORS;

export interface WarmupResult {
  techniqueId: string;
  outcome: WarmupOutcome;
  responseTimeMs?: number;
}

/** Cold-start prior for one warm-up outcome: 0.80 / 0.50 / 0.20. */
export function warmupPrior(outcome: WarmupOutcome): number {
  return WARMUP_PRIORS[outcome];
}

/** Per-technique initial P(L0): mean of that technique's warm-up priors. */
export function calibrationPriors(results: WarmupResult[]): Map<string, number> {
  const sums = new Map<string, { total: number; n: number }>();
  for (const r of results) {
    const cur = sums.get(r.techniqueId) ?? { total: 0, n: 0 };
    cur.total += warmupPrior(r.outcome);
    cur.n += 1;
    sums.set(r.techniqueId, cur);
  }
  return new Map([...sums].map(([id, { total, n }]) => [id, total / n]));
}

/** ANS baseline = median warm-up response time (DFV calibration anchor). */
export function ansBaselineMs(responseTimesMs: number[]): number {
  if (responseTimesMs.length === 0) return 0;
  const sorted = [...responseTimesMs].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export type ActivePath = "core_math_vedic" | "vedic_standalone" | "exam_prep";

export interface RoutingProfile {
  primaryGoal?: "speed" | "accuracy" | "exam_prep" | "basics";
  targetExam?: string | null;
  vedicFamiliarity?: number; // 0–10
}

/** 3-path routing: exam signal → exam_prep; speed + Vedic familiarity →
 *  vedic_standalone; everything else → core_math_vedic (default path). */
export function routePath(profile: RoutingProfile): ActivePath {
  if (profile.primaryGoal === "exam_prep" || profile.targetExam) return "exam_prep";
  if (profile.primaryGoal === "speed" && (profile.vedicFamiliarity ?? 0) >= 5) {
    return "vedic_standalone";
  }
  return "core_math_vedic";
}
