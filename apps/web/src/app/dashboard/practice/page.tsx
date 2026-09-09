"use client";

/**
 * The practice loop — the product's core screen.
 *
 * Everything that decides what the learner sees next runs on-device: answer
 * checking (for locally-checkable items), the BKT update, and mastery state.
 * The server is the system of record, never in the hot path of answering a
 * problem.
 *
 * Two rules are enforced visibly here because getting them wrong is a
 * correctness bug, not a cosmetic one:
 *   - Sandbox content is playable but must not move mastery (`feeds_mastery`).
 *   - Items needing a server check are recorded as attempted-but-unscored
 *     rather than guessed at locally.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  bktToMastery,
  classifyState,
  freshState,
  processAttempt,
  type TechniqueState,
} from "@vmsg/psychometrics";

import { getMastery, getPracticeSession, type PracticeItem } from "@/services/practice";
import { checkAnswer, type CheckOutcome } from "@/lib/answer-check";
import { MathText } from "@/components/math-text";
import { flushEvents, queueEvent } from "@/services/telemetry";
import { askHint, type HintOut } from "@/services/chat";
import { uuid } from "@/lib/telemetry-core";

const DOMAIN = "vedic-math";

type Verdict = { outcome: CheckOutcome; expected: number | null };

const OUTCOME_COPY: Record<CheckOutcome, string> = {
  correct: "Correct",
  incorrect: "Not quite",
  deferred: "Recorded — needs a server check",
  unparsable: "Enter a number to continue",
};

export default function PracticePage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["practice-session"],
    queryFn: () => getPracticeSession({ size: 10 }),
  });

  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [states, setStates] = useState<Record<string, TechniqueState>>({});
  // Telemetry contract (docs/backend/TELEMETRY.md): one session id for the
  // whole screen, a problem_attempt per check, one session_end at the end.
  const sessionId = useMemo(() => uuid(), []);
  const sessionStartedAt = useMemo(() => Date.now(), []);
  const counters = useRef({ attempted: 0, correct: 0, deferred: 0 });
  const startedRef = useRef(false);
  const endedRef = useRef(false);
  const [hint, setHint] = useState<HintOut | null>(null);
  const [hintBusy, setHintBusy] = useState(false);

  // Mastery is hydrated from the server's latest snapshot. Without this the
  // screen recomputed every skill from pInit and the session_end snapshot —
  // which every server reader treats as the WHOLE mastery picture — replaced
  // the learner's history with just the skills touched in this one session.
  const { data: persisted } = useQuery({
    queryKey: ["practice-mastery"],
    queryFn: getMastery,
    staleTime: Infinity,
  });
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (!persisted || hydratedRef.current) return;
    hydratedRef.current = true;
    setStates((previous) => {
      const seeded: Record<string, TechniqueState> = {};
      for (const [id, raw] of Object.entries(persisted.technique_states ?? {})) {
        const base = freshState(id);
        const pLearned = typeof raw?.pLearned === "number" ? raw.pLearned : base.pLearned;
        const masteryScore = typeof raw?.masteryScore === "number"
          ? raw.masteryScore
          : Math.round(pLearned * 100);
        const consecutiveCorrect = raw?.consecutiveCorrect ?? base.consecutiveCorrect;
        const consecutiveErrors = raw?.consecutiveErrors ?? base.consecutiveErrors;
        seeded[id] = {
          ...base,
          pLearned,
          masteryScore,
          accuracyScore: raw?.accuracyScore ?? base.accuracyScore,
          consecutiveCorrect,
          consecutiveErrors,
          totalAttempts: raw?.totalAttempts ?? base.totalAttempts,
          totalCorrect: raw?.totalCorrect ?? base.totalCorrect,
          // Older snapshots stored only {pLearned, state}; recompute rather than
          // trusting a label that may not match the numbers we just restored.
          state: classifyState({ masteryScore, consecutiveCorrect, consecutiveErrors }),
        };
      }
      // Anything already updated in this session wins over the snapshot.
      return { ...seeded, ...previous };
    });
  }, [persisted]);

  const items = data?.items ?? [];
  const item: PracticeItem | undefined = items[index];
  // Mastery is keyed on the graph :Skill name only. Falling back to a corpus
  // display label here would accumulate state against a vocabulary that is
  // ~96% disjoint from the skill graph, so it could never be joined back.
  const skillId = item?.skill ?? null;

  useEffect(() => {
    setStartedAt(Date.now());
  }, [index]);

  useEffect(() => {
    if (!data || startedRef.current) return;
    startedRef.current = true;
    void queueEvent(
      "session_start",
      { domain: DOMAIN, session_type: "practice", requested: data.summary.requested, served: data.summary.served },
      { session_id: sessionId },
    );
  }, [data, sessionId]);

  const submit = useCallback(() => {
    // An `unparsable` verdict is a prompt to type a number, NOT a graded
    // attempt: it must stay re-submittable. Treating it like a real verdict
    // deadlocked the button, and the only escape (Enter) silently skipped the
    // problem without recording anything.
    if (!item || (verdict && verdict.outcome !== "unparsable")) return;

    const result = checkAnswer(answer, item.expected_answer, item.answer_check);
    if (result.outcome === "unparsable") {
      setVerdict({ outcome: result.outcome, expected: item.expected_answer });
      return;
    }

    counters.current.attempted += 1;
    if (result.outcome === "correct") counters.current.correct += 1;
    if (result.outcome === "deferred") counters.current.deferred += 1;
    void queueEvent(
      "problem_attempt",
      {
        skill: skillId,
        problem_id: item.template_id,
        is_correct: result.outcome === "correct" ? true : result.outcome === "incorrect" ? false : null,
        time_ms: Date.now() - startedAt,
        domain: DOMAIN,
        difficulty: item.difficulty,
        feeds_mastery: item.feeds_mastery,
        answer_check: item.answer_check,
        // A server-checked item is graded later, off this device — so the
        // typed answer has to travel with the event. Dropping it made the
        // attempt permanently ungradable while still counting as attempted.
        submitted_answer: result.outcome === "deferred" ? answer.trim() : undefined,
        hint_level: hint?.level ?? 0,
      },
      { session_id: sessionId, session_elapsed_ms: Date.now() - sessionStartedAt },
    );

    // Only locally-graded items on trusted content with a resolvable skill may
    // move mastery: a deferred item has no verdict, sandbox content is excluded
    // by the trust ladder, and an unattributable item has nowhere to record it.
    if (result.outcome !== "deferred" && item.feeds_mastery && skillId) {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      setStates((previous) => {
        const current = previous[skillId] ?? freshState(skillId);
        return {
          ...previous,
          [skillId]: processAttempt(current, {
            correct: result.outcome === "correct",
            timeSpentSeconds: elapsedSeconds,
            targetTimeSeconds: 30,
            difficulty: item.difficulty,
          }),
        };
      });
    }

    setVerdict({ outcome: result.outcome, expected: item.expected_answer });
  }, [answer, item, startedAt, skillId, verdict, hint, sessionId, sessionStartedAt]);

  const next = useCallback(() => {
    setAnswer("");
    setVerdict(null);
    setHint(null);
    setIndex((i) => Math.min(i + 1, items.length));
  }, [items.length]);

  const mastery = useMemo(() => {
    const state = skillId ? states[skillId] : undefined;
    return state ? Math.round(bktToMastery(state.pLearned)) : null;
  }, [states, skillId]);

  // session_end once, when the last item is passed; then flush so the
  // dashboard reflects this session as soon as we are online.
  useEffect(() => {
    if (isLoading || !items.length || index < items.length || endedRef.current) return;
    endedRef.current = true;
    // The whole state, not just {pLearned, state}: this snapshot is what the
    // next session hydrates from, and a lossy one would reset the counters
    // that classifyState depends on.
    const technique_states = states;
    void queueEvent(
      "session_end",
      {
        domain: DOMAIN,
        session_type: "practice",
        problems_attempted: counters.current.attempted,
        problems_correct: counters.current.correct,
        // Attempted but not graded on-device; the server must not score these
        // out of the attempted total.
        problems_deferred: counters.current.deferred,
        technique_states,
      },
      { session_id: sessionId, session_elapsed_ms: Date.now() - sessionStartedAt },
    ).then(() => flushEvents());
  }, [isLoading, items.length, index, states, sessionId, sessionStartedAt]);

  const requestHint = useCallback(async () => {
    if (!item || hintBusy) return;
    setHintBusy(true);
    try {
      const out = await askHint(item.template_id, (hint?.level ?? 0) + 1, undefined, hint?.hint);
      setHint(out);
    } catch {
      setHint({ mode: "hint_ladder", level: hint?.level ?? 0, max_level: hint?.max_level ?? 0, hint: "Hints need a connection.", answer_withheld: true, budget_remaining: 0 });
    } finally {
      setHintBusy(false);
    }
  }, [item, hint, hintBusy]);

  if (isLoading) {
    return <Shell><p className="text-muted-foreground">Loading session…</p></Shell>;
  }

  if (isError) {
    return (
      <Shell>
        <p className="text-muted-foreground">
          Could not reach the content service. Practice needs one session downloaded
          before it can run offline.
        </p>
      </Shell>
    );
  }

  if (!items.length) {
    const withheld = Object.entries(data?.summary.withheld ?? {});
    return (
      <Shell>
        <p className="text-muted-foreground">No problems are available to serve.</p>
        {withheld.length > 0 && (
          <ul className="mt-3 text-fluid-sm text-muted-foreground">
            {withheld.map(([reason, count]) => (
              <li key={reason}>
                {count} withheld — {reason}
              </li>
            ))}
          </ul>
        )}
      </Shell>
    );
  }

  if (!item) {
    const answered = Object.values(states).reduce((sum, s) => sum + s.totalAttempts, 0);
    return (
      <Shell>
        <h1 className="text-fluid-xl font-semibold">Session complete</h1>
        <p className="mt-2 text-muted-foreground">
          {answered} problem{answered === 1 ? "" : "s"} scored on-device.
        </p>
        {Object.entries(states).map(([id, state]) => (
          <div key={id} className="mt-3 rounded-lg border border-border bg-card p-3">
            <div className="flex items-center justify-between">
              <span className="text-fluid-sm">{id}</span>
              <span className="text-primary">{Math.round(bktToMastery(state.pLearned))}%</span>
            </div>
            <p className="mt-1 text-fluid-xs uppercase tracking-wide text-muted-foreground">
              {state.state}
            </p>
          </div>
        ))}
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="flex items-center justify-between text-fluid-xs uppercase tracking-wide text-muted-foreground">
        <span>
          {index + 1} / {items.length}
        </span>
        <span>{mastery === null ? "—" : `${mastery}% mastery`}</span>
      </div>

      <h1 className="mt-4 text-fluid-lg font-medium">
        <MathText>{item.question_text ?? ""}</MathText>
      </h1>

      <div className="mt-2 flex flex-wrap gap-2 text-fluid-xs text-muted-foreground">
        {(item.technique || item.topic) && <Tag>{item.technique || item.topic}</Tag>}
        <Tag>difficulty {item.difficulty}</Tag>
        {!item.feeds_mastery && <Tag>sandbox · not scored</Tag>}
        {item.answer_check === "server_sympy" && <Tag>server-checked</Tag>}
      </div>

      {hint && (
        <p role="status" aria-live="polite" className="mt-3 rounded-lg bg-accent p-3 text-fluid-sm">
          <span className="text-fluid-xs uppercase tracking-wide text-muted-foreground">Hint {hint.level}/{hint.max_level} · answer withheld</span>
          <br />
          <MathText>{hint.hint}</MathText>
        </p>
      )}
      {!verdict && (!hint || hint.level < hint.max_level) && (
        <button type="button" onClick={requestHint} disabled={hintBusy} className="mt-3 text-fluid-sm text-muted-foreground underline">
          {hintBusy ? "Thinking…" : hint ? "Next hint" : "Need a hint?"}
        </button>
      )}

      <input
        className="mt-5 w-full rounded-lg border border-border bg-background px-3 py-2 text-foreground outline-none focus:border-primary"
        aria-label="Your answer"
        placeholder="Your answer"
        value={answer}
        onChange={(event) => {
          setAnswer(event.target.value);
          // Typing is the fix for "enter a number", so clear that prompt.
          setVerdict((v) => (v && v.outcome === "unparsable" ? null : v));
        }}
        onKeyDown={(event) =>
          event.key === "Enter" &&
          (verdict && verdict.outcome !== "unparsable" ? next() : submit())
        }
        autoFocus
      />

      {verdict && (
        <p role="status" aria-live="polite" className="mt-3 text-fluid-sm">
          <span className={verdict.outcome === "correct" ? "text-primary" : "text-foreground"}>
            {OUTCOME_COPY[verdict.outcome]}
          </span>
          {verdict.outcome === "incorrect" && verdict.expected !== null && (
            <span className="text-muted-foreground"> · answer {verdict.expected}</span>
          )}
        </p>
      )}

      <button
        type="button"
        onClick={verdict && verdict.outcome !== "unparsable" ? next : submit}
        className="mt-5 w-full rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground"
      >
        {verdict && verdict.outcome !== "unparsable" ? "Next" : "Check"}
      </button>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">{children}</main>
  );
}

function Tag({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full bg-accent px-2 py-1">{children}</span>;
}
