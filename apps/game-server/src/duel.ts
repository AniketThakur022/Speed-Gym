/**
 * Accuracy Duel — the turn-based elimination match.
 * Source: gaming/PHASE_B_DESIGN.md §1.6 (FSM), §2.2 (scoring), §2.5
 * (validation), §3.1 (difficulty); gaming/BACKEND_ARCHITECTURE.md §3.7
 * (disconnect). Pure logic, no sockets — so the rules are testable on their own.
 *
 * The duel is decided by ELIMINATION, not by score: one wrong answer (or a
 * timeout, or a disconnect past grace) ends it. Scores are still computed
 * because they feed the leaderboard and match history.
 */

export type DuelPhase = "waiting" | "countdown" | "active" | "sudden_death" | "completed" | "aborted";
export type EliminationReason = "wrong_answer" | "timeout" | "forfeit";

export const COUNTDOWN_SECONDS = 5;
export const BASE_PROBLEM_MS = 30_000;
export const DUEL_TIMER_MULTIPLIER = 1.5;
export const SUDDEN_DEATH_AFTER_ROUND = 10;
export const DISCONNECT_GRACE_MS = 15_000;
export const HEARTBEAT_TIMEOUT_MS = 10_000;

/** No hard duel timeout exists in any spec (Speed Race has 5 minutes; sudden
 *  death is explicitly uncapped). An unbounded match can pin a server slot
 *  forever, so we cap it and record the choice as ours, not the spec's. */
export const MATCH_HARD_TIMEOUT_MS = 15 * 60_000;

export const AGE_MULTIPLIERS: ReadonlyArray<{ min: number; max: number; multiplier: number }> = [
  { min: 8, max: 10, multiplier: 2.5 },
  { min: 11, max: 13, multiplier: 2.0 },
  { min: 14, max: 17, multiplier: 1.5 },
  { min: 18, max: 25, multiplier: 1.0 },
  { min: 26, max: 40, multiplier: 1.2 },
  { min: 41, max: 60, multiplier: 1.5 },
  { min: 61, max: 200, multiplier: 2.0 },
];

export function ageMultiplier(age: number): number {
  return AGE_MULTIPLIERS.find(({ min, max }) => age >= min && age <= max)?.multiplier ?? 1.0;
}

/** Per-turn allowance: base × age × the duel's 1.5 handicap. */
export function turnTimeLimitMs(age: number): number {
  return Math.round(BASE_PROBLEM_MS * ageMultiplier(age) * DUEL_TIMER_MULTIPLIER);
}

/** d₀ = floor(mean θ); +0.5 per round, +1.0 once in sudden death. */
export function roundDifficulty(thetaA: number, thetaB: number, roundNumber: number): number {
  const base = Math.floor((thetaA + thetaB) / 2);
  if (roundNumber <= SUDDEN_DEATH_AFTER_ROUND) {
    return base + 0.5 * (roundNumber - 1);
  }
  const atCutover = base + 0.5 * (SUDDEN_DEATH_AFTER_ROUND - 1);
  return atCutover + 1.0 * (roundNumber - SUDDEN_DEATH_AFTER_ROUND);
}

/** Lower ability answers first, so the weaker player is never handed the
 *  higher escalated difficulty by turn order alone. */
export function firstMover(a: { userId: string; thetaU: number }, b: { userId: string; thetaU: number }): string {
  return a.thetaU <= b.thetaU ? a.userId : b.userId;
}

// ── Anti-cheat (§2.5) ───────────────────────────────────────────────────────

export type AntiCheatFlag = "IMPOSSIBLE_SPEED" | "TIMING_ANOMALY";

export interface ValidationResult {
  correct: boolean;
  flagged: boolean;
  reason?: AntiCheatFlag;
  solveTimeMs: number;
}

export function normalizeAnswer(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, "").replace(/,/g, "");
}

/**
 * Server-authoritative validation. Flags are advisory: the spec never says a
 * flagged answer should be rejected, and silently voiding a fast correct answer
 * would punish genuinely quick learners, so `correct` is left untouched and the
 * flag is carried for review.
 */
export function validateAnswer(params: {
  submitted: string;
  expected: string;
  thetaU: number;
  problemSentAtMs: number;
  clientTimestampMs: number;
}): ValidationResult {
  const { submitted, expected, thetaU, problemSentAtMs, clientTimestampMs } = params;
  const correct = normalizeAnswer(submitted) === normalizeAnswer(expected);
  const solveTimeMs = clientTimestampMs - problemSentAtMs;

  if (solveTimeMs < 800) {
    return { correct, flagged: true, reason: "IMPOSSIBLE_SPEED", solveTimeMs };
  }
  if (solveTimeMs < 2000 && thetaU < 0.5) {
    return { correct, flagged: true, reason: "TIMING_ANOMALY", solveTimeMs };
  }
  return { correct, flagged: false, solveTimeMs };
}

// ── Scoring (§2.2) ──────────────────────────────────────────────────────────

export interface PlayerTally {
  userId: string;
  problemsAttempted: number;
  problemsCorrect: number;
  totalTimeMs: number;
  trapsTriggered: number;
}

export interface PlayerOutcome extends PlayerTally {
  rank: number;
  isWinner: boolean;
  positionPoints: number;
  accuracyBonus: number;
  finalScore: number;
  accuracyPct: number;
  avgTimeMs: number;
}

/**
 * Position points (rank 1 of N scores N) plus an accuracy bonus of +2 per
 * correct and −1 per wrong. The published formula is written for Speed Race;
 * there is no duel-specific scoring anywhere in the corpus, so this applies it
 * at N = 2 — winner 2 points, loser 1 — which is an inference, not a quote.
 */
export function scoreDuel(
  players: [PlayerTally, PlayerTally],
  winnerUserId: string,
): [PlayerOutcome, PlayerOutcome] {
  const total = players.length;
  const outcomes = players.map((tally) => {
    const isWinner = tally.userId === winnerUserId;
    const rank = isWinner ? 1 : 2;
    const positionPoints = total - rank + 1;
    const wrong = tally.problemsAttempted - tally.problemsCorrect;
    const accuracyBonus = tally.problemsCorrect * 2 - wrong;
    return {
      ...tally,
      rank,
      isWinner,
      positionPoints,
      accuracyBonus,
      finalScore: positionPoints + accuracyBonus,
      accuracyPct: tally.problemsAttempted
        ? (tally.problemsCorrect / tally.problemsAttempted) * 100
        : 0,
      avgTimeMs: tally.problemsAttempted ? tally.totalTimeMs / tally.problemsAttempted : 0,
    };
  });
  return outcomes as [PlayerOutcome, PlayerOutcome];
}

/** Tiebreak for equal scores: accuracy, then speed, then fewer traps (§2.2). */
export function breakTie(a: PlayerOutcome, b: PlayerOutcome): number {
  if (a.accuracyPct !== b.accuracyPct) return b.accuracyPct - a.accuracyPct;
  if (a.avgTimeMs !== b.avgTimeMs) return a.avgTimeMs - b.avgTimeMs;
  return a.trapsTriggered - b.trapsTriggered;
}

// ── Match state machine ─────────────────────────────────────────────────────

export interface DuelPlayer {
  userId: string;
  thetaU: number;
  age: number;
  connected: boolean;
  disconnectedAtMs?: number;
  tally: PlayerTally;
}

export interface DuelMatch {
  matchId: string;
  phase: DuelPhase;
  players: [DuelPlayer, DuelPlayer];
  roundNumber: number;
  activeUserId: string;
  problemSentAtMs?: number;
  startedAtMs: number;
  winnerUserId?: string;
  eliminationReason?: EliminationReason;
}

/** Redis/match id format from GAME_STATE_SCHEMA validation: ad_YYYYMMDD_NNN. */
export function makeMatchId(date: Date, sequence: number): string {
  const stamp =
    `${date.getUTCFullYear()}` +
    `${String(date.getUTCMonth() + 1).padStart(2, "0")}` +
    `${String(date.getUTCDate()).padStart(2, "0")}`;
  return `ad_${stamp}_${String(sequence).padStart(3, "0")}`;
}

export function createMatch(
  matchId: string,
  a: Omit<DuelPlayer, "tally" | "connected">,
  b: Omit<DuelPlayer, "tally" | "connected">,
  nowMs: number,
): DuelMatch {
  const blank = (userId: string): PlayerTally => ({
    userId,
    problemsAttempted: 0,
    problemsCorrect: 0,
    totalTimeMs: 0,
    trapsTriggered: 0,
  });
  return {
    matchId,
    phase: "countdown",
    players: [
      { ...a, connected: true, tally: blank(a.userId) },
      { ...b, connected: true, tally: blank(b.userId) },
    ],
    roundNumber: 0,
    activeUserId: firstMover(a, b),
    startedAtMs: nowMs,
  };
}

export function opponentOf(match: DuelMatch, userId: string): DuelPlayer {
  return match.players[0].userId === userId ? match.players[1] : match.players[0];
}

export function playerOf(match: DuelMatch, userId: string): DuelPlayer | undefined {
  return match.players.find((p) => p.userId === userId);
}

export interface RoundStart {
  matchId: string;
  round_number: number;
  activeUserId: string;
  difficulty: number;
  time_limit_ms: number;
}

export function beginRound(match: DuelMatch, nowMs: number): RoundStart {
  match.roundNumber += 1;
  match.phase = match.roundNumber > SUDDEN_DEATH_AFTER_ROUND ? "sudden_death" : "active";
  match.problemSentAtMs = nowMs;
  const active = playerOf(match, match.activeUserId)!;
  return {
    matchId: match.matchId,
    round_number: match.roundNumber,
    activeUserId: match.activeUserId,
    difficulty: roundDifficulty(match.players[0].thetaU, match.players[1].thetaU, match.roundNumber),
    time_limit_ms: turnTimeLimitMs(active.age),
  };
}

export interface RoundResolution {
  correct: boolean;
  flagged: boolean;
  flagReason?: AntiCheatFlag;
  matchOver: boolean;
  winnerUserId?: string;
  eliminationReason?: EliminationReason;
  nextActiveUserId?: string;
}

/** Resolve one submitted answer: correct hands the turn over, wrong ends it. */
export function resolveAnswer(
  match: DuelMatch,
  userId: string,
  submitted: string,
  expected: string,
  clientTimestampMs: number,
): RoundResolution {
  if (userId !== match.activeUserId) {
    throw new Error("NOT_YOUR_TURN");
  }
  const player = playerOf(match, userId)!;
  const result = validateAnswer({
    submitted,
    expected,
    thetaU: player.thetaU,
    problemSentAtMs: match.problemSentAtMs ?? clientTimestampMs,
    clientTimestampMs,
  });

  player.tally.problemsAttempted += 1;
  player.tally.totalTimeMs += Math.max(0, result.solveTimeMs);
  if (result.correct) player.tally.problemsCorrect += 1;

  if (!result.correct) {
    return {
      ...eliminate(match, userId, "wrong_answer"),
      correct: false,
      flagged: result.flagged,
      flagReason: result.reason,
    };
  }

  match.activeUserId = opponentOf(match, userId).userId;
  return {
    correct: true,
    flagged: result.flagged,
    flagReason: result.reason,
    matchOver: false,
    nextActiveUserId: match.activeUserId,
  };
}

function eliminate(match: DuelMatch, userId: string, reason: EliminationReason) {
  const winner = opponentOf(match, userId);
  match.phase = "completed";
  match.winnerUserId = winner.userId;
  match.eliminationReason = reason;
  return { matchOver: true, winnerUserId: winner.userId, eliminationReason: reason };
}

/** Turn timer expiry counts as a wrong answer (§1.6). */
export function expireTurn(match: DuelMatch): RoundResolution {
  const player = playerOf(match, match.activeUserId)!;
  player.tally.problemsAttempted += 1;
  return {
    ...eliminate(match, match.activeUserId, "timeout"),
    correct: false,
    flagged: false,
  };
}

export function markDisconnected(match: DuelMatch, userId: string, nowMs: number): void {
  const player = playerOf(match, userId);
  if (!player) return;
  player.connected = false;
  player.disconnectedAtMs = nowMs;
}

export function markReconnected(match: DuelMatch, userId: string): void {
  const player = playerOf(match, userId);
  if (!player) return;
  player.connected = true;
  player.disconnectedAtMs = undefined;
}

/** Forfeit once the 15s grace elapses; the timer is paused meanwhile. */
export function checkDisconnectForfeit(match: DuelMatch, nowMs: number): RoundResolution | null {
  for (const player of match.players) {
    if (
      !player.connected &&
      player.disconnectedAtMs !== undefined &&
      nowMs - player.disconnectedAtMs >= DISCONNECT_GRACE_MS
    ) {
      return { ...eliminate(match, player.userId, "forfeit"), correct: false, flagged: false };
    }
  }
  return null;
}
