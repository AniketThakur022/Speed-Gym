/**
 * Session allocator — 60/20/20 primary/sinking/frontier with persona and
 * behavioral-cluster overrides and the SHARED_REFERENCE §9.3 empty-bucket
 * redistribution. Counts use largest-remainder rounding so they always sum
 * to the requested session size.
 */
import {
  AllocationPercentages,
  BASE_ALLOCATION,
  PERSONA_ALLOCATIONS,
  CLUSTER_ALLOCATIONS,
  AGE_TIME_MULTIPLIERS,
  BASE_TIME_SECONDS,
} from "./constants.js";
import type { SessionAllocation } from "@vmsg/shared-types";

export function allocationPercentages(persona?: string, cluster?: string): AllocationPercentages {
  if (cluster && CLUSTER_ALLOCATIONS[cluster]) return { ...CLUSTER_ALLOCATIONS[cluster] };
  if (persona && PERSONA_ALLOCATIONS[persona]) return { ...PERSONA_ALLOCATIONS[persona] };
  return { ...BASE_ALLOCATION };
}

/** SHARED_REFERENCE §9.3 — fluid check first, then fragile check. */
export function redistribute(
  pcts: AllocationPercentages,
  hasFluid: boolean,
  hasFragile: boolean,
): AllocationPercentages {
  const out = { ...pcts };
  if (!hasFluid) {
    out.primary = 0;
    out.sinking += 0.3;
    out.frontier += 0.3;
  }
  if (!hasFragile) {
    out.sinking = 0;
    out.primary += 0.1;
    out.frontier += 0.1;
  }
  return out;
}

/** Largest-remainder apportionment over (possibly non-normalized) weights. */
function apportion(size: number, weights: AllocationPercentages): SessionAllocation {
  const entries = [
    ["primary", weights.primary],
    ["sinking", weights.sinking],
    ["frontier", weights.frontier],
  ] as const;
  const total = entries.reduce((s, [, w]) => s + w, 0);
  if (total <= 0) return { primary: 0, sinking: 0, frontier: size };

  const exact = entries.map(([k, w]) => [k, (w / total) * size] as const);
  const floors = exact.map(([k, v]) => [k, Math.floor(v), v - Math.floor(v)] as const);
  let assigned = floors.reduce((s, [, f]) => s + f, 0);
  const result: Record<string, number> = Object.fromEntries(floors.map(([k, f]) => [k, f]));
  const byRemainder = [...floors].sort((a, b) => b[2] - a[2]);
  for (const [k] of byRemainder) {
    if (assigned >= size) break;
    result[k] += 1;
    assigned += 1;
  }
  return { primary: result.primary, sinking: result.sinking, frontier: result.frontier };
}

export interface ComposeAllocationOptions {
  persona?: string;
  cluster?: string;
  hasFluid?: boolean;
  hasFragile?: boolean;
}

export function composeAllocation(sessionSize: number, opts: ComposeAllocationOptions = {}): SessionAllocation {
  const pcts = redistribute(
    allocationPercentages(opts.persona, opts.cluster),
    opts.hasFluid ?? true,
    opts.hasFragile ?? true,
  );
  return apportion(sessionSize, pcts);
}

export function ageTimeMultiplier(age: number): number {
  for (const { min, max, multiplier } of AGE_TIME_MULTIPLIERS) {
    if (age >= min && age <= max) return multiplier;
  }
  return age < 8 ? 2.5 : 2.0;
}

export function targetTimeSeconds(age: number, base: number = BASE_TIME_SECONDS): number {
  return Math.round(base * ageTimeMultiplier(age));
}
