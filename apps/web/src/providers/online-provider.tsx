"use client";

import { useEffect, useRef } from "react";
import { useNetworkStore } from "@/stores/network-store";
import { syncAll } from "@/services/offline/sync";
import { isOnline, onOnline, onOffline } from "@/services/device";

export function OnlineProvider({ children }: { children: React.ReactNode }) {
  const setOnline = useNetworkStore((s) => s.setOnline);
  const mounted = useRef(false);

  useEffect(() => {
    if (mounted.current) return;
    mounted.current = true;

    setOnline(isOnline());

    const goOnline = () => {
      setOnline(true);
      syncAll();
    };
    const goOffline = () => setOnline(false);

    const unsubOnline = onOnline(goOnline);
    const unsubOffline = onOffline(goOffline);

    return () => {
      unsubOnline();
      unsubOffline();
    };
  }, [setOnline]);

  return <>{children}</>;
}
