import { describe, expect, it } from "vitest";
import {
  HARD_REJECT_MS,
  HEARTBEAT_TIMEOUT_MS,
  beginRound,
  createMatch,
  newHeartbeatLedger,
  recordHeartbeat,
  resolveAnswer,
  staleHeartbeats,
  validateAnswer,
} from "../src/duel";
import {
  REBALANCE_THRESHOLD,
  averageDifficulty,
  buildPlayerQueues,
  fisherYates,
  rebalance,
  type QueuedProblem,
} from "../src/queue";

function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const typed = [120, 95, 140]; // plausible keystroke gaps

describe("hard rejects (SAFE-GATE-01)", () => {
  it("refuses a sub-200ms submission outright, not merely flagging it", () => {
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 1.5,
      problemSentAtMs: 0, clientTimestampMs: HARD_REJECT_MS - 1, keystrokeIntervalsMs: typed,
    });
    expect(r.rejected).toBe("SUB_200MS");
    expect(r.correct).toBe(false); // a refused answer is never "correct"
  });

  it("still only FLAGS between 200ms and 800ms — the two specs are layered, not merged", () => {
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 1.5,
      problemSentAtMs: 0, clientTimestampMs: 500, keystrokeIntervalsMs: typed,
    });
    expect(r.rejected).toBeUndefined();
    expect(r.flagged).toBe(true);
    expect(r.correct).toBe(true);
  });

  it("refuses a multi-character answer with no keystroke intervals (pasted or scripted)", () => {
    const r = validateAnswer({
      submitted: "9506", expected: "9506", thetaU: 1.5,
      problemSentAtMs: 0, clientTimestampMs: 6000, keystrokeIntervalsMs: [],
    });
    expect(r.rejected).toBe("MISSING_KEYSTROKES");
  });

  it("exempts single-character answers, which have no intervals to report", () => {
    const r = validateAnswer({
      submitted: "7", expected: "7", thetaU: 1.5,
      problemSentAtMs: 0, clientTimestampMs: 6000, keystrokeIntervalsMs: [],
    });
    expect(r.rejected).toBeUndefined();
    expect(r.correct).toBe(true);
  });

  it("a rejected submission leaves the round open and the turn unchanged", () => {
    const m = createMatch(
      "ad_20260905_001",
      { userId: "alice", thetaU: 0.5, age: 20 },
      { userId: "bob", thetaU: 1.5, age: 20 },
      1_000_000,
    );
    beginRound(m, 1_000_000);
    expect(() => resolveAnswer(m, "alice", "42", "42", 1_000_050, typed)).toThrow("SUB_200MS");
    expect(m.activeUserId).toBe("alice"); // no turn hand-over
    expect(m.phase).toBe("active"); // no elimination
    expect(m.players[0].tally.problemsAttempted).toBe(0); // not counted as an attempt
  });
});

describe("per-player shuffled queues", () => {
  const pool: QueuedProblem[] = Array.from({ length: 12 }, (_, i) => ({
    problemId: `p${i}`,
    difficulty: 1 + (i % 5),
  }));

  it("Fisher-Yates is a permutation: same problems, different order, deterministic per seed", () => {
    const a = fisherYates(pool, seeded(1));
    const b = fisherYates(pool, seeded(1));
    const c = fisherYates(pool, seeded(2));
    expect(a).toEqual(b);
    expect(a.map((p) => p.problemId).sort()).toEqual(pool.map((p) => p.problemId).sort());
    expect(a.map((p) => p.problemId)).not.toEqual(c.map((p) => p.problemId));
  });

  it("gives each player a different order of the SAME pool (anti-screen-peek)", () => {
    const queues = buildPlayerQueues(pool, ["alice", "bob"], seeded(9));
    const alice = queues.get("alice")!.map((p) => p.problemId);
    const bob = queues.get("bob")!.map((p) => p.problemId);
    expect([...alice].sort()).toEqual([...bob].sort());
    expect(alice).not.toEqual(bob);
  });

  it("a full permutation of one pool needs no rebalance — averages are identical by construction", () => {
    const queues = buildPlayerQueues(pool, ["alice", "bob"], seeded(3));
    const avgs = [...queues.values()].map(averageDifficulty);
    expect(Math.abs(avgs[0] - avgs[1])).toBeLessThan(1e-9);
  });

  it("rebalances queues drawn from different pools until within the 0.5 threshold", () => {
    const queues = new Map<string, QueuedProblem[]>([
      ["easy", [{ problemId: "e1", difficulty: 1 }, { problemId: "e2", difficulty: 1 }, { problemId: "e3", difficulty: 2 }]],
      ["hard", [{ problemId: "h1", difficulty: 5 }, { problemId: "h2", difficulty: 4 }, { problemId: "h3", difficulty: 5 }]],
    ]);
    const before = averageDifficulty(queues.get("hard")!) - averageDifficulty(queues.get("easy")!);
    expect(before).toBeGreaterThan(REBALANCE_THRESHOLD);

    rebalance(queues);
    const after = averageDifficulty(queues.get("hard")!) - averageDifficulty(queues.get("easy")!);
    expect(after).toBeLessThanOrEqual(REBALANCE_THRESHOLD);
    // Nothing is lost or duplicated across the swap.
    const all = [...queues.values()].flat().map((p) => p.problemId).sort();
    expect(all).toEqual(["e1", "e2", "e3", "h1", "h2", "h3"]);
  });
});

describe("heartbeat", () => {
  it("treats silence past the timeout as a disconnect signal", () => {
    const ledger = newHeartbeatLedger();
    recordHeartbeat(ledger, "alice", 1000);
    recordHeartbeat(ledger, "bob", 1000);
    // alice keeps beating, bob goes quiet
    recordHeartbeat(ledger, "alice", 1000 + HEARTBEAT_TIMEOUT_MS);
    const stale = staleHeartbeats(ledger, 1000 + HEARTBEAT_TIMEOUT_MS + 1);
    expect(stale).toEqual(["bob"]);
  });

  it("does not flag a player who is exactly at the boundary", () => {
    const ledger = newHeartbeatLedger();
    recordHeartbeat(ledger, "alice", 0);
    expect(staleHeartbeats(ledger, HEARTBEAT_TIMEOUT_MS)).toEqual([]);
    expect(staleHeartbeats(ledger, HEARTBEAT_TIMEOUT_MS + 1)).toEqual(["alice"]);
  });
});
