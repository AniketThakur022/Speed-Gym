import { apiGet, apiPost } from "./api";
import type { Policy } from "@/stores/policy-store";

export type Friend = { friendship_id: string; user_id: string; name: string; source: string; since?: string | null };
export type FriendsView = { friends: Friend[]; incoming: Friend[]; outgoing: Friend[] };

export const getPolicy = () => apiGet<Policy>("/social/policy");
export const getFriends = () => apiGet<FriendsView>("/social/friends");
export const requestFriend = (email: string) => apiPost<{ friendship_id: string }>("/social/friends/request", { email });
export const respondFriend = (friendship_id: string, action: "accept" | "decline" | "block") =>
  apiPost("/social/friends/respond", { friendship_id, action });
export const qrGenerate = () => apiPost<{ code: string; sig: string; expiresIn: number }>("/social/friends/qr/generate");
export const qrRedeem = (code: string, sig: string) => apiPost("/social/friends/qr/redeem", { code, sig });

export type DailyProblem = { problem_id: string; text: string; difficulty: number };
export type Daily = { date: string; problems: DailyProblem[]; submitted: null | { score: number; problems_correct: number } };
export const getDaily = () => apiGet<Daily>("/social/daily");
export const submitDaily = (answers: (string | null)[], total_time_ms: number) =>
  apiPost<{ score: number; rank: number | null; problems_correct: number; xp_awarded: number }>("/social/daily/submit", { answers, total_time_ms });
export const getDailyLeaderboard = () => apiGet<{ mode: string; entries: Array<{ rank: number; name: string; score: number }>; me: { rank: number; score: number; percentile: number } | null }>("/social/daily/leaderboard");
export const getAchievements = () => apiGet<{ achievements: Array<{ key: string; name: string; tier: number; category: string; phase: string; unlocked_at: string | null }>; unlocked_count: number }>("/social/achievements");
