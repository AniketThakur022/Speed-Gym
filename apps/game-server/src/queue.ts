/**
 * Per-player problem queues.
 * Source: gaming/PHASE_B_DESIGN.md §2.1 steps 4–5 — Fisher–Yates shuffle per
 * player (anti-screen-peek), then a fairness rebalance so no player's queue
 * is materially harder than another's.
 *
 * Scope, honestly: this is written for modes with a PRE-FETCHED queue (Speed
 * Race, pass-and-play — where two players may share one screen and the
 * shuffle is the only mitigation). The Accuracy Duel fetches ONE problem per
 * round at an escalating difficulty and unicasts it to the active player, so
 * there is no queue to shuffle there; the specs never reconcile the two, and
 * this module does not pretend to.
 */

export interface QueuedProblem {
  problemId: string;
  difficulty: number;
}

export const REBALANCE_THRESHOLD = 0.5;

/** Fisher–Yates with an injected RNG so a test can pin the permutation. */
export function fisherYates<T>(items: readonly T[], rng: () => number): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export function averageDifficulty(queue: readonly QueuedProblem[]): number {
  if (queue.length === 0) return 0;
  return queue.reduce((sum, p) => sum + p.difficulty, 0) / queue.length;
}

/**
 * Build one shuffled queue per player from a shared pool. Each player sees the
 * same PROBLEMS in a different ORDER — the pool is shared so the match is
 * comparable, the order differs so a glance at a neighbour's screen is useless.
 */
export function buildPlayerQueues(
  pool: readonly QueuedProblem[],
  playerIds: readonly string[],
  rng: () => number,
): Map<string, QueuedProblem[]> {
  const queues = new Map<string, QueuedProblem[]>();
  for (const id of playerIds) {
    queues.set(id, fisherYates(pool, rng));
  }
  return rebalance(queues);
}

/**
 * If the hardest average queue exceeds the easiest by more than 0.5, swap the
 * hardest problem out of the hard queue for the easiest problem in the easy
 * queue (PHASE_B_DESIGN §2.1 step 5). Repeats until within threshold or no
 * swap helps, so it always terminates.
 *
 * Note this only matters when queues are drawn from DIFFERENT pools or are
 * truncated; a full permutation of one shared pool has identical averages by
 * construction, and the loop exits immediately.
 */
export function rebalance(queues: Map<string, QueuedProblem[]>): Map<string, QueuedProblem[]> {
  for (let guard = 0; guard < 50; guard++) {
    const entries = [...queues.entries()];
    if (entries.length < 2) return queues;

    entries.sort((a, b) => averageDifficulty(a[1]) - averageDifficulty(b[1]));
    const [easyId, easy] = entries[0];
    const [hardId, hard] = entries[entries.length - 1];
    if (averageDifficulty(hard) - averageDifficulty(easy) <= REBALANCE_THRESHOLD) return queues;
    if (easy.length === 0 || hard.length === 0) return queues;

    const hardestIdx = hard.reduce((best, p, i) => (p.difficulty > hard[best].difficulty ? i : best), 0);
    const easiestIdx = easy.reduce((best, p, i) => (p.difficulty < easy[best].difficulty ? i : best), 0);
    if (hard[hardestIdx].difficulty <= easy[easiestIdx].difficulty) return queues; // a swap cannot help

    const tmp = hard[hardestIdx];
    hard[hardestIdx] = easy[easiestIdx];
    easy[easiestIdx] = tmp;
    queues.set(easyId, easy);
    queues.set(hardId, hard);
  }
  return queues;
}
