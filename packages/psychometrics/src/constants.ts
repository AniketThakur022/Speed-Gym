/**
 * Canonical Decision-Engine constants.
 * BKT priors are RFP v7.2 BKT-01..05 (the RFP wins over the older v5.2
 * SHARED_REFERENCE values); learn-rate-by-difficulty and the allocation /
 * guard / persona tables are SHARED_REFERENCE.md §2/§6/§9/§11.
 */
import type { WrongAnswerGuards } from "@vmsg/shared-types";

export interface BktParams {
  pInit: number;    // P(L0)
  pTransit: number; // P(T)
  pSlip: number;    // P(S)
  pGuess: number;   // P(G)
  pForget: number;  // P(F) per day
}

export const RFP_BKT_PARAMS: BktParams = {
  pInit: 0.35,
  pTransit: 0.14,
  pSlip: 0.1,
  pGuess: 0.2,
  pForget: 0.007,
};

/** P(T) scaled by item difficulty (SHARED_REFERENCE §5.1). */
export const LEARN_RATE_BY_DIFFICULTY: Record<number, number> = {
  1: 0.4,
  2: 0.3,
  3: 0.25,
  4: 0.2,
  5: 0.15,
};

export const FLUID_GATE = 0.85;      // BKT-10
export const PROFICIENT_GATE = 0.6;

export const WARMUP_PRIORS = {
  correct_first_try: 0.8,
  hint_or_slow: 0.5,
  wrong: 0.2,
} as const;

export type AllocationPercentages = { primary: number; sinking: number; frontier: number };

export const BASE_ALLOCATION: AllocationPercentages = { primary: 0.6, sinking: 0.2, frontier: 0.2 };

export const PERSONA_ALLOCATIONS: Record<string, AllocationPercentages> = {
  SpeedDemon: { primary: 0.7, sinking: 0.15, frontier: 0.15 },
  BrainTrainer: { primary: 0.5, sinking: 0.3, frontier: 0.2 },
  SchoolSupport: { primary: 0.6, sinking: 0.2, frontier: 0.2 },
};

export const CLUSTER_ALLOCATIONS: Record<string, AllocationPercentages> = {
  sprinter: { primary: 0.7, sinking: 0.15, frontier: 0.15 },
  deliberate: { primary: 0.6, sinking: 0.2, frontier: 0.2 },
  perfectionist: { primary: 0.6, sinking: 0.2, frontier: 0.2 },
  balanced: { primary: 0.6, sinking: 0.2, frontier: 0.2 },
  rebuilder: { primary: 0.5, sinking: 0.3, frontier: 0.2 },
  wanderer: { primary: 0.4, sinking: 0.3, frontier: 0.3 },
};

/** Age-based time multipliers, base 30 s/problem (SHARED_REFERENCE §2). */
export const AGE_TIME_MULTIPLIERS: Array<{ min: number; max: number; multiplier: number }> = [
  { min: 8, max: 10, multiplier: 2.5 },
  { min: 11, max: 13, multiplier: 2.0 },
  { min: 14, max: 17, multiplier: 1.5 },
  { min: 18, max: 25, multiplier: 1.0 },
  { min: 26, max: 40, multiplier: 1.2 },
  { min: 41, max: 60, multiplier: 1.5 },
  { min: 61, max: 200, multiplier: 2.0 },
];

export const BASE_TIME_SECONDS = 30;

export const WRONG_ANSWER_GUARDS: WrongAnswerGuards = {
  max_cycles_per_technique: 3,
  max_wrongs_per_session: 5,
  max_consecutive_wrongs: 4,
  pingpong_max_toggles: 3,
  pingpong_window: 10,
};

// Scheduler (sinking-skill queue)
export const SINKING_CREATE_PRIORITY = 0.8;
export const SINKING_BUMP = 0.1;
export const SINKING_PRIORITY_CAP = 0.95;
export const DECAY_CLIFF_DAYS = 7; // Phase-1 binary cliff
