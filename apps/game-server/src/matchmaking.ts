/**
 * Matchmaking — composite skill score, widening skill band, fairness gate.
 * Source: gaming/PHASE_B_DESIGN.md §5.1–§5.5 (the ratified Phase B spec;
 * multiplayer/MULTIPLAYER_GAMING_ENGINE.md is the superseded earlier design
 * and uses an unnormalized score — deliberately not followed).
 *
 * Two defects in the spec's own pseudocode are corrected here, both noted
 * inline: the skill band was computed from an absolute timestamp, and the
 * candidate sort demoted the players it claimed to prioritise.
 */

export type Cluster = "sprinter" | "deliberate" | "perfectionist" | "balanced" | "rebuilder" | "wanderer";

export interface MatchmakingProfile {
  userId: string;
  thetaU: number; // [-3, 3]
  elo: number; // [600, 2400]
  cluster: Cluster;
  latencyMs: number;
  queueJoinTimeMs: number;
}

export const SKILL_BAND_BASE = 0.15;
export const SKILL_BAND_MAX = 0.5;
export const MAX_THETA_DELTA = 0.5;
export const MAX_LATENCY_DELTA_MS = 200;
export const BOT_BACKFILL_AFTER_SECONDS = 60;

/** Normalized composite: 0.4·θ̂ + 0.6·êlo, both mapped to [0,1] (§5.1). */
export function compositeScore(profile: Pick<MatchmakingProfile, "thetaU" | "elo">): number {
  const thetaNorm = (profile.thetaU + 3) / 6;
  const eloNorm = (profile.elo - 600) / 1800;
  return 0.4 * thetaNorm + 0.6 * eloNorm;
}

/** ELO seed from ability: 1000 + 400·θ, clamped to the rating floor/ceiling (§5.2). */
export function seedElo(thetaU: number): number {
  return Math.min(2400, Math.max(600, 1000 + 400 * thetaU));
}

/**
 * Search band widens with waiting time: 0.15 + 0.05 per minute, capped 0.50.
 *
 * The spec passes `player.queue_join_time` (an absolute epoch) into this
 * function, which saturates the band at the cap immediately and effectively
 * disables skill matching. This takes ELAPSED seconds, as the table of
 * worked values in §5.3 intends.
 */
export function currentSkillBand(waitSeconds: number): number {
  const band = SKILL_BAND_BASE + (Math.max(0, waitSeconds) / 60) * 0.05;
  return Math.min(band, SKILL_BAND_MAX);
}

/** Cluster pairs that play so differently the match feels unfair (§5.4). */
const INCOMPATIBLE_CLUSTERS: ReadonlyArray<readonly [Cluster, Cluster]> = [
  ["deliberate", "sprinter"],
  ["perfectionist", "sprinter"],
];

function clustersIncompatible(a: Cluster, b: Cluster): boolean {
  const pair = [a, b].sort() as [Cluster, Cluster];
  return INCOMPATIBLE_CLUSTERS.some(([x, y]) => x === pair[0] && y === pair[1]);
}

export interface FairnessResult {
  fair: boolean;
  reason?: string;
}

/**
 * @param waitSeconds how long the searching player has queued — after 120s the
 * cluster rule is relaxed rather than leaving them unmatched. The spec notes
 * this override in a comment but never implements it; without it a sprinter
 * facing a lobby of deliberates waits forever.
 */
export function isFairMatch(
  player: MatchmakingProfile,
  candidate: MatchmakingProfile,
  waitSeconds = 0,
): FairnessResult {
  if (player.userId === candidate.userId) {
    return { fair: false, reason: "same player" };
  }
  if (Math.abs(player.thetaU - candidate.thetaU) > MAX_THETA_DELTA) {
    return { fair: false, reason: "theta delta > 0.5" };
  }
  if (clustersIncompatible(player.cluster, candidate.cluster) && waitSeconds < 120) {
    return { fair: false, reason: `incompatible clusters ${player.cluster}/${candidate.cluster}` };
  }
  if (Math.abs(player.latencyMs - candidate.latencyMs) > MAX_LATENCY_DELTA_MS) {
    return { fair: false, reason: "latency delta > 200ms" };
  }
  return { fair: true };
}

/**
 * Rank candidates: closest skill first, with a bounded nudge toward players who
 * have waited longest.
 *
 * The spec sorts on `score * 0.7 + waitBonus * 0.3` ascending with waitBonus in
 * raw seconds — mixing a [0,1] skill delta with an unbounded quantity, so after
 * a couple of seconds the wait term dominates, and because the sort is
 * ascending it puts the LONGEST-waiting candidates last: the opposite of the
 * stated intent. Normalising the wait to [0,1] and subtracting it keeps both
 * terms comparable and actually prioritises waiting players.
 */
export function rankCandidates(
  player: MatchmakingProfile,
  candidates: MatchmakingProfile[],
  nowMs: number,
): MatchmakingProfile[] {
  const playerScore = compositeScore(player);
  return [...candidates]
    .map((candidate) => {
      const skillDelta = Math.abs(compositeScore(candidate) - playerScore);
      const waitSeconds = Math.max(0, (nowMs - candidate.queueJoinTimeMs) / 1000);
      const waitNorm = Math.min(waitSeconds / 120, 1); // saturates at 2 minutes
      return { candidate, rank: skillDelta * 0.7 - waitNorm * 0.3 };
    })
    .sort((a, b) => a.rank - b.rank)
    .map(({ candidate }) => candidate);
}

export interface MatchDecision {
  type: "matched" | "waiting" | "bot_fill";
  opponent?: MatchmakingProfile;
  estimatedWaitSeconds?: number;
}

/** One matchmaking tick for a searching player (§5.5). */
export function findMatch(
  player: MatchmakingProfile,
  pool: MatchmakingProfile[],
  nowMs: number,
): MatchDecision {
  const waitSeconds = Math.max(0, (nowMs - player.queueJoinTimeMs) / 1000);
  const band = currentSkillBand(waitSeconds);
  const playerScore = compositeScore(player);

  const withinBand = pool.filter(
    (candidate) => Math.abs(compositeScore(candidate) - playerScore) <= band,
  );
  const fair = rankCandidates(player, withinBand, nowMs).filter(
    (candidate) => isFairMatch(player, candidate, waitSeconds).fair,
  );

  if (fair.length > 0) {
    return { type: "matched", opponent: fair[0] };
  }
  if (waitSeconds >= BOT_BACKFILL_AFTER_SECONDS) {
    return { type: "bot_fill" };
  }
  return {
    type: "waiting",
    estimatedWaitSeconds: Math.ceil(BOT_BACKFILL_AFTER_SECONDS - waitSeconds),
  };
}

/** Bot ability: median of those waiting, ±0.1 absolute jitter (3 specs agree;
 *  API_SPEC's "±5%" is the outlier and is not used). */
export function botTheta(waiting: number[], jitter: number): number {
  if (waiting.length === 0) return jitter;
  const sorted = [...waiting].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return median + Math.max(-0.1, Math.min(0.1, jitter));
}
