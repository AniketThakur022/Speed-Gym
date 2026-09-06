import Dexie, { type Table } from "dexie";
import type { ContentFeedbackRequest } from "@/lib/types/content-feedback";
import type { QueuedEvent } from "@/lib/telemetry-core";

export interface DashboardCache {
  id: string;
  data: unknown;
  updatedAt: number;
  trustStatus?: string;
  ttl?: number;
}

export interface QueuedFeedback {
  id: string;
  payload: ContentFeedbackRequest;
  createdAt: number;
  retryCount: number;
}

class ExamArenaDB extends Dexie {
  dashboardCache!: Table<DashboardCache, string>;
  feedbackQueue!: Table<QueuedFeedback, string>;
  /** Block 8: the offline practice queue — every event the practice loop
   *  emits, flushed to POST /api/v1/sync in idempotent batches. */
  eventQueue!: Table<QueuedEvent, string>;

  constructor() {
    super("ExamArenaDB");
    this.version(2).stores({
      dashboardCache: "id, updatedAt, trustStatus",
      feedbackQueue: "id, createdAt, retryCount",
    });
    this.version(3).stores({
      dashboardCache: "id, updatedAt, trustStatus",
      feedbackQueue: "id, createdAt, retryCount",
      eventQueue: "event_id, createdAt, event_type",
    });
  }
}

export const db = new ExamArenaDB();
