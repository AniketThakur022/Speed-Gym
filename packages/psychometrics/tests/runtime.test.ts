import { describe, expect, it } from "vitest";
import { freshState, processAttempt, composeSession, WRONG_ANSWER_GUARDS } from "../src/index.js";

describe("practice runtime", () => {
  it("processAttempt updates streaks, accuracy, mastery formula, and BKT together", () => {
    const next = processAttempt(freshState("nikhilam"), {
      correct: true,
      timeSpentSeconds: 12,
      targetTimeSeconds: 30,
      difficulty: 1,
    });
    expect(next.totalAttempts).toBe(1);
    expect(next.accuracyScore).toBeCloseTo(100, 10);
    expect(next.masteryScore).toBe(100); // 100·0.6 + 40 (under target), capped
    expect(next.consecutiveCorrect).toBe(1);
    expect(next.pLearned).toBeCloseTo(0.8247191, 6); // demo-exact BKT step
    expect(next.state).toBe("fragile"); // mastery is high but streak < 5 → not yet fluid
  });

  it("fifth consecutive correct with mastery ≥ 80 transitions to fluid", () => {
    const base = {
      ...freshState("urdhva"),
      totalAttempts: 10,
      totalCorrect: 9,
      consecutiveCorrect: 4,
      accuracyScore: 90,
      masteryScore: 78,
      pLearned: 0.8,
      state: "fragile" as const,
    };
    const next = processAttempt(base, { correct: true, timeSpentSeconds: 10, targetTimeSeconds: 30 });
    expect(next.consecutiveCorrect).toBe(5);
    expect(next.masteryScore).toBeGreaterThanOrEqual(80); // 90.9·0.6+40 ≈ 95
    expect(next.state).toBe("fluid");
  });

  it("composeSession fills buckets per allocation and injects the wrong-answer guards", () => {
    const prescription = composeSession(
      { persona: "SpeedDemon", age: 20, sessionSize: 20 },
      {
        fluid: ["nikhilam", "urdhva", "ekadhikena"],
        fragile: ["yavadunam"],
        frontier: ["digital-root", "direct-division"],
      },
    );
    expect(prescription.allocation).toEqual({ primary: 14, sinking: 3, frontier: 3 });
    expect(prescription.problems).toHaveLength(20);
    expect(prescription.problems.filter((p) => p.bucket === "primary")).toHaveLength(14);
    expect(prescription.guards).toEqual(WRONG_ANSWER_GUARDS);
    expect(prescription.targetTimeSeconds).toBe(30);
  });
});
