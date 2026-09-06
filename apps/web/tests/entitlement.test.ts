import { describe, expect, it } from "vitest";
import { effectiveTier, isEntitled, secondsUntilDowngrade } from "../src/lib/entitlement";

const DAY = 86_400;

describe("offline entitlement (SUB-10 / PAY-05)", () => {
  it("honours the horizon plus the server-declared grace, then downgrades to free", () => {
    const ent = { tier: "pro", expires_at: 1_000_000, grace_days: 3, signature: "sig" };
    expect(isEntitled(ent, (1_000_000 + 2 * DAY) * 1000)).toBe(true);
    expect(isEntitled(ent, (1_000_000 + 3 * DAY) * 1000)).toBe(true);
    expect(isEntitled(ent, (1_000_000 + 3 * DAY + 1) * 1000)).toBe(false);
    expect(effectiveTier(ent, (1_000_000 + 4 * DAY) * 1000)).toBe("free");
  });

  it("free and missing entitlements are never entitled", () => {
    expect(isEntitled(null)).toBe(false);
    expect(isEntitled({ tier: "free", expires_at: 9e12, grace_days: 3, signature: "" })).toBe(false);
    expect(secondsUntilDowngrade(null)).toBeNull();
  });

  it("counts down to the downgrade", () => {
    const ent = { tier: "bundle_2", expires_at: 100, grace_days: 1, signature: "" };
    expect(secondsUntilDowngrade(ent, 100 * 1000)).toBe(DAY);
    expect(secondsUntilDowngrade(ent, (100 + DAY + 50) * 1000)).toBe(0);
  });
});
