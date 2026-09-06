import { describe, expect, it } from "vitest";
import {
  MAX_BATCH,
  MAX_RETRIES,
  MemoryEventStore,
  buildBatch,
  flushOnce,
  newEvent,
  type SyncBody,
} from "../src/lib/telemetry-core";

describe("telemetry queue (block 8 — offline-first practice events)", () => {
  it("every event carries a client-generated event_id and the metadata contract", () => {
    const e = newEvent("problem_attempt", { skill: "nikhilam", problem_id: "t1", is_correct: true, time_ms: 4200, domain: "vedic-math" }, { session_id: "s1", now: 1000 });
    expect(e.event_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(e.client_timestamp).toBe(1000);
    expect(e.metadata.skill).toBe("nikhilam");
    const body = buildBatch([e], "dev-1");
    expect(body.device_id).toBe("dev-1");
    expect(Object.keys(body.events[0])).not.toContain("retryCount");
    expect(Object.keys(body.events[0])).not.toContain("createdAt");
  });

  it("caps a batch at MAX_BATCH events (the server's limit)", () => {
    const events = Array.from({ length: MAX_BATCH + 50 }, (_, i) => newEvent("page_view", {}, { now: i }));
    expect(buildBatch(events).events).toHaveLength(MAX_BATCH);
  });

  it("drops the whole batch after any 2xx — duplicates and sampled-out are the server's business", async () => {
    const store = new MemoryEventStore();
    for (let i = 0; i < 3; i++) await store.put(newEvent("problem_attempt", { i }, { now: i }));
    const posted: SyncBody[] = [];
    const res = await flushOnce(store, async (b) => { posted.push(b); return { accepted: 1, duplicates: 2 }; });
    expect(posted[0].events).toHaveLength(3);
    expect(res.sent).toBe(3);
    expect(await store.count()).toBe(0);
  });

  it("keeps everything on failure and bumps retries; a resend carries the SAME event ids", async () => {
    const store = new MemoryEventStore();
    await store.put(newEvent("problem_attempt", {}, { now: 1 }));
    const first = store.events[0].event_id;
    const res = await flushOnce(store, async () => { throw new Error("offline"); });
    expect(res.error).toBe("offline");
    expect(store.events[0].retryCount).toBe(1);
    const sent: string[] = [];
    await flushOnce(store, async (b) => { sent.push(b.events[0].event_id); return { accepted: 1, duplicates: 0 }; });
    expect(sent[0]).toBe(first);
  });

  it("never drops psychometric events, but does drop a poison UI event after MAX_RETRIES", async () => {
    const store = new MemoryEventStore();
    const attempt = newEvent("problem_attempt", {}, { now: 1 });
    const view = newEvent("page_view", {}, { now: 2 });
    attempt.retryCount = MAX_RETRIES - 1;
    view.retryCount = MAX_RETRIES - 1;
    await store.put(attempt); await store.put(view);
    await flushOnce(store, async () => { throw new Error("offline"); });
    const remaining = store.events.map((e) => e.event_type);
    expect(remaining).toEqual(["problem_attempt"]);
  });

  it("surfaces the entitlement the sync response carries", async () => {
    const store = new MemoryEventStore();
    await store.put(newEvent("session_end", {}, { now: 1 }));
    const res = await flushOnce(store, async () => ({ accepted: 1, duplicates: 0, entitlement: { tier: "pro", expires_at: 1, grace_days: 3, signature: "x" } }));
    expect(res.entitlement?.tier).toBe("pro");
  });
});
