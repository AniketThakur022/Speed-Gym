"use client";

/**
 * Session boot (block 8): once a learner is signed in, start the offline
 * event flush loop and read the server-authoritative kids/COPPA policy.
 * Nothing here blocks rendering; a failed policy read keeps the cached one.
 */
import { useEffect } from "react";
import { useAuthStore } from "@/stores/auth-store";
import { usePolicyStore } from "@/stores/policy-store";
import { getPolicy } from "@/services/social";
import { startEventSync } from "@/services/telemetry";

const IS_MOCK = process.env.NEXT_PUBLIC_API_MOCK !== "false";

export function SessionBoot() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setPolicy = usePolicyStore((s) => s.setPolicy);

  useEffect(() => {
    if (!isAuthenticated || IS_MOCK) return;
    const stop = startEventSync();
    getPolicy().then(setPolicy).catch(() => { /* keep the cached policy */ });
    return stop;
  }, [isAuthenticated, setPolicy]);

  return null;
}
