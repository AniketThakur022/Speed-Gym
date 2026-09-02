/**
 * Content feedback — the human-in-the-loop signal into the content factory.
 *
 * RECONSTRUCTED during the 2026-09-03 reseed (imported by
 * `services/offline/db.ts`, not among the leaked sources). Queued in Dexie
 * (`feedbackQueue`) while offline and replayed to
 * `POST /api/v1/sync/content/feedback` — the one sync key the recovered client
 * uses. Reports flow to the trust ladder, which is why the template's trust
 * tier travels with the report.
 */

export type ContentFeedbackReason =
  | "wrong_answer"
  | "unclear_steps"
  | "typo"
  | "too_easy"
  | "too_hard"
  | "other";

export type ContentFeedbackRequest = {
  /** SolveAlongTemplate.id the report is about. */
  templateId: string;
  /** Trust tier the client held when it served the item ("trusted" | "sandbox"). */
  trustStatus?: string;
  reason: ContentFeedbackReason;
  comment?: string;
  /** Client clock, UNIX ms — the server stamps its own receipt time. */
  reportedAt: number;
  domain?: string;
};
