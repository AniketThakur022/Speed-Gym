import { apiGet, apiPost } from "./api";

export type MockQuestion = { question_id: string; position: number; kind: "mcq" | "tita" | "numeric" | "essay"; text: string; options: Array<{ id: string; text: string }> | null; skill: string | null; difficulty: number | null };
export type MockSection = { key: string; name: string; minutes: number; kinds: string[]; marks_correct: number; marks_wrong_mcq: number; questions: MockQuestion[] };
export type MockConfigured = { mock_id: string; exam: string; mode: string; time_limit_seconds: number; timers_suppressed: boolean; rules: Record<string, unknown>; sections: MockSection[] };
export type MockResult = { mock_id: string; score: { total_raw: number; max_raw: number; scaled_total: number | null; scaled_approximate: boolean; sections: Array<{ key: string; correct: number; wrong: number; unattempted: number; raw: number; max_raw: number; scaled: number | null }>; weak_areas: Array<{ skill: string; accuracy: number }> }; percentile: number; peers: number; xp_awarded: number; timing: string };

export const getBlueprints = () => apiGet<{ blueprints: Array<{ key: string; name: string; total_minutes: number; sections: Array<{ key: string; name: string; questions: number; minutes: number; available: boolean }> }> }>("/mocks/blueprints");
export const configureMock = (exam: string, sections?: string[], mode: "full" | "sectional" = "full") =>
  apiPost<MockConfigured>("/mocks/configure", { exam, sections, mode });
export const submitAnswer = (mock_id: string, question_id: string, answer: string | null, time_ms?: number) =>
  apiPost("/mocks/submit-answer", { mock_id, question_id, answer, time_ms });
export const submitMock = (mock_id: string, section_times?: Record<string, number>) => apiPost<MockResult>("/mocks/submit", { mock_id, section_times });
export const getHistory = () => apiGet<{ attempts: Array<{ mock_id: string; exam: string; total_score: number | null; max_score: number | null; percentile: number | null; completed_at: string | null }> }>("/mocks/history");
