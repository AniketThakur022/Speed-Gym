import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { safeLocalStorage } from "@/lib/browser";

/** The per-user kids/COPPA policy from GET /api/v1/social/policy, read at
 *  session start and honoured everywhere (ads, timers, bots, social). It is
 *  server-authoritative; this store only caches it for offline sessions. */
export type Policy = {
  kids_mode: boolean;
  ads_enabled: boolean;
  bots_enabled: boolean;
  taunts_enabled: boolean;
  timers_suppressed: boolean;
  session_cap_minutes: number | null;
  tracking_minimized: boolean;
  leaderboard: "full" | "percentile_only";
  clips_enabled: boolean;
  friends: "open" | "parent_managed";
  parental_consent_required: boolean;
};

const ADULT: Policy = {
  kids_mode: false, ads_enabled: true, bots_enabled: true, taunts_enabled: true, timers_suppressed: false,
  session_cap_minutes: null, tracking_minimized: false, leaderboard: "full", clips_enabled: true,
  friends: "open", parental_consent_required: false,
};

type PolicyState = { policy: Policy; setPolicy: (p: Policy) => void; reset: () => void };

export const usePolicyStore = create<PolicyState>()(
  persist(
    (set) => ({ policy: ADULT, setPolicy: (p) => set({ policy: p }), reset: () => set({ policy: ADULT }) }),
    { name: "exam-arena-policy", storage: createJSONStorage(() => safeLocalStorage) },
  ),
);
