import { describe, expect, it } from "vitest";
import { botsAllowedFor } from "../src/bot";

describe("COPPA bot gate — account policy overrides the age table", () => {
  it("blocks bots when the account service says so, even for an adult age", () => {
    const r = botsAllowedFor({ age: 25, mode: "accuracy_duel", accountBlocksBots: true });
    expect(r.allowed).toBe(false);
    expect(r.reason).toContain("kids mode");
  });

  it("still allows bots for an adult when the account service allows them", () => {
    expect(botsAllowedFor({ age: 25, mode: "accuracy_duel", accountBlocksBots: false }).allowed).toBe(true);
  });

  it("keeps refusing under-13 and unknown ages regardless of the flag", () => {
    expect(botsAllowedFor({ age: 11, mode: "accuracy_duel", accountBlocksBots: false }).allowed).toBe(false);
    expect(botsAllowedFor({ age: null, mode: "accuracy_duel", accountBlocksBots: false }).allowed).toBe(false);
  });

  it("never fills the daily challenge with bots", () => {
    expect(botsAllowedFor({ age: 30, mode: "daily_challenge", accountBlocksBots: false }).allowed).toBe(false);
  });
});
