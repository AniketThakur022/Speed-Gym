import { describe, expect, it } from "vitest";
import { mulberry32, generateSet, TECHNIQUE_IDS, GeneratedProblem } from "../src/index.js";

/** Independent re-derivation — plain arithmetic, no sutra code. */
function independentAnswer(p: GeneratedProblem): number {
  switch (p.techniqueId) {
    case "nikhilam-base-100":
    case "urdhva-2digit":
      return p.params.a * p.params.b;
    case "square-ending-5":
    case "yavadunam-100":
      return p.params.n * p.params.n;
    case "digital-root":
      return p.params.n === 0 ? 0 : 1 + ((p.params.n - 1) % 9); // closed form
    default:
      throw new Error(`no independent derivation for ${p.techniqueId}`);
  }
}

describe("seeded parametric generators (mulberry32)", () => {
  it("mulberry32 is deterministic per seed and emits values in [0, 1)", () => {
    const a = mulberry32(42);
    const b = mulberry32(42);
    const c = mulberry32(43);
    const seqA = [a(), a(), a(), a(), a()];
    const seqB = [b(), b(), b(), b(), b()];
    expect(seqA).toEqual(seqB);
    expect(seqA).not.toEqual([c(), c(), c(), c(), c()]);
    for (const v of seqA) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });

  it("same (technique, seed, difficulty) reproduces an identical problem set", () => {
    const first = generateSet("nikhilam-base-100", 10, 1234, 2);
    const second = generateSet("nikhilam-base-100", 10, 1234, 2);
    expect(first).toEqual(second);
    expect(generateSet("nikhilam-base-100", 10, 999, 2)).not.toEqual(first);
  });

  it("625 generated problems re-derive exactly (5 techniques × 5 difficulties × 25)", () => {
    let total = 0;
    for (const techniqueId of TECHNIQUE_IDS) {
      for (let difficulty = 1; difficulty <= 5; difficulty++) {
        const problems = generateSet(techniqueId, 25, difficulty * 1000 + 7, difficulty);
        for (const p of problems) {
          expect(p.answer).toBe(independentAnswer(p));
          total += 1;
        }
      }
    }
    expect(total).toBe(625);
  });

  it("generated parameters respect their difficulty windows", () => {
    for (const p of generateSet("nikhilam-base-100", 50, 5, 1)) {
      expect(Math.abs(p.params.a - 100)).toBeLessThanOrEqual(3);
      expect(Math.abs(p.params.b - 100)).toBeLessThanOrEqual(3);
    }
    for (const p of generateSet("urdhva-2digit", 50, 5, 5)) {
      expect(p.params.a).toBeGreaterThanOrEqual(70);
      expect(p.params.a).toBeLessThanOrEqual(90);
    }
  });

  it("every generated problem's final solve-along step states the answer", () => {
    for (const techniqueId of TECHNIQUE_IDS) {
      for (const p of generateSet(techniqueId, 5, 77, 3)) {
        const last = p.steps[p.steps.length - 1];
        expect(Number(last.result)).toBe(p.answer);
      }
    }
  });
});
