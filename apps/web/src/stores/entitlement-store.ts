import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { safeLocalStorage } from "@/lib/browser";
import type { Entitlement } from "@/lib/telemetry-core";
import { effectiveTier, isEntitled } from "@/lib/entitlement";

type EntitlementState = {
  entitlement: Entitlement | null;
  updatedAt: number | null;
  setEntitlement: (e: Entitlement) => void;
  clear: () => void;
  /** Tier the client should honour right now (offline-safe). */
  tier: () => string;
  entitled: () => boolean;
};

export const useEntitlementStore = create<EntitlementState>()(
  persist(
    (set, get) => ({
      entitlement: null,
      updatedAt: null,
      setEntitlement: (e) => set({ entitlement: e, updatedAt: Date.now() }),
      clear: () => set({ entitlement: null, updatedAt: null }),
      tier: () => effectiveTier(get().entitlement),
      entitled: () => isEntitled(get().entitlement),
    }),
    { name: "exam-arena-entitlement", storage: createJSONStorage(() => safeLocalStorage) },
  ),
);
