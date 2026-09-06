import { apiPost } from "./api";

export type HintOut = { mode: "hint_ladder" | "llm" | "refused"; level: number; max_level: number; hint: string; answer_withheld: true; fallback?: string; budget_remaining: number };

/** Hints only — the server never returns the answer. */
export const askHint = (template_id: string, level: number, message?: string, prior_hint?: string) =>
  apiPost<HintOut>("/chat/query", { template_id, level, message, prior_hint });
