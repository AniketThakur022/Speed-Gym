/**
 * Practice runtime — processAttempt (state machine) + composeSession
 * (client-side prescription builder, ~50 ms budget).
 */
import type { Bucket, PrescribedProblem, SessionPrescription, TechniqueStateName } from "@vmsg/shared-types";
import { updateBkt } from "./bkt";
import { composeAllocation, targetTimeSeconds, ComposeAllocationOptions } from "./allocator";
import { WRONG_ANSWER_GUARDS, RFP_BKT_PARAMS } from "./constants";

export interface TechniqueState {
  techniqueId: string;
  state: TechniqueStateName;
  masteryScore: number;
  accuracyScore: number;
  consecutiveCorrect: number;
  consecutiveErrors: number;
  totalAttempts: number;
  totalCorrect: number;
  pLearned: number;
}

export function freshState(techniqueId: string, pInit: number = RFP_BKT_PARAMS.pInit): TechniqueState {
  return {
    techniqueId,
    state: "fractured",
    masteryScore: Math.round(pInit * 100),
    accuracyScore: 0,
    consecutiveCorrect: 0,
    consecutiveErrors: 0,
    totalAttempts: 0,
    totalCorrect: 0,
    pLearned: pInit,
  };
}

/** Legacy state classification (SHARED_REFERENCE §8 — Phase-1 thresholds). */
export function classifyState(s: {
  masteryScore: number;
  consecutiveCorrect: number;
  consecutiveErrors: number;
}): TechniqueStateName {
  if (s.masteryScore < 50 || s.consecutiveErrors >= 3) return "fractured";
  if (s.masteryScore >= 80 && s.consecutiveCorrect >= 5) return "fluid";
  return "fragile";
}

export interface AttemptInput {
  correct: boolean;
  timeSpentSeconds: number;
  targetTimeSeconds: number;
  difficulty?: number;
}

/** mastery = min(100, accuracy·0.6 + (under-target ? 40 : 20)) — backend §3.1. */
export function masteryScore(accuracyPct: number, underTarget: boolean): number {
  return Math.min(100, Math.round(accuracyPct * 0.6 + (underTarget ? 40 : 20)));
}

export function processAttempt(state: TechniqueState, attempt: AttemptInput): TechniqueState {
  const totalAttempts = state.totalAttempts + 1;
  const totalCorrect = state.totalCorrect + (attempt.correct ? 1 : 0);
  const accuracyScore = (totalCorrect / totalAttempts) * 100;
  const next: TechniqueState = {
    ...state,
    totalAttempts,
    totalCorrect,
    accuracyScore,
    consecutiveCorrect: attempt.correct ? state.consecutiveCorrect + 1 : 0,
    consecutiveErrors: attempt.correct ? 0 : state.consecutiveErrors + 1,
    masteryScore: masteryScore(accuracyScore, attempt.timeSpentSeconds < attempt.targetTimeSeconds),
    pLearned: updateBkt(state.pLearned, attempt.correct, RFP_BKT_PARAMS, attempt.difficulty),
  };
  next.state = classifyState(next);
  return next;
}

export interface SessionProfile {
  persona?: string;
  cluster?: string;
  age: number;
  sessionSize?: number;
}

export interface TechniquePools {
  fluid: string[];
  fragile: string[];
  frontier: string[];
}

const POOL_BY_BUCKET: Record<Bucket, keyof TechniquePools> = {
  primary: "fluid",
  sinking: "fragile",
  frontier: "frontier",
};

/** Client-side composeSession — allocation + deterministic pool draw + guards. */
export function composeSession(profile: SessionProfile, pools: TechniquePools): SessionPrescription {
  const sessionSize = profile.sessionSize ?? 20;
  const opts: ComposeAllocationOptions = {
    persona: profile.persona,
    cluster: profile.cluster,
    hasFluid: pools.fluid.length > 0,
    hasFragile: pools.fragile.length > 0,
  };
  const allocation = composeAllocation(sessionSize, opts);

  const problems: PrescribedProblem[] = [];
  for (const bucket of ["primary", "sinking", "frontier"] as Bucket[]) {
    const pool = pools[POOL_BY_BUCKET[bucket]];
    const want = allocation[bucket];
    for (let i = 0; i < want && pool.length > 0; i++) {
      problems.push({ techniqueId: pool[i % pool.length], bucket });
    }
  }

  return {
    allocation,
    problems,
    targetTimeSeconds: targetTimeSeconds(profile.age),
    guards: { ...WRONG_ANSWER_GUARDS },
  };
}
