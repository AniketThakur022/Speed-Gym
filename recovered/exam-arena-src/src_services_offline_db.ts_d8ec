import Dexie, { type Table } from "dexie";
import type { ContentFeedbackRequest } from "@/lib/types/content-feedback";

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

  constructor() {
    super("ExamArenaDB");
    this.version(2).stores({
      dashboardCache: "id, updatedAt, trustStatus",
      feedbackQueue: "id, createdAt, retryCount",
    });
  }
}

export const db = new ExamArenaDB();
