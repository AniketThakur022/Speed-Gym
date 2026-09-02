"use client";

/**
 * Root route. AppEntry (in the layout) owns the real decision: it shows the
 * splash on native shells, renders onboarding when unauthenticated, and only
 * then renders this page — whose job is simply to hand an authenticated user
 * to the dashboard.
 */
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/dashboard/learn");
  }, [router]);

  return <div className="fixed inset-0 bg-background" />;
}
