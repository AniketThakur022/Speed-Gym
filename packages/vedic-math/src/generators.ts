/**
 * Seeded parametric generators — mulberry32 PRNG (deterministic, re-derivable)
 * feeding the 5 implemented sutras. Tier-2 generative runtime, PRACTICE-only.
 */
import type { SolutionStep } from "@vmsg/shared-types";
import {
  nikhilamMultiply,
  urdhvaMultiply2x2,
  squareEndingIn5,
  yavadunamSquare,
  digitalRoot,
} from "./sutras";

/** mulberry32 — tiny, fast, deterministic 32-bit PRNG. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function randInt(rng: () => number, min: number, max: number): number {
  return min + Math.floor(rng() * (max - min + 1));
}

export interface GeneratedProblem {
  techniqueId: string;
  difficulty: number;
  problemText: string;
  params: Record<string, number>;
  answer: number;
  steps: SolutionStep[];
}

type Generator = (rng: () => number, difficulty: number) => GeneratedProblem;

/** Deviation window per difficulty for near-base techniques. */
function baseWindow(difficulty: number): number {
  return [0, 3, 6, 9, 12, 15][difficulty] ?? 9;
}

const nikhilamBase100: Generator = (rng, difficulty) => {
  const w = baseWindow(difficulty);
  const a = 100 + (randInt(rng, 1, w) * (rng() < 0.5 ? -1 : 1));
  const b = 100 + (randInt(rng, 1, w) * (rng() < 0.5 ? -1 : 1));
  const { answer, steps } = nikhilamMultiply(a, b, 100);
  return {
    techniqueId: "nikhilam-base-100",
    difficulty,
    problemText: `${a} × ${b}`,
    params: { a, b, base: 100 },
    answer,
    steps,
  };
};

const urdhva2Digit: Generator = (rng, difficulty) => {
  const lo = 10 + (difficulty - 1) * 15;
  const hi = Math.min(99, lo + 20);
  const a = randInt(rng, lo, hi);
  const b = randInt(rng, lo, hi);
  const { answer, steps } = urdhvaMultiply2x2(a, b);
  return {
    techniqueId: "urdhva-2digit",
    difficulty,
    problemText: `${a} × ${b}`,
    params: { a, b },
    answer,
    steps,
  };
};

const square5: Generator = (rng, difficulty) => {
  const prefix = randInt(rng, 1 + (difficulty - 1) * 3, 9 + (difficulty - 1) * 12);
  const n = prefix * 10 + 5;
  const { answer, steps } = squareEndingIn5(n);
  return {
    techniqueId: "square-ending-5",
    difficulty,
    problemText: `${n}²`,
    params: { n },
    answer,
    steps,
  };
};

const yavadunam100: Generator = (rng, difficulty) => {
  const w = baseWindow(difficulty);
  const n = 100 + randInt(rng, 1, w) * (rng() < 0.5 ? -1 : 1);
  const { answer, steps } = yavadunamSquare(n, 100);
  return {
    techniqueId: "yavadunam-100",
    difficulty,
    problemText: `${n}²`,
    params: { n, base: 100 },
    answer,
    steps,
  };
};

const digitalRootGen: Generator = (rng, difficulty) => {
  const magnitude = Math.pow(10, difficulty + 1);
  const n = randInt(rng, magnitude, magnitude * 9);
  const { answer, steps } = digitalRoot(n);
  return {
    techniqueId: "digital-root",
    difficulty,
    problemText: `digital root of ${n}`,
    params: { n },
    answer,
    steps,
  };
};

export const GENERATORS: Record<string, Generator> = {
  "nikhilam-base-100": nikhilamBase100,
  "urdhva-2digit": urdhva2Digit,
  "square-ending-5": square5,
  "yavadunam-100": yavadunam100,
  "digital-root": digitalRootGen,
};

export const TECHNIQUE_IDS = Object.keys(GENERATORS);

/** Deterministic problem set: same (technique, seed, difficulty, count) →
 *  byte-identical problems, so the server can re-derive and audit any set. */
export function generateSet(
  techniqueId: string,
  count: number,
  seed: number,
  difficulty: number,
): GeneratedProblem[] {
  const generator = GENERATORS[techniqueId];
  if (!generator) throw new Error(`unknown technique: ${techniqueId}`);
  const rng = mulberry32(seed);
  return Array.from({ length: count }, () => generator(rng, difficulty));
}
