import { describe, expect, it } from "vitest";
import {
  ekanyunenaByNines,
  anurupyenaMultiply,
  paravartyaDivide,
  shunyamSolveLinear,
  sankalanaSolvePair,
  puranaCompleteSquare,
  chalanaQuadraticRoots,
  vyashtiProduct,
  shesanyankenaRecurring,
  sopantyaDivisible,
  gunitaSumCheck,
} from "../src/index";

/** Every sutra is checked against ordinary arithmetic, never against itself. */
describe("Vedic sutras 6–16", () => {
  it("Ekanyunena Purvena multiplies by a run of nines", () => {
    expect(ekanyunenaByNines(7, 1).answer).toBe(7 * 9);
    expect(ekanyunenaByNines(43, 2).answer).toBe(43 * 99);
    expect(ekanyunenaByNines(614, 3).answer).toBe(614 * 999);
    expect(() => ekanyunenaByNines(120, 2)).toThrow(/expects n <=/);
  });

  it("Anurupyena multiplies around a working base (48×47 at base 50)", () => {
    expect(anurupyenaMultiply(48, 47, 100, 0.5).answer).toBe(48 * 47);
    expect(anurupyenaMultiply(46, 43, 100, 0.5).answer).toBe(46 * 43);
    // Working base above the round base: 212 × 213 at 200.
    expect(anurupyenaMultiply(212, 213, 100, 2).answer).toBe(212 * 213);
  });

  it("Paravartya Yojayet divides by a divisor just above the base", () => {
    const r = paravartyaDivide(1234, 112, 100);
    expect(r.answer).toBe(Math.floor(1234 / 112));
    expect(r.steps[2].result).toBe(String(1234 % 112));
  });

  it("Shunyam Saamyasamuccaye gives x = 0 when the constant is shared", () => {
    // 7x + 5 = 3x + 5  →  x = 0, the sutra's headline case.
    expect(shunyamSolveLinear(7, 5, 3, 5).answer).toBe(0);
    expect(shunyamSolveLinear(7, 5, 3, 5).steps[0].result).toBe("equal");
    // General transposition still works: 5x + 2 = 3x + 8 → x = 3.
    expect(shunyamSolveLinear(5, 2, 3, 8).answer).toBe(3);
    expect(() => shunyamSolveLinear(4, 1, 4, 9)).toThrow(/distinct/);
  });

  it("Sankalana-Vyavakalanabhyam solves coefficient-swapped pairs", () => {
    // 45x + 23y = 113 ; 23x + 45y = 91  →  x = 2, y = 1
    const [x, y] = sankalanaSolvePair(45, 23, 113, 91).answers;
    expect(x).toBeCloseTo(2, 10);
    expect(y).toBeCloseTo(1, 10);
    // Substituting back must satisfy both original equations.
    expect(45 * x + 23 * y).toBeCloseTo(113, 10);
    expect(23 * x + 45 * y).toBeCloseTo(91, 10);
  });

  it("Puranapuranabhyam completes the square", () => {
    // x² − 5x + 6 → roots 3 and 2
    const { answers } = puranaCompleteSquare(-5, 6);
    expect([...answers].sort((a, b) => a - b)).toEqual([2, 3]);
    for (const root of answers) {
      expect(root * root - 5 * root + 6).toBeCloseTo(0, 10);
    }
    expect(() => puranaCompleteSquare(0, 4)).toThrow(/no real roots/);
  });

  it("Chalana-Kalanabhyam finds quadratic roots via their difference", () => {
    // 2x² − 7x + 3 → roots 3 and 0.5
    const { answers } = chalanaQuadraticRoots(2, -7, 3);
    for (const root of answers) {
      expect(2 * root * root - 7 * root + 3).toBeCloseTo(0, 10);
    }
    expect([...answers].sort((a, b) => a - b)).toEqual([0.5, 3]);
    expect(() => chalanaQuadraticRoots(0, 1, 1)).toThrow(/a ≠ 0/);
  });

  it("Vyashtisamanstih multiplies via the mean (difference of squares)", () => {
    expect(vyashtiProduct(47, 53).answer).toBe(47 * 53);
    expect(vyashtiProduct(96, 104).answer).toBe(96 * 104);
    expect(vyashtiProduct(12, 12).answer).toBe(144);
  });

  it("Shesanyankena Charamena reproduces the recurring block of 1/n", () => {
    const nineteenth = shesanyankenaRecurring(19);
    expect(nineteenth.digits.join("")).toBe("052631578947368421"); // 1/19, 18 digits
    expect(nineteenth.digits).toHaveLength(18);

    const seventh = shesanyankenaRecurring(29);
    // Independent check: the block must equal the long division of 1/29.
    let remainder = 1;
    const expected: number[] = [];
    for (let i = 0; i < seventh.digits.length; i++) {
      remainder *= 10;
      expected.push(Math.floor(remainder / 29));
      remainder %= 29;
    }
    expect(seventh.digits).toEqual(expected);
    expect(() => shesanyankenaRecurring(21)).toThrow(/ending in 9/);
  });

  it("Sopantyadvayamantyam tests divisibility by osculation", () => {
    expect(sopantyaDivisible(114, 19).divisible).toBe(true); // 19 × 6
    expect(sopantyaDivisible(2774, 19).divisible).toBe(true); // 19 × 146
    expect(sopantyaDivisible(115, 19).divisible).toBe(false);
    expect(() => sopantyaDivisible(100, 21)).toThrow(/ending in 9/);
  });

  it("osculation agrees with the modulus over a range", () => {
    for (let n = 1; n <= 400; n++) {
      expect(sopantyaDivisible(n, 29).divisible).toBe(n % 29 === 0);
    }
  });

  it("Gunitasamuchyah validates a factorisation by its coefficient sums", () => {
    // x² + 5x + 6 = (x + 2)(x + 3): 12 = 3 × 4
    expect(gunitaSumCheck([1, 5, 6], [[1, 2], [1, 3]]).valid).toBe(true);
    // A wrong factorisation is rejected: (x + 1)(x + 3) sums to 2 × 4 = 8 ≠ 12
    expect(gunitaSumCheck([1, 5, 6], [[1, 1], [1, 3]]).valid).toBe(false);
  });
});
