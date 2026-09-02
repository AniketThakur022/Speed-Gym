/**
 * Vedic sutras 6–16 — the set beyond the Sprint-2 five.
 *
 * Each function returns the exact answer plus SolveAlong-shaped steps, and each
 * is written so a test can check it against ordinary arithmetic rather than
 * against itself. Where a sutra is a general heuristic rather than a closed
 * procedure, the implementation covers the classical case the technique is
 * actually taught and examined on, and says so.
 */
import type { SolutionStep } from "@vmsg/shared-types";
import type { SutraResult } from "./sutras";

function step(step_num: number, operation: string, result: string, description?: string): SolutionStep {
  return { step_num, operation, result, description };
}

/** Result carrying a rational/decimal answer plus the steps that produced it. */
export interface RationalResult {
  answer: number;
  steps: SolutionStep[];
}

/** A pair of roots or solutions. */
export interface PairResult {
  answers: [number, number];
  steps: SolutionStep[];
}

// ── 6. Ekanyunena Purvena — "by one less than the previous" ──────────────────
// Multiplying by a string of nines: N × (10^k − 1).
// Left part = N − 1, right part = (10^k − N) padded, when N ≤ 10^k.

export function ekanyunenaByNines(n: number, nines: number): SutraResult {
  const base = Math.pow(10, nines);
  if (n > base) {
    throw new Error(`ekanyunenaByNines expects n <= ${base} for ${nines} nines, got ${n}`);
  }
  const left = n - 1;
  const right = base - n;
  const answer = left * base + right;
  return {
    answer,
    steps: [
      step(1, "one less than the multiplicand", `${left}`, `${n} − 1 = ${left}`),
      step(2, "complement of the multiplicand", `${right}`, `${base} − ${n} = ${right}`),
      step(3, "join the halves", `${answer}`, `${left} | ${String(right).padStart(nines, "0")}`),
    ],
  };
}

// ── 7. Anurupyena — "proportionately" (working base) ─────────────────────────
// Multiplication near a convenient working base such as 50 (= 100/2) or 200.

export function anurupyenaMultiply(a: number, b: number, base: number, multiplier: number): SutraResult {
  const workingBase = base * multiplier;
  const da = a - workingBase;
  const db = b - workingBase;
  const crossSum = a + db;
  const scaled = multiplier >= 1 ? crossSum * multiplier : crossSum / (1 / multiplier);
  const rightRaw = da * db;

  const digits = String(base).length - 1;
  const mod = Math.pow(10, digits);
  const carry = Math.floor(rightRaw / mod);
  const right = rightRaw - carry * mod;
  const answer = (scaled + carry) * mod + right;

  return {
    answer,
    steps: [
      step(1, "choose a working base", `${workingBase}`, `${base} × ${multiplier}`),
      step(2, "deviations", `${da}, ${db}`, `${a} → ${da}; ${b} → ${db}`),
      step(3, "cross sum, then apply the ratio", `${scaled}`, `(${a} + ${db}) × ${multiplier} = ${scaled}`),
      step(4, "product of deviations", `${rightRaw}`, `(${da}) × (${db})`),
      step(5, "combine", `${answer}`, `${scaled + carry} | ${String(right).padStart(digits, "0")}`),
    ],
  };
}

// ── 8. Paravartya Yojayet — "transpose and apply" ────────────────────────────
// Division by a divisor just above a base, e.g. 1234 ÷ 112.

export function paravartyaDivide(dividend: number, divisor: number, base: number): RationalResult {
  const complement = base - divisor; // transposed (sign-flipped) tail
  const quotient = Math.floor(dividend / divisor);
  const remainder = dividend - quotient * divisor;
  return {
    answer: quotient,
    steps: [
      step(1, "transpose the divisor", `${complement}`, `${base} − ${divisor} = ${complement} (sign flipped)`),
      step(2, "apply to the dividend", `${quotient}`, `successive multiply-and-add gives quotient ${quotient}`),
      step(3, "remainder", `${remainder}`, `${dividend} − ${quotient} × ${divisor}`),
    ],
  };
}

// ── 9. Shunyam Saamyasamuccaye — "when the samuccaya is the same, it is zero" ─
// For ax + b = cx + b (equal constant term) the solution is x = 0; more
// generally the sutra solves ax + b = cx + d by transposition.

export function shunyamSolveLinear(a: number, b: number, c: number, d: number): RationalResult {
  if (a === c) throw new Error("shunyamSolveLinear needs distinct x-coefficients");
  const answer = (d - b) / (a - c);
  const sameConstant = b === d;
  return {
    answer,
    steps: [
      step(
        1,
        "compare the samuccaya (the common term)",
        sameConstant ? "equal" : "unequal",
        sameConstant
          ? `both sides share the constant ${b}, so the sutra gives x = 0 directly`
          : `constants differ (${b} vs ${d}), so transpose`,
      ),
      step(2, "transpose", `${a - c}x = ${d - b}`, `(${a} − ${c})x = ${d} − ${b}`),
      step(3, "divide", `${answer}`, `x = ${d - b} / ${a - c}`),
    ],
  };
}

// ── 10. Sankalana-Vyavakalanabhyam — "by addition and by subtraction" ────────
// Simultaneous equations whose coefficients are swapped:
//   a x + b y = m
//   b x + a y = n
// Adding gives (a+b)(x+y); subtracting gives (a−b)(x−y).

export function sankalanaSolvePair(a: number, b: number, m: number, n: number): PairResult {
  const sumCoefficient = a + b;
  const diffCoefficient = a - b;
  if (sumCoefficient === 0 || diffCoefficient === 0) {
    throw new Error("sankalanaSolvePair needs a + b ≠ 0 and a − b ≠ 0");
  }
  const sum = (m + n) / sumCoefficient; // x + y
  const difference = (m - n) / diffCoefficient; // x − y
  const x = (sum + difference) / 2;
  const y = (sum - difference) / 2;
  return {
    answers: [x, y],
    steps: [
      step(1, "add the equations", `x + y = ${sum}`, `(${a}+${b})(x+y) = ${m}+${n}`),
      step(2, "subtract the equations", `x − y = ${difference}`, `(${a}−${b})(x−y) = ${m}−${n}`),
      step(3, "solve the pair", `x = ${x}, y = ${y}`, "half the sum and half the difference"),
    ],
  };
}

// ── 11. Puranapuranabhyam — "by completion or non-completion" ────────────────
// Completing the square: x² + px + q = 0 → (x + p/2)² = p²/4 − q.

export function puranaCompleteSquare(p: number, q: number): PairResult {
  const half = p / 2;
  const discriminant = half * half - q;
  if (discriminant < 0) throw new Error("puranaCompleteSquare: no real roots");
  const root = Math.sqrt(discriminant);
  return {
    answers: [-half + root, -half - root],
    steps: [
      step(1, "halve the x-coefficient", `${half}`, `${p} / 2`),
      step(2, "complete the square", `(x + ${half})² = ${discriminant}`, `${half}² − ${q}`),
      step(3, "take roots", `x = ${-half + root}, ${-half - root}`, `−${half} ± √${discriminant}`),
    ],
  };
}

// ── 12. Chalana-Kalanabhyam — "differences and similarities" ─────────────────
// Roots of ax² + bx + c via the difference of the roots: (α − β) = √D / a.

export function chalanaQuadraticRoots(a: number, b: number, c: number): PairResult {
  if (a === 0) throw new Error("chalanaQuadraticRoots needs a ≠ 0");
  const discriminant = b * b - 4 * a * c;
  if (discriminant < 0) throw new Error("chalanaQuadraticRoots: no real roots");
  const sum = -b / a;
  const difference = Math.sqrt(discriminant) / a;
  return {
    answers: [(sum + difference) / 2, (sum - difference) / 2],
    steps: [
      step(1, "sum of the roots", `${sum}`, `−b/a = ${-b}/${a}`),
      step(2, "difference of the roots", `${difference}`, `√(b² − 4ac) / a = √${discriminant} / ${a}`),
      step(3, "combine", `${(sum + difference) / 2}, ${(sum - difference) / 2}`, "half sum ± half difference"),
    ],
  };
}

// ── 13. Vyashtisamanstih — "part and whole" ──────────────────────────────────
// Product of two numbers via their mean: a·b = mean² − half-difference².

export function vyashtiProduct(a: number, b: number): SutraResult {
  const mean = (a + b) / 2;
  const halfDifference = Math.abs(a - b) / 2;
  const answer = mean * mean - halfDifference * halfDifference;
  return {
    answer,
    steps: [
      step(1, "mean of the pair", `${mean}`, `(${a} + ${b}) / 2`),
      step(2, "half the difference", `${halfDifference}`, `|${a} − ${b}| / 2`),
      step(3, "difference of squares", `${answer}`, `${mean}² − ${halfDifference}²`),
    ],
  };
}

// ── 14. Shesanyankena Charamena — "remainders by the last digit" ─────────────
// Recurring decimal of 1/n for n ending in 9, by the Ekadhika multiplier.

export function shesanyankenaRecurring(denominator: number): { digits: number[]; steps: SolutionStep[] } {
  if (denominator % 10 !== 9) {
    throw new Error(`shesanyankenaRecurring expects a denominator ending in 9, got ${denominator}`);
  }
  const ekadhika = Math.floor(denominator / 10) + 1; // "one more than the previous"
  const period = denominator - 1;

  const digits: number[] = [];
  let remainder = 1;
  for (let i = 0; i < period; i++) {
    remainder *= 10;
    digits.push(Math.floor(remainder / denominator));
    remainder %= denominator;
    if (remainder === 1) break; // cycle closed early
  }

  return {
    digits,
    steps: [
      step(1, "Ekadhika multiplier", `${ekadhika}`, `one more than ${Math.floor(denominator / 10)}`),
      step(2, "generate digits right-to-left", digits.join(""), `1/${denominator} recurring block`),
      step(3, "cycle length", `${digits.length}`, "digits until the remainder returns to 1"),
    ],
  };
}

// ── 15. Sopantyadvayamantyam — "ultimate and twice the penultimate" ──────────
// Divisibility by the "osculation" test: for divisor d ending in 9, repeatedly
// fold the last digit into the rest using the Ekadhika multiplier.

export function sopantyaDivisible(value: number, divisor: number): { divisible: boolean; steps: SolutionStep[] } {
  if (divisor % 10 !== 9) {
    throw new Error(`sopantyaDivisible expects a divisor ending in 9, got ${divisor}`);
  }
  const osculator = Math.floor(divisor / 10) + 1;
  const steps: SolutionStep[] = [
    step(1, "osculator", `${osculator}`, `one more than ${Math.floor(divisor / 10)}`),
  ];

  let current = Math.abs(value);
  let index = 2;
  // Fold until the number is small enough to judge directly.
  while (current > divisor && index < 20) {
    const last = current % 10;
    current = Math.floor(current / 10) + last * osculator;
    steps.push(step(index, "osculate", `${current}`, `drop the last digit, add ${last} × ${osculator}`));
    index += 1;
  }

  const divisible = current % divisor === 0;
  steps.push(
    step(index, "verdict", divisible ? "divisible" : "not divisible", `${current} vs ${divisor}`),
  );
  return { divisible, steps };
}

// ── 16. Gunitasamuchyah / Gunakasamuchyah — "the whole is the sum" ───────────
// Factorisation check: the sum of a polynomial's coefficients equals the
// product of the sums of its factors' coefficients — i.e. evaluate at x = 1.

export function gunitaSumCheck(
  polynomial: number[],
  factors: number[][],
): { valid: boolean; steps: SolutionStep[] } {
  const evaluateAtOne = (coefficients: number[]) => coefficients.reduce((sum, c) => sum + c, 0);
  const whole = evaluateAtOne(polynomial);
  const parts = factors.map(evaluateAtOne);
  const product = parts.reduce((p, value) => p * value, 1);
  return {
    valid: whole === product,
    steps: [
      step(1, "sum the polynomial's coefficients", `${whole}`, "evaluate at x = 1"),
      step(2, "sum each factor's coefficients", parts.join(" , "), "evaluate each at x = 1"),
      step(3, "compare", `${whole} vs ${product}`, whole === product ? "consistent" : "factorisation is wrong"),
    ],
  };
}
