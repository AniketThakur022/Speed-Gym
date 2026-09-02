/**
 * On-device answer checking.
 *
 * The practice loop runs offline, so items the server marked
 * `answer_check: "client_extract"` are graded here with no network. Items
 * marked `server_sympy` are deferred — never guessed at locally, because
 * marking a correct learner wrong is far more damaging than a round-trip.
 */

export type CheckOutcome = "correct" | "incorrect" | "deferred" | "unparsable";

export type CheckResult = {
  outcome: CheckOutcome;
  parsed: number | null;
};

/** Accepts plain numbers, thousands separators, and mixed forms like "4 1/2". */
export function parseLearnerAnswer(input: string): number | null {
  const text = input.trim().replace(/,/g, "");
  if (!text) return null;

  const mixed = text.match(/^(-?\d+)\s+(\d+)\s*\/\s*(\d+)$/);
  if (mixed) {
    const [, whole, numerator, denominator] = mixed;
    const den = Number(denominator);
    if (den === 0) return null;
    const magnitude = Math.abs(Number(whole)) + Number(numerator) / den;
    return whole.startsWith("-") ? -magnitude : magnitude;
  }

  const fraction = text.match(/^(-?\d+)\s*\/\s*(\d+)$/);
  if (fraction) {
    const den = Number(fraction[2]);
    return den === 0 ? null : Number(fraction[1]) / den;
  }

  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/**
 * Compare with a relative tolerance so a learner who rounds a repeating
 * decimal at a sensible place is not marked wrong.
 */
export function checkAnswer(
  input: string,
  expected: number | null,
  answerCheck: "client_extract" | "server_sympy",
): CheckResult {
  const parsed = parseLearnerAnswer(input);
  if (answerCheck === "server_sympy" || expected === null) {
    return { outcome: "deferred", parsed };
  }
  if (parsed === null) return { outcome: "unparsable", parsed: null };

  const tolerance = Math.max(1e-9, Math.abs(expected) * 1e-6);
  return {
    outcome: Math.abs(parsed - expected) <= tolerance ? "correct" : "incorrect",
    parsed,
  };
}
