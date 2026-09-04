/**
 * Bot backfill for the duel lobby.
 *
 * Bots solve the empty-lobby problem: without them a learner who queues at a
 * quiet hour waits forever. They are also the single most compliance-sensitive
 * part of this server, because a bot is presented to the learner as an
 * opponent. The rules below are not styling choices — they come from the
 * architecture's compliance section and are enforced here rather than left to
 * each call site:
 *
 *   1. NEVER offer a bot to an under-13 account (COPPA).
 *   2. Ids must be human-plausible — never `bot_<uuid>`.
 *   3. `isBot` / `persona` never cross the API boundary to a client.
 *   4. Bot-round rating changes are weighted 0.5x.
 *   5. No bots in the daily challenge or ranked tournaments.
 *
 * Determinism: every function takes an `rng` so behaviour is reproducible in
 * tests. Bot timing must never be perfectly regular, but it must be testable.
 */

export type BotPersona = "overthinker" | "speedster" | "improver" | "choker";

/** Personas the duel uses. `speedster` exists in the wider spec but the duel's
 *  named set is these three; keeping the type wider avoids a cast elsewhere. */
export const DUEL_PERSONAS: BotPersona[] = ["overthinker", "improver", "choker"];

export const MIN_AGE_FOR_BOTS = 13;
export const BOT_ELO_WEIGHT = 0.5;
export const TARGET_BOT_WIN_RATE = 0.45;
export const MAX_BOTS_PER_DUEL = 1;
export const MIN_SOLVE_MS = 3000;

/** Names read as ordinary handles. A learner must not be able to identify a bot
 *  from its id — an id like `bot_9f2` is a disclosure by accident. */
const NAME_POOL = [
  "arjun", "priya", "rohan", "meera", "kabir", "ananya", "vikram", "diya",
  "aditya", "sneha", "karan", "riya", "nikhil", "isha", "varun", "tara",
];

export interface BotProfile {
  userId: string;
  displayName: string;
  thetaU: number;
  elo: number;
  cluster: "balanced";
  latencyMs: number;
  /** INTERNAL ONLY. Must be stripped before anything reaches a client. */
  isBot: true;
  /** INTERNAL ONLY. */
  persona: BotPersona;
}

export interface EligibilityResult {
  allowed: boolean;
  reason?: string;
}

/**
 * Whether this player may be matched against a bot at all.
 *
 * Age is required, not optional: an unknown age is treated as ineligible.
 * Defaulting an absent age to "adult" would let a mis-recorded child profile
 * silently pass the COPPA gate, and the cost of being wrong is a compliance
 * breach rather than a longer queue.
 */
export function botsAllowedFor(params: {
  age?: number | null;
  mode: string;
  isRankedTournament?: boolean;
}): EligibilityResult {
  const { age, mode, isRankedTournament } = params;

  if (age === undefined || age === null) {
    return { allowed: false, reason: "age unknown — cannot confirm the COPPA gate" };
  }
  if (age < MIN_AGE_FOR_BOTS) {
    return { allowed: false, reason: `under ${MIN_AGE_FOR_BOTS}: bots are disabled for kids accounts` };
  }
  if (mode === "daily_challenge") {
    return { allowed: false, reason: "bots would distort global daily-challenge percentiles" };
  }
  if (isRankedTournament) {
    return { allowed: false, reason: "no bots in ranked tournaments" };
  }
  return { allowed: true };
}

/** Median of the waiting players' ability, with bounded jitter (±0.1 absolute). */
export function botTheta(waitingThetas: number[], rng: () => number): number {
  if (waitingThetas.length === 0) return 0;
  const sorted = [...waitingThetas].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
  return median + (rng() * 0.2 - 0.1);
}

export function makeBot(waitingThetas: number[], rng: () => number): BotProfile {
  const theta = botTheta(waitingThetas, rng);
  const persona = DUEL_PERSONAS[Math.floor(rng() * DUEL_PERSONAS.length)];
  const name = NAME_POOL[Math.floor(rng() * NAME_POOL.length)];
  // A short numeric suffix keeps ids unique while still reading like a handle.
  const suffix = Math.floor(rng() * 9000) + 1000;
  return {
    userId: `${name}${suffix}`,
    displayName: `${name.charAt(0).toUpperCase()}${name.slice(1)}`,
    thetaU: theta,
    elo: Math.min(2400, Math.max(600, 1000 + 400 * theta)),
    cluster: "balanced",
    latencyMs: 30 + rng() * 50, // uniform(30, 80)
    isBot: true,
    persona,
  };
}

/**
 * Strip every internal marker before a profile can reach a client.
 *
 * This is the API boundary rule in code form: the returned object has no
 * `isBot` and no `persona`, so a serialization mistake cannot leak them.
 */
export function publicOpponent(profile: BotProfile | { userId: string; displayName?: string; thetaU: number }): {
  user_id: string;
  display_name?: string;
  theta_u: number;
} {
  return {
    user_id: profile.userId,
    display_name: (profile as BotProfile).displayName,
    theta_u: profile.thetaU,
  };
}

// ── Solve simulation ────────────────────────────────────────────────────────

/** Box–Muller, so timing is normally distributed rather than uniform. */
function gaussian(rng: () => number, mean: number, stdDev: number): number {
  const u = Math.max(rng(), 1e-9);
  const v = rng();
  return mean + stdDev * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export interface BotAttempt {
  correct: boolean;
  solveTimeMs: number;
}

/**
 * Whether the bot answers correctly, from a 1PL/Rasch curve on
 * (ability − difficulty), with persona adjustments.
 *
 * `choker` deliberately fails hard problems: it has a 70% chance of a wrong
 * answer once difficulty passes 4.0, which is what makes it feel like a human
 * who tightens up rather than a curve.
 */
export function botAnswersCorrectly(
  persona: BotPersona,
  thetaBot: number,
  difficulty: number,
  rng: () => number,
): boolean {
  if (persona === "choker" && difficulty > 4.0) {
    return rng() > 0.7;
  }
  let ability = thetaBot;
  if (persona === "improver") ability += 0.15; // warms up over a match
  if (persona === "overthinker") ability += 0.1; // accurate, just slow
  const pCorrect = 1 / (1 + Math.exp(-(ability - difficulty)));
  return rng() < pCorrect;
}

/**
 * How long the bot "takes". Never below a 3s floor: a sub-second answer would
 * trip the server's own anti-cheat and, more importantly, reads as a machine.
 */
export function botSolveTimeMs(
  persona: BotPersona,
  baseTimeMs: number,
  rng: () => number,
): number {
  let base = baseTimeMs;
  if (persona === "overthinker") base *= 1.6;
  if (persona === "speedster") base *= 0.6;

  const jittered = gaussian(rng, base, 3000);
  // Humans backspace and hesitate; a clean distribution looks synthetic.
  const backspaces = rng() < 0.25 ? 2000 : 0;
  const hesitation = rng() < 0.35 ? 1500 : 0;
  return Math.max(MIN_SOLVE_MS, Math.round(jittered + backspaces + hesitation));
}

export function simulateBotAttempt(
  bot: BotProfile,
  difficulty: number,
  baseTimeMs: number,
  rng: () => number,
): BotAttempt {
  return {
    correct: botAnswersCorrectly(bot.persona, bot.thetaU, difficulty, rng),
    solveTimeMs: botSolveTimeMs(bot.persona, baseTimeMs, rng),
  };
}

/**
 * Rating change against a bot counts for half.
 *
 * A bot is a calibrated approximation of an opponent, not an opponent, so a
 * result against one should move a learner's rating less than a real match.
 */
export function weightBotEloChange(change: number): number {
  const scaled = change * BOT_ELO_WEIGHT;
  // Round half AWAY FROM ZERO, symmetrically. Math.round breaks ties toward
  // +Infinity, so -15.5 becomes -15 while +15.5 becomes +16 — losses would be
  // shaved and gains rounded up, a small bias in the player's favour that
  // compounds over many bot rounds.
  return Math.sign(scaled) * Math.round(Math.abs(scaled));
}
