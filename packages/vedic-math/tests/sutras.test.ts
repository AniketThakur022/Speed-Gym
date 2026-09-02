import { describe, expect, it } from "vitest";
import {
  nikhilamMultiply,
  urdhvaMultiply2x2,
  squareEndingIn5,
  yavadunamSquare,
  digitalRoot,
  digitalRootCheck,
} from "../src/index.js";

describe("Vedic sutras (self-verifying)", () => {
  it("Nikhilam below base 100: 98 × 97 = 9506 via deficits −2/−3", () => {
    const r = nikhilamMultiply(98, 97, 100);
    expect(r.answer).toBe(9506);
    expect(r.answer).toBe(98 * 97);
    expect(r.steps).toHaveLength(4);
  });

  it("Nikhilam above base and mixed deviations stay exact (104×103, 104×97)", () => {
    expect(nikhilamMultiply(104, 103, 100).answer).toBe(10712);
    expect(nikhilamMultiply(104, 97, 100).answer).toBe(104 * 97); // 10088, negative cross product
  });

  it("Nikhilam works at base 1000: 996 × 988 = 984048", () => {
    const r = nikhilamMultiply(996, 988, 1000);
    expect(r.answer).toBe(996 * 988);
    expect(r.answer).toBe(984048);
  });

  it("Urdhva-Tiryagbhyam 2-digit: 23 × 41 = 943 with carry resolution", () => {
    const r = urdhvaMultiply2x2(23, 41);
    expect(r.answer).toBe(943);
    expect(urdhvaMultiply2x2(87, 96).answer).toBe(87 * 96); // heavy carries
  });

  it("Ekadhikena square ending in 5: 85² = 7225 (8×9 | 25)", () => {
    const r = squareEndingIn5(85);
    expect(r.answer).toBe(7225);
    expect(() => squareEndingIn5(84)).toThrow(/ending in 5/);
  });

  it("Yavadunam squaring near base: 98² = 9604 and 112² = 12544 (carry case)", () => {
    expect(yavadunamSquare(98, 100).answer).toBe(9604);
    expect(yavadunamSquare(112, 100).answer).toBe(12544);
    expect(yavadunamSquare(88, 100).answer).toBe(7744);
  });

  it("digital root reduces by repeated digit sums: dr(12345) = 6", () => {
    const r = digitalRoot(12345);
    expect(r.answer).toBe(6);
    expect(r.steps[0].description).toContain("1 + 2 + 3 + 4 + 5");
    expect(digitalRoot(7).answer).toBe(7);
  });

  it("casting-out-nines check accepts the true product and rejects an off-by-one", () => {
    expect(digitalRootCheck(98, 97, 9506)).toBe(true);
    expect(digitalRootCheck(98, 97, 9507)).toBe(false);
  });
});
