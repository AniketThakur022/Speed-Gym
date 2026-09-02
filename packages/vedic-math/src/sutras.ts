/**
 * Vedic sutra implementations — Sprint-2 parity set (5 of 16), each returning
 * the exact answer plus SolveAlong-shaped steps, and each self-verifiable
 * against plain arithmetic.
 */
import type { SolutionStep } from "@vmsg/shared-types";

export interface SutraResult {
  answer: number;
  steps: SolutionStep[];
}

function step(step_num: number, operation: string, result: string, description?: string): SolutionStep {
  return { step_num, operation, result, description };
}

/** Nikhilam Navatashcaramam Dashatah — multiplication near a base (100/1000…). */
export function nikhilamMultiply(a: number, b: number, base: number): SutraResult {
  const da = a - base; // deviation (negative below base, positive above)
  const db = b - base;
  const left = a + db; // equivalently b + da — cross sum
  const right = da * db;
  const digits = String(base).length - 1;
  const mod = Math.pow(10, digits);
  // Floor division carries correctly for negative deviation products
  // (e.g. 104×97: left 101, right −12 → carry −1, remainder 88 → 10088).
  const carry = Math.floor(right / mod);
  const rightPart = right - carry * mod;
  const leftPart = left + carry;
  const answer = leftPart * mod + rightPart;

  return {
    answer,
    steps: [
      step(1, `deviations from ${base}`, `${da}, ${db}`, `${a} is ${da >= 0 ? "+" : ""}${da}; ${b} is ${db >= 0 ? "+" : ""}${db}`),
      step(2, "cross sum", `${left}`, `${a} + (${db}) = ${left}`),
      step(3, "deviation product", `${da * db}`, `(${da}) × (${db}) = ${da * db}`),
      step(4, "combine", `${answer}`, `left ${leftPart} | right ${String(rightPart).padStart(digits, "0")}`),
    ],
  };
}

/** Urdhva-Tiryagbhyam (vertically and crosswise) for two 2-digit numbers. */
export function urdhvaMultiply2x2(a: number, b: number): SutraResult {
  const [a1, a0] = [Math.floor(a / 10), a % 10];
  const [b1, b0] = [Math.floor(b / 10), b % 10];

  const units = a0 * b0;
  const cross = a1 * b0 + a0 * b1;
  const tens = a1 * b1;

  const unitsDigit = units % 10;
  const carry1 = Math.floor(units / 10);
  const crossTotal = cross + carry1;
  const crossDigit = crossTotal % 10;
  const carry2 = Math.floor(crossTotal / 10);
  const high = tens + carry2;
  const answer = high * 100 + crossDigit * 10 + unitsDigit;

  return {
    answer,
    steps: [
      step(1, "vertical (units)", `${units}`, `${a0} × ${b0} = ${units}`),
      step(2, "crosswise", `${cross}`, `${a1}×${b0} + ${a0}×${b1} = ${cross}`),
      step(3, "vertical (tens)", `${tens}`, `${a1} × ${b1} = ${tens}`),
      step(4, "resolve carries", `${answer}`, `${tens}|${cross}|${units} → ${answer}`),
    ],
  };
}

/** Ekadhikena Purvena — squares of numbers ending in 5. */
export function squareEndingIn5(n: number): SutraResult {
  if (n % 10 !== 5) throw new Error(`squareEndingIn5 requires a number ending in 5, got ${n}`);
  const prefix = Math.floor(n / 10);
  const left = prefix * (prefix + 1);
  const answer = left * 100 + 25;
  return {
    answer,
    steps: [
      step(1, "one more than the previous", `${prefix + 1}`, `previous digit(s) ${prefix} → ${prefix + 1}`),
      step(2, "multiply", `${left}`, `${prefix} × ${prefix + 1} = ${left}`),
      step(3, "append 25", `${answer}`, `${left} | 25`),
    ],
  };
}

/** Yavadunam — squaring near a base: (n ± d)² = (n ± d) | d². */
export function yavadunamSquare(n: number, base: number): SutraResult {
  const dev = n - base;
  const left = n + dev; // n + deviation
  const right = dev * dev;
  const digits = String(base).length - 1;
  const mod = Math.pow(10, digits);
  const carry = Math.floor(right / mod);
  const answer = (left + carry) * mod + (right % mod);
  return {
    answer,
    steps: [
      step(1, `deviation from ${base}`, `${dev}`, `${n} = ${base} ${dev >= 0 ? "+" : "−"} ${Math.abs(dev)}`),
      step(2, "add the deviation again", `${left}`, `${n} + (${dev}) = ${left}`),
      step(3, "square the deviation", `${right}`, `(${dev})² = ${right}`),
      step(4, "combine", `${answer}`, `${left + carry} | ${String(right % mod).padStart(digits, "0")}`),
    ],
  };
}

/** Digital root (Navashesh) — repeated digit sum, with the casting-out-nines check. */
export function digitalRoot(n: number): SutraResult {
  const stepsOut: SolutionStep[] = [];
  let value = Math.abs(n);
  let i = 1;
  while (value >= 10) {
    const digits = String(value).split("").map(Number);
    const sum = digits.reduce((s, d) => s + d, 0);
    stepsOut.push(step(i, "digit sum", `${sum}`, `${digits.join(" + ")} = ${sum}`));
    value = sum;
    i += 1;
  }
  if (stepsOut.length === 0) {
    stepsOut.push(step(1, "single digit", `${value}`, `${n} is already a single digit`));
  }
  return { answer: value, steps: stepsOut };
}

/** Casting-out-nines product check: dr(dr(a)·dr(b)) must equal dr(a·b). */
export function digitalRootCheck(a: number, b: number, claimedProduct: number): boolean {
  const dr = (x: number) => digitalRoot(x).answer;
  return dr(dr(a) * dr(b)) === dr(claimedProduct);
}
