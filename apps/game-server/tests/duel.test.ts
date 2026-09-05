import { describe, expect, it } from "vitest";
import {
  ageMultiplier,
  beginRound,
  breakTie,
  checkDisconnectForfeit,
  createMatch,
  expireTurn,
  firstMover,
  makeMatchId,
  markDisconnected,
  markReconnected,
  normalizeAnswer,
  resolveAnswer,
  roundDifficulty,
  scoreDuel,
  turnTimeLimitMs,
  validateAnswer,
  DISCONNECT_GRACE_MS,
} from "../src/duel";

/** Plausible keystroke gaps: these tests model a TYPED answer. */
const TYPED = [110, 95, 130];

const alice = { userId: "alice", thetaU: 0.5, age: 20 };
const bob = { userId: "bob", thetaU: 1.5, age: 20 };

function match(nowMs = 1_000_000) {
  return createMatch("ad_20260903_001", alice, bob, nowMs);
}

describe("duel difficulty and timing", () => {
  it("starts at floor(mean theta) and escalates 0.5 per round", () => {
    // mean(0.5, 1.5) = 1.0 → floor 1
    expect(roundDifficulty(0.5, 1.5, 1)).toBe(1);
    expect(roundDifficulty(0.5, 1.5, 2)).toBe(1.5);
    expect(roundDifficulty(0.5, 1.5, 10)).toBe(5.5);
  });

  it("escalates 1.0 per round in sudden death, uncapped", () => {
    const atTen = roundDifficulty(0.5, 1.5, 10);
    expect(roundDifficulty(0.5, 1.5, 11)).toBe(atTen + 1);
    expect(roundDifficulty(0.5, 1.5, 15)).toBe(atTen + 5);
  });

  it("applies the age table and the duel's 1.5x handicap", () => {
    expect(ageMultiplier(9)).toBe(2.5);
    expect(ageMultiplier(20)).toBe(1.0);
    expect(turnTimeLimitMs(20)).toBe(45_000); // 30s × 1.0 × 1.5
    expect(turnTimeLimitMs(9)).toBe(112_500); // 30s × 2.5 × 1.5
  });

  it("gives the first turn to the lower-ability player", () => {
    expect(firstMover(alice, bob)).toBe("alice");
    expect(firstMover(bob, alice)).toBe("alice");
  });

  it("formats match ids as ad_YYYYMMDD_NNN", () => {
    expect(makeMatchId(new Date(Date.UTC(2026, 8, 3)), 1)).toBe("ad_20260903_001");
  });
});

describe("answer validation and anti-cheat", () => {
  it("normalizes whitespace, case and separators before comparing", () => {
    expect(normalizeAnswer(" 1,250 ")).toBe("1250");
    expect(normalizeAnswer("Nikhilam")).toBe("nikhilam");
  });

  it("flags sub-800ms submissions as impossible speed", () => {
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 0.2,
      problemSentAtMs: 0, clientTimestampMs: 500, keystrokeIntervalsMs: TYPED,
    });
    expect(r.reason).toBe("IMPOSSIBLE_SPEED");
    expect(r.flagged).toBe(true);
  });

  it("flags fast answers from low-ability players as a timing anomaly", () => {
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 0.2,
      problemSentAtMs: 0, clientTimestampMs: 1500, keystrokeIntervalsMs: TYPED,
    });
    expect(r.reason).toBe("TIMING_ANOMALY");
  });

  it("does not flag the same speed from a high-ability player", () => {
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 1.2,
      problemSentAtMs: 0, clientTimestampMs: 1500, keystrokeIntervalsMs: TYPED,
    });
    expect(r.flagged).toBe(false);
  });

  it("keeps a flagged answer correct — flags are advisory, not a verdict", () => {
    // 300ms would now be a hard reject (SUB_200MS applies below 200ms, and the
    // pre-existing fixture sat too close to it); the advisory tier is 200-800ms.
    const r = validateAnswer({
      submitted: "42", expected: "42", thetaU: 0.1,
      problemSentAtMs: 0, clientTimestampMs: 600, keystrokeIntervalsMs: TYPED,
    });
    expect(r.correct).toBe(true);
    expect(r.flagged).toBe(true);
    expect(r.rejected).toBeUndefined();
  });
});

describe("duel flow", () => {
  it("hands the turn over after a correct answer", () => {
    const m = match();
    const round = beginRound(m, 1_000_000);
    expect(round.activeUserId).toBe("alice");

    const result = resolveAnswer(m, "alice", "42", "42", 1_010_000, TYPED);
    expect(result.correct).toBe(true);
    expect(result.matchOver).toBe(false);
    expect(result.nextActiveUserId).toBe("bob");
    expect(m.activeUserId).toBe("bob");
  });

  it("ends the match immediately on a wrong answer — elimination, not points", () => {
    const m = match();
    beginRound(m, 1_000_000);
    const result = resolveAnswer(m, "alice", "41", "42", 1_010_000, TYPED);
    expect(result.matchOver).toBe(true);
    expect(result.winnerUserId).toBe("bob");
    expect(result.eliminationReason).toBe("wrong_answer");
    expect(m.phase).toBe("completed");
  });

  it("refuses an answer submitted out of turn", () => {
    const m = match();
    beginRound(m, 1_000_000);
    expect(() => resolveAnswer(m, "bob", "42", "42", 1_010_000, TYPED)).toThrow("NOT_YOUR_TURN");
  });

  it("treats a turn timeout as elimination", () => {
    const m = match();
    beginRound(m, 1_000_000);
    const result = expireTurn(m);
    expect(result.eliminationReason).toBe("timeout");
    expect(result.winnerUserId).toBe("bob");
  });

  it("enters sudden death after round 10", () => {
    const m = match();
    for (let i = 0; i < 10; i++) {
      beginRound(m, 1_000_000);
      resolveAnswer(m, m.activeUserId, "42", "42", 1_005_000, TYPED);
    }
    expect(m.phase).toBe("active");
    beginRound(m, 1_000_000);
    expect(m.roundNumber).toBe(11);
    expect(m.phase).toBe("sudden_death");
  });
});

describe("disconnect handling", () => {
  it("does not forfeit inside the 15s grace window", () => {
    const m = match();
    markDisconnected(m, "bob", 2_000_000);
    expect(checkDisconnectForfeit(m, 2_000_000 + DISCONNECT_GRACE_MS - 1)).toBeNull();
  });

  it("forfeits to the opponent once grace expires", () => {
    const m = match();
    markDisconnected(m, "bob", 2_000_000);
    const result = checkDisconnectForfeit(m, 2_000_000 + DISCONNECT_GRACE_MS);
    expect(result?.eliminationReason).toBe("forfeit");
    expect(result?.winnerUserId).toBe("alice");
  });

  it("cancels the forfeit when the player reconnects in time", () => {
    const m = match();
    markDisconnected(m, "bob", 2_000_000);
    markReconnected(m, "bob");
    expect(checkDisconnectForfeit(m, 2_000_000 + DISCONNECT_GRACE_MS + 5_000)).toBeNull();
  });
});

describe("scoring", () => {
  it("awards position points plus the accuracy bonus", () => {
    const [winner, loser] = scoreDuel(
      [
        { userId: "alice", problemsAttempted: 5, problemsCorrect: 5, totalTimeMs: 50_000, trapsTriggered: 0 },
        { userId: "bob", problemsAttempted: 5, problemsCorrect: 4, totalTimeMs: 60_000, trapsTriggered: 1 },
      ],
      "alice",
    );
    // winner: 2 position + (5×2 − 0) = 12 ; loser: 1 position + (4×2 − 1) = 8
    expect(winner.finalScore).toBe(12);
    expect(loser.finalScore).toBe(8);
    expect(winner.isWinner).toBe(true);
    expect(winner.rank).toBe(1);
    expect(loser.accuracyPct).toBe(80);
  });

  it("breaks ties by accuracy, then speed, then traps", () => {
    const base = {
      userId: "x", problemsAttempted: 10, totalTimeMs: 0, trapsTriggered: 0,
      rank: 1, isWinner: true, positionPoints: 2, accuracyBonus: 0, finalScore: 2,
      problemsCorrect: 8,
    };
    const higherAccuracy = { ...base, accuracyPct: 90, avgTimeMs: 5000 };
    const lowerAccuracy = { ...base, accuracyPct: 80, avgTimeMs: 4000 };
    expect(breakTie(higherAccuracy, lowerAccuracy)).toBeLessThan(0);

    const faster = { ...base, accuracyPct: 90, avgTimeMs: 3000 };
    expect(breakTie(faster, higherAccuracy)).toBeLessThan(0);
  });
});
