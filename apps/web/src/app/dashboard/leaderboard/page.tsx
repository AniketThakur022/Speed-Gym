"use client";

/** Leaderboard + Daily Challenge. The server applies the anxiety guard and
 *  the kids percentile-only rule; this page renders whatever it is allowed. */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MathText } from "@/components/math-text";
import { getLeaderboard } from "@/services/dashboard";
import { getDaily, getDailyLeaderboard, submitDaily } from "@/services/social";
import { usePolicyStore } from "@/stores/policy-store";

export default function LeaderboardPage() {
  const policy = usePolicyStore((s) => s.policy);
  const board = useQuery({ queryKey: ["leaderboard"], queryFn: () => getLeaderboard() });
  const daily = useQuery({ queryKey: ["daily"], queryFn: getDaily });
  const dailyBoard = useQuery({ queryKey: ["daily-board"], queryFn: getDailyLeaderboard });
  const [answers, setAnswers] = useState<string[]>([]);
  const [startedAt] = useState(() => Date.now());
  const [done, setDone] = useState<{ score: number; rank: number | null; problems_correct: number; xp_awarded: number } | null>(null);

  useEffect(() => { if (daily.data) setAnswers(daily.data.problems.map(() => "")); }, [daily.data]);

  async function submit() {
    if (!daily.data) return;
    const out = await submitDaily(answers.map((a) => (a.trim() ? a : null)), Date.now() - startedAt);
    setDone(out);
    void daily.refetch(); void dailyBoard.refetch(); void board.refetch();
  }

  return (
    <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">
      <h1 className="text-fluid-xl font-semibold">Leaderboard</h1>
      {board.data && board.data.length === 0 && <p className="mt-2 text-fluid-sm text-muted-foreground">Hidden for a minute after a match, or while you recover. Come back shortly.</p>}
      <ul className="mt-3 grid gap-1 text-fluid-sm">
        {(board.data ?? []).map((e) => (
          <li key={`${e.rank}-${e.name}`} className={`flex justify-between rounded-lg px-3 py-2 ${e.me ? "bg-accent" : ""}`}>
            <span>#{e.rank} {e.name}</span><span>{e.xp} XP{"percentile" in e && policy.leaderboard === "percentile_only" ? ` · top ${100 - (e as { percentile?: number }).percentile!}%` : ""}</span>
          </li>
        ))}
      </ul>

      <h2 className="mt-8 text-fluid-lg font-medium">Daily Challenge</h2>
      {daily.isError && <p className="text-fluid-sm text-muted-foreground">No challenge available right now.</p>}
      {daily.data && (daily.data.submitted || done) ? (
        <p role="status" aria-live="polite" className="mt-2 text-fluid-sm">Done for today: {(done ?? daily.data.submitted)!.problems_correct}/{daily.data.problems.length} correct · score {(done ?? daily.data.submitted)!.score}{done?.rank ? ` · rank #${done.rank}` : ""}</p>
      ) : daily.data ? (
        <div className="mt-2 grid gap-3">
          {daily.data.problems.map((p, i) => (
            <div key={p.problem_id} className="rounded-lg border border-border bg-card p-3">
              <p className="text-fluid-sm"><MathText>{p.text}</MathText></p>
              <input className="mt-2 w-full rounded-lg border border-border bg-background px-3 py-1" aria-label={`Answer for question ${i + 1}`} placeholder="Answer" value={answers[i] ?? ""} onChange={(e) => setAnswers((a) => a.map((v, j) => (j === i ? e.target.value : v)))} />
            </div>
          ))}
          <button type="button" onClick={submit} className="rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground">Submit challenge</button>
        </div>
      ) : null}
      {dailyBoard.data && dailyBoard.data.entries.length > 0 && (
        <ul className="mt-4 grid gap-1 text-fluid-sm">
          {dailyBoard.data.entries.map((e) => <li key={`${e.rank}-${e.name}`} className="flex justify-between"><span>#{e.rank} {e.name}</span><span>{e.score}</span></li>)}
        </ul>
      )}
      {dailyBoard.data?.me && dailyBoard.data.mode === "percentile_only" && (
        <p className="mt-2 text-fluid-sm text-muted-foreground">You are in the top {100 - dailyBoard.data.me.percentile}% today.</p>
      )}
    </main>
  );
}
