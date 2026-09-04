import { describe, expect, it } from "vitest";
import {
  BOT_ELO_WEIGHT,
  DUEL_PERSONAS,
  MIN_AGE_FOR_BOTS,
  MIN_SOLVE_MS,
  botAnswersCorrectly,
  botSolveTimeMs,
  botTheta,
  botsAllowedFor,
  makeBot,
  publicOpponent,
  simulateBotAttempt,
  weightBotEloChange,
} from "../src/bot";

/** Deterministic RNG so bot behaviour is reproducible under test. */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

describe("COPPA and fairness gates", () => {
  it("never offers a bot to an under-13 account", () => {
    for (const age of [8, 10, 12]) {
      const result = botsAllowedFor({ age, mode: "accuracy_duel" });
      expect(result.allowed).toBe(false);
      expect(result.reason).toMatch(/under 13|kids/i);
    }
  });

  it("allows bots for players at or above the age gate", () => {
    expect(botsAllowedFor({ age: MIN_AGE_FOR_BOTS, mode: "accuracy_duel" }).allowed).toBe(true);
    expect(botsAllowedFor({ age: 30, mode: "accuracy_duel" }).allowed).toBe(true);
  });

  it("refuses when age is unknown rather than assuming adult", () => {
    // Defaulting an absent age to adult would let a mis-recorded child profile
    // through the COPPA gate; a longer queue is the cheaper failure.
    expect(botsAllowedFor({ age: undefined, mode: "accuracy_duel" }).allowed).toBe(false);
    expect(botsAllowedFor({ age: null, mode: "accuracy_duel" }).allowed).toBe(false);
  });

  it("keeps bots out of the daily challenge and ranked tournaments", () => {
    expect(botsAllowedFor({ age: 25, mode: "daily_challenge" }).allowed).toBe(false);
    expect(
      botsAllowedFor({ age: 25, mode: "tournament", isRankedTournament: true }).allowed,
    ).toBe(false);
  });
});

describe("bot identity is not self-disclosing", () => {
  it("generates human-plausible ids, never bot_<uuid>", () => {
    for (let seed = 1; seed <= 60; seed++) {
      const bot = makeBot([0.5, 1.0], seeded(seed));
      expect(bot.userId).not.toMatch(/bot/i);
      expect(bot.userId).not.toMatch(/^[0-9a-f]{8}-/); // not a raw uuid
      expect(bot.userId).toMatch(/^[a-z]+\d{4}$/);
      expect(bot.displayName).not.toMatch(/bot/i);
    }
  });

  it("strips isBot and persona at the API boundary", () => {
    const bot = makeBot([1.0], seeded(7));
    const exposed = publicOpponent(bot);
    expect(exposed).not.toHaveProperty("isBot");
    expect(exposed).not.toHaveProperty("persona");
    expect(Object.keys(exposed).sort()).toEqual(["display_name", "theta_u", "user_id"]);
    // The serialized form must not mention it either.
    expect(JSON.stringify(exposed)).not.toMatch(/bot|persona/i);
  });
});

describe("bot calibration", () => {
  it("takes ability from the median of waiting players with bounded jitter", () => {
    for (let seed = 1; seed <= 40; seed++) {
      const theta = botTheta([0.5, 1.0, 1.5], seeded(seed));
      expect(Math.abs(theta - 1.0)).toBeLessThanOrEqual(0.1);
    }
  });

  it("handles an empty lobby without producing NaN", () => {
    expect(botTheta([], seeded(3))).toBe(0);
  });

  it("seeds ELO from ability, clamped to the rating bounds", () => {
    const bot = makeBot([3.5], seeded(11));
    expect(bot.elo).toBeLessThanOrEqual(2400);
    expect(bot.elo).toBeGreaterThanOrEqual(600);
  });

  it("only uses the duel's persona set", () => {
    for (let seed = 1; seed <= 40; seed++) {
      expect(DUEL_PERSONAS).toContain(makeBot([1.0], seeded(seed)).persona);
    }
  });
});

describe("solve behaviour reads as human", () => {
  it("never answers faster than the 3s floor", () => {
    for (let seed = 1; seed <= 200; seed++) {
      for (const persona of DUEL_PERSONAS) {
        expect(botSolveTimeMs(persona, 8000, seeded(seed))).toBeGreaterThanOrEqual(MIN_SOLVE_MS);
      }
    }
  });

  it("never trips the server's own sub-800ms anti-cheat flag", () => {
    // A bot that looks like a cheater to our own validator is a bug.
    for (let seed = 1; seed <= 200; seed++) {
      expect(botSolveTimeMs("improver", 4000, seeded(seed))).toBeGreaterThan(800);
    }
  });

  it("produces varied timings rather than a constant", () => {
    const times = new Set(
      Array.from({ length: 40 }, (_, i) => botSolveTimeMs("improver", 9000, seeded(i + 1))),
    );
    expect(times.size).toBeGreaterThan(20);
  });

  it("gets easy problems right more often than hard ones", () => {
    const rate = (difficulty: number) => {
      let correct = 0;
      for (let seed = 1; seed <= 400; seed++) {
        if (botAnswersCorrectly("improver", 2.0, difficulty, seeded(seed))) correct++;
      }
      return correct / 400;
    };
    expect(rate(1)).toBeGreaterThan(rate(4));
  });

  it("chokers fail hard problems most of the time", () => {
    let correct = 0;
    for (let seed = 1; seed <= 400; seed++) {
      if (botAnswersCorrectly("choker", 3.0, 4.5, seeded(seed))) correct++;
    }
    expect(correct / 400).toBeLessThan(0.45);
  });

  it("simulateBotAttempt returns a usable attempt", () => {
    const bot = makeBot([1.0], seeded(5));
    const attempt = simulateBotAttempt(bot, 2, 7000, seeded(9));
    expect(typeof attempt.correct).toBe("boolean");
    expect(attempt.solveTimeMs).toBeGreaterThanOrEqual(MIN_SOLVE_MS);
  });
});

describe("rating impact", () => {
  it("halves the rating change for a bot round", () => {
    expect(BOT_ELO_WEIGHT).toBe(0.5);
    expect(weightBotEloChange(30)).toBe(15);
    expect(weightBotEloChange(-31)).toBe(-16); // rounds, never drops the sign
    expect(weightBotEloChange(0)).toBe(0);
  });

  it("keeps the direction of the change", () => {
    expect(weightBotEloChange(7)).toBeGreaterThan(0);
    expect(weightBotEloChange(-7)).toBeLessThan(0);
  });
});
