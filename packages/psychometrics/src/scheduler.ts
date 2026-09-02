/**
 * Spaced-repetition scheduler — sinking-skill queue (decay-priority model)
 * and the daily-weight formula (DECISION_ENGINE_TECHNICAL_SPEC §1.6, Q5/Q6).
 */
import {
  SINKING_CREATE_PRIORITY,
  SINKING_BUMP,
  SINKING_PRIORITY_CAP,
  DECAY_CLIFF_DAYS,
} from "./constants.js";

export type SinkingTrigger = "mock_wrong_answer" | "session_wrong" | "decay" | "manual";

export interface SinkingSkill {
  techniqueId: string;
  decayPriority: number;
  consecutiveErrors: number;
  totalErrors: number;
  triggeredBy: SinkingTrigger;
}

/** New sinking edge starts at decay_priority 0.8 (graph Q5 ON CREATE). */
export function createSinking(techniqueId: string, triggeredBy: SinkingTrigger): SinkingSkill {
  return {
    techniqueId,
    decayPriority: SINKING_CREATE_PRIORITY,
    consecutiveErrors: 1,
    totalErrors: 1,
    triggeredBy,
  };
}

/** Repeat failure: +0.1 capped at 0.95 (graph Q5 ON MATCH). */
export function bumpSinking(skill: SinkingSkill): SinkingSkill {
  return {
    ...skill,
    decayPriority: Math.min(SINKING_PRIORITY_CAP, skill.decayPriority + SINKING_BUMP),
    consecutiveErrors: skill.consecutiveErrors + 1,
    totalErrors: skill.totalErrors + 1,
  };
}

/** Successful remediation resets the queue entry (backend §3.1 notes). */
export function resolveSinking(skill: SinkingSkill): SinkingSkill {
  return { ...skill, decayPriority: 0, consecutiveErrors: 0 };
}

/** Phase-1 decay is a binary cliff at 7 days (SHARED_REFERENCE §8). */
export function needsReview(daysSinceLastPractice: number): boolean {
  return daysSinceLastPractice > DECAY_CLIFF_DAYS;
}

export function reviewQueue(skills: SinkingSkill[], limit = 5, minPriority = 0.7): SinkingSkill[] {
  return skills
    .filter((s) => s.decayPriority > minPriority)
    .sort((a, b) => b.decayPriority - a.decayPriority)
    .slice(0, limit);
}

// ── Daily weights (DE spec §1.6) ─────────────────────────────────────────────

export interface WeightItem {
  techniqueId: string;
  mastery: number; // 0–100
  isHighYield?: boolean;
  decayDays?: number;
  isWeakArea?: boolean;
}

export interface WeightOptions {
  daysRemaining?: number;
  damageControl?: boolean;
}

export function urgencyMultiplier(daysRemaining?: number): number {
  if (daysRemaining === undefined) return 1.0;
  if (daysRemaining <= 3) return 2.0;
  if (daysRemaining <= 7) return 1.5;
  if (daysRemaining <= 14) return 1.2;
  return 1.0;
}

export function rawDailyWeight(item: WeightItem, opts: WeightOptions = {}): number {
  let weight: number;
  if (item.mastery >= 90) weight = 0.05;
  else if (item.mastery >= 70) weight = 0.15;
  else if (item.mastery >= 50) weight = 0.3;
  else weight = 0.4;

  if (opts.damageControl) {
    weight *= item.isHighYield ? 2.0 : 0.1;
    if (item.mastery >= 90) weight = 0.01;
    else if (item.mastery >= 50 && item.mastery < 70) weight *= 1.5;
  }

  if (item.isWeakArea) weight *= 1.5;
  if ((item.decayDays ?? 0) > 7) weight *= 1.5;

  return weight * urgencyMultiplier(opts.daysRemaining);
}

/** Normalized weights: Σ = 1.0 across the technique set. */
export function dailyWeights(items: WeightItem[], opts: WeightOptions = {}): Map<string, number> {
  const raw = items.map((i) => [i.techniqueId, rawDailyWeight(i, opts)] as const);
  const total = raw.reduce((s, [, w]) => s + w, 0);
  return new Map(raw.map(([id, w]) => [id, total > 0 ? w / total : 0]));
}
