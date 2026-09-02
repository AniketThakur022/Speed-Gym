import { apiGet } from "./api";

export type AnswerCheck = "client_extract" | "server_sympy";

export type PracticeItem = {
  source: "tier1_static" | "tier2_generated";
  template_id: string;
  question_text: string | null;
  difficulty: number;
  technique: string | null;
  topic: string | null;
  sub_topic: string | null;
  trust: string;
  /** Sandbox content is playable but must never move mastery. */
  feeds_mastery: boolean;
  answer_verification: string;
  solution_verification: string;
  answer_check: AnswerCheck;
  /** Present only when the item can be marked on-device (offline-first). */
  expected_answer: number | null;
  answer_key_display?: string | null;
};

export type PracticeSession = {
  items: PracticeItem[];
  summary: {
    requested: number;
    served: number;
    tier1_static: number;
    tier2_generated: number;
    client_checkable: number;
    server_checkable: number;
    feeds_mastery: number;
    /** Why content was filtered out — an empty session should be explainable. */
    withheld: Record<string, number>;
  };
};

export async function getPracticeSession(params: {
  topic?: string;
  technique?: string;
  size?: number;
} = {}): Promise<PracticeSession> {
  const query = new URLSearchParams();
  if (params.topic) query.set("topic", params.topic);
  if (params.technique) query.set("technique", params.technique);
  query.set("size", String(params.size ?? 10));
  return apiGet<PracticeSession>(`/practice/session?${query.toString()}`);
}
