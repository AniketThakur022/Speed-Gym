/**
 * Offline entitlement (SUB-10 / PAY-05). The server signs
 * HMAC(user_id:expires_at) on every sync; the client cannot verify the HMAC
 * (the secret never leaves the server) — what it enforces locally is the
 * horizon: `expires_at + grace_days`. The signature is opaque and the server
 * re-validates on every online action, so tampering only breaks the tamperer.
 */
import type { Entitlement } from "./telemetry-core";

export const DEFAULT_GRACE_DAYS = 3;

export function isEntitled(ent: Entitlement | null | undefined, nowMs: number = Date.now()): boolean {
  if (!ent || !ent.tier || ent.tier === "free") return false;
  const grace = (ent.grace_days ?? DEFAULT_GRACE_DAYS) * 86_400;
  return nowMs / 1000 <= ent.expires_at + grace;
}

export function effectiveTier(ent: Entitlement | null | undefined, nowMs: number = Date.now()): string {
  return isEntitled(ent, nowMs) ? ent!.tier : "free";
}

export function secondsUntilDowngrade(ent: Entitlement | null | undefined, nowMs: number = Date.now()): number | null {
  if (!ent || ent.tier === "free") return null;
  const grace = (ent.grace_days ?? DEFAULT_GRACE_DAYS) * 86_400;
  return Math.max(0, Math.floor(ent.expires_at + grace - nowMs / 1000));
}
