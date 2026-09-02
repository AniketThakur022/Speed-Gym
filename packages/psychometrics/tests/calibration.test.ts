import { describe, expect, it } from "vitest";
import { warmupPrior, calibrationPriors, ansBaselineMs, routePath } from "../src/index.js";

describe("trinary cold-start calibration", () => {
  it("warm-up outcomes map to priors 0.80 / 0.50 / 0.20", () => {
    expect(warmupPrior("correct_first_try")).toBe(0.8);
    expect(warmupPrior("hint_or_slow")).toBe(0.5);
    expect(warmupPrior("wrong")).toBe(0.2);
  });

  it("per-technique priors average that technique's warm-up outcomes", () => {
    const priors = calibrationPriors([
      { techniqueId: "nikhilam", outcome: "correct_first_try" },
      { techniqueId: "nikhilam", outcome: "wrong" },
      { techniqueId: "urdhva", outcome: "hint_or_slow" },
    ]);
    expect(priors.get("nikhilam")).toBeCloseTo(0.5, 10); // (0.8+0.2)/2
    expect(priors.get("urdhva")).toBeCloseTo(0.5, 10);
  });

  it("ANS baseline is the median warm-up response time", () => {
    expect(ansBaselineMs([1200, 800, 1000])).toBe(1000);
    expect(ansBaselineMs([1200, 800, 1000, 2000])).toBe(1100); // even count → mean of middle two
    expect(ansBaselineMs([])).toBe(0);
  });

  it("3-path routing: exam signal → exam_prep; speed+Vedic → standalone; default core", () => {
    expect(routePath({ primaryGoal: "exam_prep" })).toBe("exam_prep");
    expect(routePath({ primaryGoal: "speed", targetExam: "CAT" })).toBe("exam_prep");
    expect(routePath({ primaryGoal: "speed", vedicFamiliarity: 7 })).toBe("vedic_standalone");
    expect(routePath({ primaryGoal: "speed", vedicFamiliarity: 2 })).toBe("core_math_vedic");
    expect(routePath({ primaryGoal: "basics" })).toBe("core_math_vedic");
  });
});
