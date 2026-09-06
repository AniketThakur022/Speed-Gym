"use client";

/**
 * Dashboard home — the hub the onboarding flow and AppEntry land on. Replaces
 * the 2026-09-03 redirect shim now that the /api/v1/dashboard/* reads are real.
 */
import Link from "next/link";
import { useDashboardData } from "@/hooks/queries/use-dashboard";
import { useEntitlementStore } from "@/stores/entitlement-store";
import { usePolicyStore } from "@/stores/policy-store";

const LINKS = [
  ["/dashboard/practice", "Practice", "Adaptive drills, on-device mastery"],
  ["/dashboard/mocks", "Mock Center", "Full-length CAT / GMAT / GRE"],
  ["/dashboard/leaderboard", "Leaderboard", "XP ranks + today's challenge"],
  ["/dashboard/friends", "Friends", "Pair, race ghosts, compare"],
  ["/dashboard/learn", "Learn", "Topic browser"],
  ["/dashboard/billing", "Plans", "Pro, bundles, family seats"],
] as const;

export default function DashboardIndex() {
  const { data } = useDashboardData();
  const tier = useEntitlementStore((s) => s.tier());
  const policy = usePolicyStore((s) => s.policy);

  return (
    <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">
      <div className="flex items-center justify-between">
        <h1 className="text-fluid-xl font-semibold">Exam Arena</h1>
        <span className="rounded-full bg-accent px-2 py-1 text-fluid-xs uppercase">{tier}{policy.kids_mode ? " · kids" : ""}</span>
      </div>
      {data && (
        <div className="mt-4 grid grid-cols-3 gap-2 text-center text-fluid-sm">
          <Stat label="Streak" value={`${data.streak.current}d`} />
          <Stat label="XP" value={String(data.streak.xp)} />
          <Stat label="Accuracy" value={`${data.stats.accuracy}%`} />
        </div>
      )}
      {data && data.upcoming.length > 0 && (
        <ul className="mt-4 grid gap-1 text-fluid-sm">
          {data.upcoming.map((u) => <li key={u.title} className="flex justify-between rounded-lg bg-card px-3 py-2"><span>{u.title}</span><span className="text-muted-foreground">{u.tag}</span></li>)}
        </ul>
      )}
      <div className="mt-6 grid gap-2">
        {LINKS.map(([href, title, sub]) => (
          <Link key={href} href={href} className="rounded-lg border border-border bg-card p-3">
            <div className="font-medium">{title}</div>
            <div className="text-fluid-xs text-muted-foreground">{sub}</div>
          </Link>
        ))}
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-border bg-card p-3"><div className="text-fluid-lg font-semibold">{value}</div><div className="text-fluid-xs uppercase text-muted-foreground">{label}</div></div>;
}
