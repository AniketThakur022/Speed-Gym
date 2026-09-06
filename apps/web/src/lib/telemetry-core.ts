/**
 * Pure telemetry-queue logic (no Dexie, no network) so it can be unit-tested
 * in node. The server contract is docs/backend/TELEMETRY.md: every event
 * carries a client-generated `event_id` (the idempotency key), and a resend of
 * a partially-flushed batch is a no-op server-side.
 */

export type QueuedEvent = {
  event_id: string;
  event_type: string;
  client_timestamp: number;
  session_id?: string;
  session_elapsed_ms?: number;
  metadata: Record<string, unknown>;
  createdAt: number;
  retryCount: number;
};

export type SyncBody = {
  events: Array<Omit<QueuedEvent, "createdAt" | "retryCount">>;
  device_id?: string;
};

export type SyncResponse = {
  accepted: number;
  duplicates: number;
  sampled_out?: number;
  minimized?: number;
  xp_awarded?: number;
  entitlement?: Entitlement;
};

export type Entitlement = { tier: string; expires_at: number; grace_days: number; signature: string };

export const MAX_BATCH = 200;
export const MAX_RETRIES = 20;

export function uuid(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  // RFC-4122-ish fallback for very old WebViews
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    return (ch === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function newEvent(
  event_type: string,
  metadata: Record<string, unknown>,
  opts: { session_id?: string; session_elapsed_ms?: number; now?: number } = {},
): QueuedEvent {
  const now = opts.now ?? Date.now();
  return {
    event_id: uuid(),
    event_type,
    client_timestamp: now,
    session_id: opts.session_id,
    session_elapsed_ms: opts.session_elapsed_ms,
    metadata,
    createdAt: now,
    retryCount: 0,
  };
}

export function buildBatch(events: QueuedEvent[], deviceId?: string): SyncBody {
  return {
    events: events.slice(0, MAX_BATCH).map(({ createdAt: _c, retryCount: _r, ...rest }) => rest),
    device_id: deviceId,
  };
}

/** Minimal storage seam: Dexie in the app, an array in tests. */
export interface EventStore {
  put(event: QueuedEvent): Promise<void>;
  take(limit: number): Promise<QueuedEvent[]>;
  remove(ids: string[]): Promise<void>;
  bump(ids: string[]): Promise<void>;
  count(): Promise<number>;
}

export type FlushResult = { sent: number; accepted: number; remaining: number; error?: string; entitlement?: Entitlement };

/**
 * One flush: take a batch, POST it, drop it on success. Any 2xx means the
 * server holds every event (accepted, duplicate, sampled-out or minimised
 * alike), so the whole batch is removed. Failures bump retry counts; events
 * past MAX_RETRIES are dropped so one poison event cannot block the queue —
 * except psychometric ones, which are never dropped (they are re-tried forever).
 */
export async function flushOnce(
  store: EventStore,
  post: (body: SyncBody) => Promise<SyncResponse>,
  deviceId?: string,
  isPsychometric: (type: string) => boolean = defaultIsPsychometric,
): Promise<FlushResult> {
  const batch = await store.take(MAX_BATCH);
  if (!batch.length) return { sent: 0, accepted: 0, remaining: 0 };
  try {
    const res = await post(buildBatch(batch, deviceId));
    await store.remove(batch.map((e) => e.event_id));
    return { sent: batch.length, accepted: res.accepted, remaining: await store.count(), entitlement: res.entitlement };
  } catch (err) {
    const ids = batch.map((e) => e.event_id);
    await store.bump(ids);
    const poison = batch
      .filter((e) => e.retryCount + 1 >= MAX_RETRIES && !isPsychometric(e.event_type))
      .map((e) => e.event_id);
    if (poison.length) await store.remove(poison);
    return { sent: 0, accepted: 0, remaining: await store.count(), error: err instanceof Error ? err.message : String(err) };
  }
}

const PSYCHOMETRIC = new Set([
  "problem_attempt", "problem_solved", "problem_failed", "trap_triggered", "bkt_state_snapshot",
  "session_start", "session_end", "calibration_completed", "phase_transition", "skill_level_up",
  "fatigue_index_computed", "clr_mode_activated", "behavioral_profile_computed",
  "mock_exam_started", "mock_problem_attempt", "mock_exam_submitted",
  "deferred_workout_started", "deferred_workout_completed",
]);

export function defaultIsPsychometric(type: string): boolean {
  return PSYCHOMETRIC.has(type);
}

export class MemoryEventStore implements EventStore {
  events: QueuedEvent[] = [];
  async put(e: QueuedEvent) { this.events.push(e); }
  async take(limit: number) { return this.events.slice(0, limit); }
  async remove(ids: string[]) { const s = new Set(ids); this.events = this.events.filter((e) => !s.has(e.event_id)); }
  async bump(ids: string[]) { const s = new Set(ids); for (const e of this.events) if (s.has(e.event_id)) e.retryCount += 1; }
  async count() { return this.events.length; }
}
