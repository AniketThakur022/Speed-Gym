import { describe, expect, it } from "vitest";
import {
  createSinking,
  bumpSinking,
  resolveSinking,
  needsReview,
  reviewQueue,
  rawDailyWeight,
  dailyWeights,
} from "../src/index.js";

describe("spaced-repetition scheduler", () => {
  it("a new sinking skill starts at decay_priority 0.8", () => {
    const s = createSinking("nikhilam", "mock_wrong_answer");
    expect(s.decayPriority).toBe(0.8);
    expect(s.consecutiveErrors).toBe(1);
  });

  it("repeat failures bump priority by 0.1, capped at 0.95", () => {
    let s = createSinking("nikhilam", "session_wrong");
    s = bumpSinking(s);
    expect(s.decayPriority).toBeCloseTo(0.9, 10);
    s = bumpSinking(s);
    expect(s.decayPriority).toBe(0.95); // capped
    expect(s.consecutiveErrors).toBe(3);
  });

  it("successful remediation resets priority and error streak", () => {
    const s = resolveSinking(bumpSinking(createSinking("urdhva", "decay")));
    expect(s.decayPriority).toBe(0);
    expect(s.consecutiveErrors).toBe(0);
  });

  it("Phase-1 review cliff is binary at 7 days", () => {
    expect(needsReview(7)).toBe(false);
    expect(needsReview(8)).toBe(true);
  });

  it("daily weights map mastery bands to 0.05/0.15/0.30/0.40 and normalize to 1", () => {
    const items = [
      { techniqueId: "a", mastery: 95 },
      { techniqueId: "b", mastery: 75 },
      { techniqueId: "c", mastery: 55 },
      { techniqueId: "d", mastery: 40 },
    ];
    expect(rawDailyWeight(items[0])).toBeCloseTo(0.05, 10);
    expect(rawDailyWeight(items[1])).toBeCloseTo(0.15, 10);
    expect(rawDailyWeight(items[2])).toBeCloseTo(0.3, 10);
    expect(rawDailyWeight(items[3])).toBeCloseTo(0.4, 10);
    const weights = dailyWeights(items);
    const sum = [...weights.values()].reduce((s, w) => s + w, 0);
    expect(sum).toBeCloseTo(1.0, 10);
    expect(weights.get("d")).toBeCloseTo(0.4 / 0.9, 10);
  });

  it("urgency and damage-control multipliers follow the DE-spec §1.6 table", () => {
    // ≤3 days doubles; high-yield boost ×2 with 50–70 push ×1.5; non-high-yield ×0.1
    expect(rawDailyWeight({ techniqueId: "x", mastery: 55 }, { daysRemaining: 2 })).toBeCloseTo(0.6, 10);
    expect(
      rawDailyWeight({ techniqueId: "x", mastery: 55, isHighYield: true }, { damageControl: true }),
    ).toBeCloseTo(0.3 * 2.0 * 1.5, 10);
    expect(
      rawDailyWeight({ techniqueId: "x", mastery: 55, isHighYield: false }, { damageControl: true }),
    ).toBeCloseTo(0.3 * 0.1 * 1.5, 10);
    // review queue: priority > 0.7, sorted desc
    const queue = reviewQueue([
      { techniqueId: "lo", decayPriority: 0.5, consecutiveErrors: 1, totalErrors: 1, triggeredBy: "decay" },
      { techniqueId: "hi", decayPriority: 0.95, consecutiveErrors: 3, totalErrors: 4, triggeredBy: "decay" },
      { techniqueId: "mid", decayPriority: 0.8, consecutiveErrors: 1, totalErrors: 2, triggeredBy: "decay" },
    ]);
    expect(queue.map((s) => s.techniqueId)).toEqual(["hi", "mid"]);
  });
});
