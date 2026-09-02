"use client";

import { useEffect, useRef } from "react";
import { setPlatform } from "@/services/device";

export function CapacitorInit() {
  const cleanupRef = useRef<() => void>();

  useEffect(() => {
    let _navDepth = 0;

    (async () => {
      try {
        const { Capacitor } = await import("@capacitor/core");
        if (!Capacitor.isNativePlatform()) return;
        setPlatform(Capacitor.getPlatform() as "android" | "ios");

        // Track SPA navigation depth for back button
        const origPush = history.pushState.bind(history);
        const origReplace = history.replaceState.bind(history);

        history.pushState = function (...args) {
          _navDepth++;
          return origPush(...args);
        };

        history.replaceState = function (...args) {
          return origReplace(...args);
        };

        const onPopState = () => {
          _navDepth = Math.max(0, _navDepth - 1);
        };
        window.addEventListener("popstate", onPopState);

        // Register hardware back button handler
        const { App } = await import("@capacitor/app");
        let lastBack = 0;

        await App.addListener("backButton", () => {
          if (_navDepth > 0) {
            window.history.back();
          } else {
            const now = Date.now();
            if (now - lastBack < 2000) {
              App.exitApp();
            } else {
              lastBack = now;
            }
          }
        });

        cleanupRef.current = () => {
          history.pushState = origPush;
          history.replaceState = origReplace;
          window.removeEventListener("popstate", onPopState);
        };
      } catch {
        // Not running in Capacitor
      }
    })();

    return () => cleanupRef.current?.();
  }, []);

  return null;
}
