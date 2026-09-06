/**
 * Offline-first telemetry: queue in Dexie, flush to POST /api/v1/sync.
 * Psychometric events are never dropped; the server never double-counts a
 * resend (event_id idempotency). The sync response also carries the offline
 * entitlement, which is persisted here.
 */
import { apiPost } from "./api";
import { db } from "./offline/db";
import {
  flushOnce,
  newEvent,
  type EventStore,
  type FlushResult,
  type QueuedEvent,
  type SyncBody,
  type SyncResponse,
} from "@/lib/telemetry-core";
import { useEntitlementStore } from "@/stores/entitlement-store";

export const dexieEventStore: EventStore = {
  async put(e: QueuedEvent) { await db.eventQueue.put(e); },
  async take(limit: number) { return db.eventQueue.orderBy("createdAt").limit(limit).toArray(); },
  async remove(ids: string[]) { await db.eventQueue.bulkDelete(ids); },
  async bump(ids: string[]) {
    await db.eventQueue.where("event_id").anyOf(ids).modify((e) => { e.retryCount += 1; });
  },
  async count() { return db.eventQueue.count(); },
};

function deviceId(): string | undefined {
  try {
    const key = "exam-arena-device-id";
    let id = localStorage.getItem(key);
    if (!id) {
      id = newEvent("x", {}).event_id;
      localStorage.setItem(key, id);
    }
    return id;
  } catch {
    return undefined;
  }
}

export async function queueEvent(
  eventType: string,
  metadata: Record<string, unknown>,
  opts: { session_id?: string; session_elapsed_ms?: number } = {},
): Promise<void> {
  await dexieEventStore.put(newEvent(eventType, metadata, opts));
}

let flushing = false;

export async function flushEvents(): Promise<FlushResult> {
  if (flushing) return { sent: 0, accepted: 0, remaining: await dexieEventStore.count() };
  flushing = true;
  try {
    let last: FlushResult = { sent: 0, accepted: 0, remaining: 0 };
    // Drain in batches; stop on the first failure (offline) — the interval retries.
    for (let i = 0; i < 10; i++) {
      last = await flushOnce(dexieEventStore, (body: SyncBody) => apiPost<SyncResponse>("/sync", body), deviceId());
      if (last.entitlement) useEntitlementStore.getState().setEntitlement(last.entitlement);
      if (last.error || last.remaining === 0) break;
    }
    return last;
  } finally {
    flushing = false;
  }
}

/** Wire the flush to connectivity, visibility and a timer. Returns a disposer. */
export function startEventSync(intervalMs = 30_000): () => void {
  if (typeof window === "undefined") return () => {};
  const onOnline = () => { void flushEvents(); };
  const onVisible = () => { if (document.visibilityState === "visible") void flushEvents(); };
  window.addEventListener("online", onOnline);
  document.addEventListener("visibilitychange", onVisible);
  const timer = window.setInterval(() => { if (navigator.onLine) void flushEvents(); }, intervalMs);
  void flushEvents();
  return () => {
    window.removeEventListener("online", onOnline);
    document.removeEventListener("visibilitychange", onVisible);
    window.clearInterval(timer);
  };
}
