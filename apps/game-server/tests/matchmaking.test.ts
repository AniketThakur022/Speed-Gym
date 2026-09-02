import { describe, expect, it } from "vitest";
import {
  botTheta,
  compositeScore,
  currentSkillBand,
  findMatch,
  isFairMatch,
  rankCandidates,
  seedElo,
  type MatchmakingProfile,
} from "../src/matchmaking";

function profile(overrides: Partial<MatchmakingProfile> = {}): MatchmakingProfile {
  return {
    userId: "p1",
    thetaU: 0,
    elo: 1500,
    cluster: "balanced",
    latencyMs: 50,
    queueJoinTimeMs: 0,
    ...overrides,
  };
}

describe("composite score and ELO seed", () => {
  it("normalizes both terms into [0,1] before weighting 0.4/0.6", () => {
    // theta 0 → 0.5 ; elo 1500 → 0.5 ; 0.4(0.5) + 0.6(0.5) = 0.5
    expect(compositeScore({ thetaU: 0, elo: 1500 })).toBeCloseTo(0.5, 10);
    expect(compositeScore({ thetaU: 3, elo: 2400 })).toBeCloseTo(1, 10);
    expect(compositeScore({ thetaU: -3, elo: 600 })).toBeCloseTo(0, 10);
  });

  it("seeds ELO from ability, clamped to [600, 2400]", () => {
    expect(seedElo(0)).toBe(1000);
    expect(seedElo(1.5)).toBe(1600);
    expect(seedElo(-3)).toBe(600); // raw -200 clamps up
    expect(seedElo(3)).toBe(2200);
  });
});

describe("skill band widening", () => {
  it("starts at 0.15 and widens 0.05 per minute of waiting", () => {
    expect(currentSkillBand(0)).toBeCloseTo(0.15, 10);
    expect(currentSkillBand(60)).toBeCloseTo(0.2, 10);
    expect(currentSkillBand(120)).toBeCloseTo(0.25, 10);
  });

  it("caps at 0.50", () => {
    expect(currentSkillBand(420)).toBe(0.5);
    expect(currentSkillBand(100_000)).toBe(0.5);
  });

  it("takes ELAPSED seconds, not an absolute timestamp", () => {
    // The spec passed queue_join_time (epoch ms) here, which saturates the band
    // instantly and disables skill matching entirely.
    expect(currentSkillBand(30)).toBeLessThan(0.5);
  });
});

describe("fairness gate", () => {
  it("rejects an ability gap over 0.5", () => {
    const result = isFairMatch(profile({ thetaU: 0 }), profile({ userId: "p2", thetaU: 0.6 }));
    expect(result.fair).toBe(false);
    expect(result.reason).toMatch(/theta/);
  });

  it("rejects incompatible clusters early in the queue", () => {
    const result = isFairMatch(
      profile({ cluster: "sprinter" }),
      profile({ userId: "p2", cluster: "deliberate" }),
      10,
    );
    expect(result.fair).toBe(false);
  });

  it("relaxes the cluster rule after 120s so a player is not stranded", () => {
    const result = isFairMatch(
      profile({ cluster: "sprinter" }),
      profile({ userId: "p2", cluster: "deliberate" }),
      150,
    );
    expect(result.fair).toBe(true);
  });

  it("rejects a latency gap over 200ms", () => {
    const result = isFairMatch(
      profile({ latencyMs: 20 }),
      profile({ userId: "p2", latencyMs: 400 }),
    );
    expect(result.reason).toMatch(/latency/);
  });

  it("never matches a player with themselves", () => {
    expect(isFairMatch(profile(), profile()).fair).toBe(false);
  });
});

describe("candidate ranking", () => {
  it("prefers the closest skill when waits are equal", () => {
    const player = profile({ thetaU: 0, elo: 1500 });
    const near = profile({ userId: "near", elo: 1520 });
    const far = profile({ userId: "far", elo: 2000 });
    expect(rankCandidates(player, [far, near], 0)[0].userId).toBe("near");
  });

  it("prioritises the longer-waiting candidate, not demotes it", () => {
    // The spec's sort was ascending on a raw seconds term, which put the
    // longest-waiting candidates LAST — the opposite of its stated intent.
    const now = 300_000;
    const player = profile({ thetaU: 0, elo: 1500 });
    const waitingLong = profile({ userId: "long", elo: 1560, queueJoinTimeMs: now - 120_000 });
    const justJoined = profile({ userId: "fresh", elo: 1550, queueJoinTimeMs: now - 1_000 });
    expect(rankCandidates(player, [justJoined, waitingLong], now)[0].userId).toBe("long");
  });
});

describe("match decision", () => {
  it("matches a fair opponent inside the band", () => {
    const now = 10_000;
    const player = profile({ queueJoinTimeMs: now - 5_000 });
    const decision = findMatch(player, [profile({ userId: "p2", elo: 1520 })], now);
    expect(decision.type).toBe("matched");
    expect(decision.opponent?.userId).toBe("p2");
  });

  it("keeps waiting with an estimate when nobody is suitable yet", () => {
    const now = 10_000;
    const player = profile({ queueJoinTimeMs: now - 5_000 });
    const decision = findMatch(player, [profile({ userId: "p2", thetaU: 2.9, elo: 2400 })], now);
    expect(decision.type).toBe("waiting");
    expect(decision.estimatedWaitSeconds).toBe(55);
  });

  it("falls back to a bot after 60 seconds", () => {
    const now = 100_000;
    const player = profile({ queueJoinTimeMs: now - 61_000 });
    expect(findMatch(player, [], now).type).toBe("bot_fill");
  });
});

describe("bot ability", () => {
  it("uses the median of waiting players with bounded jitter", () => {
    expect(botTheta([0.5, 1.0, 1.5], 0)).toBe(1.0);
    expect(botTheta([1.0, 2.0], 0)).toBe(1.5);
  });

  it("clamps jitter to ±0.1 absolute", () => {
    expect(botTheta([1.0], 5)).toBeCloseTo(1.1, 10);
    expect(botTheta([1.0], -5)).toBeCloseTo(0.9, 10);
  });
});
