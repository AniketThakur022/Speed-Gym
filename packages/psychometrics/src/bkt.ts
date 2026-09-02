/**
 * Bayesian Knowledge Tracing — RFP-exact (BKT-01..11).
 * Update = Bayesian posterior on the observation, then the learn step.
 * Verified against the pre-loss build's live demo: P(L)=0.35 (FRACTURED) +
 * one correct difficulty-1 answer → 0.8247 (FRAGILE 82%).
 */
import { BktParams, RFP_BKT_PARAMS, LEARN_RATE_BY_DIFFICULTY, FLUID_GATE, PROFICIENT_GATE } from "./constants.js";

export function validateParams(params: BktParams): void {
  if (params.pSlip + params.pGuess >= 1) {
    throw new Error(`BKT identifiability violated: P(S)+P(G) must be < 1 (BKT-06), got ${params.pSlip + params.pGuess}`);
  }
}

/** P(L | observation) — BKT-07/08. */
export function posterior(pL: number, correct: boolean, params: BktParams = RFP_BKT_PARAMS): number {
  validateParams(params);
  const { pSlip, pGuess } = params;
  if (correct) {
    const num = pL * (1 - pSlip);
    return num / (num + (1 - pL) * pGuess);
  }
  const num = pL * pSlip;
  return num / (num + (1 - pL) * (1 - pGuess));
}

/** Learn step after each attempt: P(L)' = P(L|obs) + (1 − P(L|obs))·P(T).
 *  P(T) scales with item difficulty when provided (L1=0.40 … L5=0.15). */
export function learnStep(pPosterior: number, params: BktParams = RFP_BKT_PARAMS, difficulty?: number): number {
  const pT = difficulty !== undefined ? LEARN_RATE_BY_DIFFICULTY[difficulty] ?? params.pTransit : params.pTransit;
  return pPosterior + (1 - pPosterior) * pT;
}

/** Full BKT update: posterior then learn. */
export function updateBkt(
  pL: number,
  correct: boolean,
  params: BktParams = RFP_BKT_PARAMS,
  difficulty?: number,
): number {
  return learnStep(posterior(pL, correct, params), params, difficulty);
}

/** Inter-session decay (BKT-09): P(L)·(1 − P(F))^(d/45). */
export function decayMastery(pL: number, days: number, params: BktParams = RFP_BKT_PARAMS): number {
  if (days <= 0) return pL;
  return pL * Math.pow(1 - params.pForget, days / 45);
}

/** Fluid gate (BKT-10, ROU-02): P(L) ≥ 0.85. */
export function isFluid(pL: number): boolean {
  return pL >= FLUID_GATE;
}

/** BKT probability → 0–100 mastery score (SHARED_REFERENCE §5.2). */
export function bktToMastery(pLearned: number): number {
  return pLearned * 100;
}

export type BktState = "fluid" | "proficient" | "learning";

/** BKT-threshold classification (0.85 / 0.60). */
export function classifyBkt(pL: number): BktState {
  if (pL >= FLUID_GATE) return "fluid";
  if (pL >= PROFICIENT_GATE) return "proficient";
  return "learning";
}

/** Empirical-Bayes shrinkage of the prior once n ≥ 20 attempts exist (BKT-11):
 *  blend the fixed prior toward the observed correct-rate, weight n/(n+n0). */
export function shrinkPrior(prior: number, observedRate: number, n: number, n0 = 20): number {
  if (n < 20) return prior;
  return (n0 * prior + n * observedRate) / (n0 + n);
}
