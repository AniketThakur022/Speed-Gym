"use client";

/**
 * Mock Center — configure → take (server-timed) → submit → scorecard.
 * Every answer is posted as it is given (server-timestamped); the final
 * submit scores on the server, which alone holds the correct answers.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MathText } from "@/components/math-text";
import { configureMock, getBlueprints, getHistory, submitAnswer, submitMock, type MockConfigured, type MockResult } from "@/services/mocks";
import { queueEvent } from "@/services/telemetry";

export default function MocksPage() {
  const blueprints = useQuery({ queryKey: ["mock-blueprints"], queryFn: getBlueprints });
  const history = useQuery({ queryKey: ["mock-history"], queryFn: getHistory });
  const [exam, setExam] = useState("cat");
  const [mock, setMock] = useState<MockConfigured | null>(null);
  const [sectionIdx, setSectionIdx] = useState(0);
  const [qIdx, setQIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [askedAt, setAskedAt] = useState(() => Date.now());
  const [result, setResult] = useState<MockResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const section = mock?.sections[sectionIdx];
  const question = section?.questions[qIdx];

  useEffect(() => { setAskedAt(Date.now()); setAnswer(""); }, [qIdx, sectionIdx]);

  const start = useCallback(async () => {
    setBusy(true); setError(null); setResult(null);
    try {
      const m = await configureMock(exam);
      setMock(m); setSectionIdx(0); setQIdx(0);
      void queueEvent("mock_exam_started", { exam_type: exam, problem_count: m.sections.reduce((n, s) => n + s.questions.length, 0), time_limit: m.time_limit_seconds });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the mock");
    } finally { setBusy(false); }
  }, [exam]);

  const record = useCallback(async () => {
    if (!mock || !question || !section) return;
    const time_ms = Date.now() - askedAt;
    try {
      await submitAnswer(mock.mock_id, question.question_id, answer.trim() || null, time_ms);
      void queueEvent("mock_problem_attempt", { problem_id: question.question_id, time_ms, section: section.key, answered: answer.trim() !== "" });
    } catch { /* keep going; the final submit re-sends nothing — unanswered stays unanswered */ }
    if (qIdx + 1 < section.questions.length) setQIdx(qIdx + 1);
    else if (sectionIdx + 1 < mock.sections.length) { setSectionIdx(sectionIdx + 1); setQIdx(0); }
    else await finish();
  }, [mock, question, section, answer, askedAt, qIdx, sectionIdx]);

  const finish = useCallback(async () => {
    if (!mock) return;
    setBusy(true);
    try {
      const r = await submitMock(mock.mock_id);
      setResult(r);
      void queueEvent("mock_exam_submitted", { exam_type: mock.exam, total_correct: r.score.sections.reduce((n, s) => n + s.correct, 0), deferred_count: r.score.weak_areas.length });
      void history.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit");
    } finally { setBusy(false); }
  }, [mock, history]);

  const total = useMemo(() => mock?.sections.reduce((n, s) => n + s.questions.length, 0) ?? 0, [mock]);

  if (result) {
    return (
      <Shell>
        <h1 className="text-fluid-xl font-semibold">Scorecard</h1>
        <p className="mt-2 text-fluid-lg">{result.score.total_raw} / {result.score.max_raw}
          {result.score.scaled_total !== null && <span className="text-muted-foreground"> · scaled ≈ {result.score.scaled_total}{result.score.scaled_approximate ? " (approx.)" : ""}</span>}
        </p>
        <p className="text-fluid-sm text-muted-foreground">Percentile {result.percentile} among {result.peers} peer{result.peers === 1 ? "" : "s"} · +{result.xp_awarded} XP{result.timing === "client_reported" ? " · timing self-reported" : ""}</p>
        <div className="mt-4 grid gap-2">
          {result.score.sections.map((s) => (
            <div key={s.key} className="rounded-lg border border-border bg-card p-3 text-fluid-sm">
              <div className="flex justify-between"><span className="uppercase">{s.key}</span><span>{s.raw} / {s.max_raw}</span></div>
              <p className="text-muted-foreground">{s.correct} correct · {s.wrong} wrong · {s.unattempted} skipped{s.scaled !== null ? ` · scaled ≈ ${s.scaled}` : ""}</p>
            </div>
          ))}
        </div>
        {result.score.weak_areas.length > 0 && (
          <div className="mt-4 rounded-lg bg-accent p-3 text-fluid-sm">
            <p className="font-medium">Deferred workout</p>
            <ul className="mt-1 text-muted-foreground">{result.score.weak_areas.map((w) => <li key={w.skill}>{w.skill} — {Math.round(w.accuracy * 100)}%</li>)}</ul>
          </div>
        )}
        <button type="button" onClick={() => { setMock(null); setResult(null); }} className="mt-5 w-full rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground">Back to Mock Center</button>
      </Shell>
    );
  }

  if (mock && section && question) {
    const done = mock.sections.slice(0, sectionIdx).reduce((n, s) => n + s.questions.length, 0) + qIdx + 1;
    return (
      <Shell>
        <div className="flex items-center justify-between text-fluid-xs uppercase tracking-wide text-muted-foreground">
          <span>{section.name} · {qIdx + 1}/{section.questions.length}</span>
          <span>{done}/{total}{mock.timers_suppressed ? "" : ` · ${section.minutes} min section`}</span>
        </div>
        <h1 className="mt-4 text-fluid-lg font-medium"><MathText>{question.text}</MathText></h1>
        {question.kind === "mcq" && question.options ? (
          <div className="mt-4 grid gap-2">
            {question.options.map((o) => (
              <button key={o.id} type="button" onClick={() => setAnswer(o.id)} className={`rounded-lg border px-3 py-2 text-left ${answer === o.id ? "border-primary" : "border-border"}`}>
                <span className="mr-2 uppercase text-muted-foreground">{o.id}</span>{o.text}
              </button>
            ))}
          </div>
        ) : (
          <input className="mt-5 w-full rounded-lg border border-border bg-background px-3 py-2" aria-label={question.kind === "essay" ? "Your response" : "Your answer"} placeholder={question.kind === "essay" ? "Your response" : "Your answer"} value={answer} onChange={(e) => setAnswer(e.target.value)} autoFocus />
        )}
        <div className="mt-5 flex gap-2">
          <button type="button" onClick={record} className="flex-1 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground">{done === total ? "Submit exam" : "Next"}</button>
          <button type="button" onClick={finish} disabled={busy} className="rounded-lg border border-border px-4 py-2">End early</button>
        </div>
        <p className="mt-2 text-fluid-xs text-muted-foreground">Leave blank to skip. {mock.rules?.negative_marking ? "Wrong MCQ answers cost marks; TITA does not." : "No negative marking."}</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="text-fluid-xl font-semibold">Mock Center</h1>
      <p className="mt-1 text-fluid-sm text-muted-foreground">Full-length, server-scored. Ads off, sinking skills deferred until the scorecard.</p>
      {error && <p role="alert" className="mt-3 rounded-lg bg-accent p-3 text-fluid-sm">{error}</p>}
      <div className="mt-4 grid gap-2">
        {(blueprints.data?.blueprints ?? []).map((b) => {
          const ready = b.sections.every((s) => s.available);
          return (
            <button key={b.key} type="button" disabled={!ready} onClick={() => setExam(b.key)} className={`rounded-lg border p-3 text-left ${exam === b.key ? "border-primary" : "border-border"} disabled:opacity-50`}>
              <div className="flex justify-between"><span className="font-medium">{b.name}</span><span className="text-fluid-xs text-muted-foreground">{b.total_minutes} min</span></div>
              <p className="text-fluid-xs text-muted-foreground">{b.sections.map((s) => `${s.name} ${s.questions}q${s.available ? "" : " (no pool yet)"}`).join(" · ")}</p>
            </button>
          );
        })}
      </div>
      <button type="button" onClick={start} disabled={busy || !blueprints.data} className="mt-5 w-full rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50">{busy ? "Preparing…" : "Start mock"}</button>
      {history.data && history.data.attempts.length > 0 && (
        <div className="mt-6">
          <h2 className="text-fluid-sm uppercase tracking-wide text-muted-foreground">History</h2>
          <ul className="mt-2 grid gap-1 text-fluid-sm">
            {history.data.attempts.slice(0, 8).map((a) => (
              <li key={a.mock_id} className="flex justify-between"><span className="uppercase">{a.exam}</span><span>{a.total_score ?? "—"} / {a.max_score ?? "—"} · P{a.percentile ?? 0}</span></li>
            ))}
          </ul>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">{children}</main>;
}
