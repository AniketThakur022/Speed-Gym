import { describe, expect, it } from "vitest";
import {
  composeAllocation,
  allocationPercentages,
  redistribute,
  ageTimeMultiplier,
  targetTimeSeconds,
} from "../src/index.js";

describe("60/20/20 session allocator", () => {
  it("base allocation splits 20 problems 12/4/4", () => {
    expect(composeAllocation(20)).toEqual({ primary: 12, sinking: 4, frontier: 4 });
  });

  it("SpeedDemon persona shifts to 70/15/15 → 14/3/3 of 20", () => {
    expect(composeAllocation(20, { persona: "SpeedDemon" })).toEqual({
      primary: 14,
      sinking: 3,
      frontier: 3,
    });
  });

  it("BrainTrainer persona shifts to 50/30/20 → 10/6/4 of 20", () => {
    expect(composeAllocation(20, { persona: "BrainTrainer" })).toEqual({
      primary: 10,
      sinking: 6,
      frontier: 4,
    });
  });

  it("wanderer behavioral cluster gets the exploratory 40/30/30 split", () => {
    expect(allocationPercentages(undefined, "wanderer")).toEqual({
      primary: 0.4,
      sinking: 0.3,
      frontier: 0.3,
    });
    expect(composeAllocation(10, { cluster: "wanderer" })).toEqual({
      primary: 4,
      sinking: 3,
      frontier: 3,
    });
  });

  it("empty fluid bucket redistributes +0.30/+0.30 to sinking and frontier", () => {
    const pcts = redistribute({ primary: 0.6, sinking: 0.2, frontier: 0.2 }, false, true);
    expect(pcts.primary).toBe(0);
    expect(pcts.sinking).toBeCloseTo(0.5, 10);
    expect(pcts.frontier).toBeCloseTo(0.5, 10);
    expect(composeAllocation(10, { hasFluid: false })).toEqual({ primary: 0, sinking: 5, frontier: 5 });
  });

  it("empty fragile bucket redistributes +0.10/+0.10 to primary and frontier", () => {
    const pcts = redistribute({ primary: 0.6, sinking: 0.2, frontier: 0.2 }, true, false);
    expect(pcts.primary).toBeCloseTo(0.7, 10);
    expect(pcts.sinking).toBe(0);
    expect(pcts.frontier).toBeCloseTo(0.3, 10);
    expect(composeAllocation(10, { hasFragile: false })).toEqual({ primary: 7, sinking: 0, frontier: 3 });
  });

  it("rounded counts always sum to the requested session size", () => {
    for (const size of [5, 7, 13, 15, 17, 20, 34]) {
      for (const persona of [undefined, "SpeedDemon", "BrainTrainer"]) {
        const a = composeAllocation(size, { persona });
        expect(a.primary + a.sinking + a.frontier).toBe(size);
      }
    }
  });

  it("age time multipliers follow the SHARED_REFERENCE table (base 30 s)", () => {
    expect(ageTimeMultiplier(9)).toBe(2.5);
    expect(ageTimeMultiplier(20)).toBe(1.0);
    expect(ageTimeMultiplier(30)).toBe(1.2);
    expect(ageTimeMultiplier(65)).toBe(2.0);
    expect(targetTimeSeconds(9)).toBe(75);
    expect(targetTimeSeconds(20)).toBe(30);
    expect(targetTimeSeconds(65)).toBe(60);
  });
});
