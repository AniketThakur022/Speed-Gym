import { describe, expect, it } from "vitest";
import {
  RFP_BKT_PARAMS,
  LEARN_RATE_BY_DIFFICULTY,
  posterior,
  learnStep,
  updateBkt,
  decayMastery,
  isFluid,
  bktToMastery,
  classifyBkt,
  shrinkPrior,
  validateParams,
} from "../src/index.js";

// Hand-computed against BKT-07/08 with the RFP priors:
// P(L)=0.35, P(S)=0.10, P(G)=0.20
//   correct: 0.35·0.9 / (0.35·0.9 + 0.65·0.2) = 0.315/0.445 = 0.70786517
//   wrong:   0.35·0.1 / (0.35·0.1 + 0.65·0.8) = 0.035/0.555 = 0.06306306

describe("BKT engine (RFP-exact)", () => {
  it("posterior after a correct answer matches the hand-computed value", () => {
    expect(posterior(0.35, true)).toBeCloseTo(0.7078651685, 8);
  });

  it("posterior after a wrong answer matches the hand-computed value", () => {
    expect(posterior(0.35, false)).toBeCloseTo(0.0630630631, 8);
  });

  it("reproduces the verified pre-loss demo: 35% + one correct L1 answer → 82% (FRACTURED→FRAGILE)", () => {
    // learn step with difficulty-1 rate 0.40:
    // 0.70786517 + 0.29213483·0.40 = 0.82471910
    const pL = updateBkt(0.35, true, RFP_BKT_PARAMS, 1);
    expect(pL).toBeCloseTo(0.8247191, 6);
    expect(Math.round(bktToMastery(pL))).toBe(82);
  });

  it("learn step falls back to the RFP P(T)=0.14 when difficulty is unknown", () => {
    // 0.70786517 + 0.29213483·0.14 = 0.74876404
    expect(updateBkt(0.35, true)).toBeCloseTo(0.748764, 6);
  });

  it("applies the difficulty-scaled learn-rate table L1..L5", () => {
    expect(LEARN_RATE_BY_DIFFICULTY).toEqual({ 1: 0.4, 2: 0.3, 3: 0.25, 4: 0.2, 5: 0.15 });
    const post = posterior(0.5, true);
    for (const d of [1, 2, 3, 4, 5]) {
      expect(learnStep(post, RFP_BKT_PARAMS, d)).toBeCloseTo(
        post + (1 - post) * LEARN_RATE_BY_DIFFICULTY[d],
        12,
      );
    }
  });

  it("rejects parameter sets violating identifiability P(S)+P(G) < 1", () => {
    expect(() =>
      validateParams({ pInit: 0.35, pTransit: 0.14, pSlip: 0.6, pGuess: 0.4, pForget: 0.007 }),
    ).toThrow(/identifiability/);
  });

  it("inter-session decay follows BKT-09: P(L)·(1−P(F))^(d/45)", () => {
    expect(decayMastery(0.9, 45)).toBeCloseTo(0.9 * (1 - 0.007), 10);
    expect(decayMastery(0.9, 90)).toBeCloseTo(0.9 * Math.pow(0.993, 2), 10);
  });

  it("zero (or negative) elapsed days leaves mastery unchanged", () => {
    expect(decayMastery(0.7, 0)).toBe(0.7);
    expect(decayMastery(0.7, -3)).toBe(0.7);
  });

  it("fluid gate fires at exactly P(L) ≥ 0.85 (BKT-10)", () => {
    expect(isFluid(0.85)).toBe(true);
    expect(isFluid(0.8499999)).toBe(false);
  });

  it("maps BKT probability to the 0–100 mastery scale", () => {
    expect(bktToMastery(0.35)).toBeCloseTo(35);
    expect(bktToMastery(0.8247191)).toBeCloseTo(82.47191);
  });

  it("classifies by BKT thresholds 0.85/0.60 (fluid/proficient/learning)", () => {
    expect(classifyBkt(0.9)).toBe("fluid");
    expect(classifyBkt(0.7)).toBe("proficient");
    expect(classifyBkt(0.59)).toBe("learning");
  });

  it("empirical-Bayes shrinkage activates at n ≥ 20 and moves the prior toward observed", () => {
    expect(shrinkPrior(0.35, 0.9, 19)).toBe(0.35);
    expect(shrinkPrior(0.35, 0.9, 20)).toBeCloseTo((20 * 0.35 + 20 * 0.9) / 40, 10); // 0.625
    const n40 = shrinkPrior(0.35, 0.9, 40);
    expect(n40).toBeGreaterThan(shrinkPrior(0.35, 0.9, 20));
    expect(n40).toBeLessThan(0.9);
  });
});
