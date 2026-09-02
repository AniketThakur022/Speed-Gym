"use client";

/**
 * SHIM (2026-09-03 reseed). The APK shipped ~25 dashboard routes but only
 * `/dashboard/learn` survived in the recovered sources, yet both the onboarding
 * flow and AppEntry navigate to `/dashboard` — which 404s without this file.
 * Redirects to the one real page until the dashboard index is rebuilt; delete
 * this when that lands.
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function DashboardIndex() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard/learn");
  }, [router]);

  return <div className="fixed inset-0 bg-background" />;
}
