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

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  bktToMastery,
  freshState,
  processAttempt,
  type TechniqueState,
} from "@vmsg/psychometrics";

import { getPracticeSession, type PracticeItem } from "@/services/practice";
import { checkAnswer, type CheckOutcome } from "@/lib/answer-check";
import { MathText } from "@/components/math-text";

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

  const items = data?.items ?? [];
  const item: PracticeItem | undefined = items[index];
  const techniqueId = item?.technique ?? item?.topic ?? "unknown";

  useEffect(() => {
    setStartedAt(Date.now());
  }, [index]);

  const submit = useCallback(() => {
    if (!item || verdict) return;

    const result = checkAnswer(answer, item.expected_answer, item.answer_check);
    if (result.outcome === "unparsable") {
      setVerdict({ outcome: result.outcome, expected: item.expected_answer });
      return;
    }

    // Only locally-graded items on trusted content may move mastery: a
    // deferred item has no verdict yet, and sandbox content is excluded by
    // the trust ladder.
    if (result.outcome !== "deferred" && item.feeds_mastery) {
      const elapsedSeconds = (Date.now() - startedAt) / 1000;
      setStates((previous) => {
        const current = previous[techniqueId] ?? freshState(techniqueId);
        return {
          ...previous,
          [techniqueId]: processAttempt(current, {
            correct: result.outcome === "correct",
            timeSpentSeconds: elapsedSeconds,
            targetTimeSeconds: 30,
            difficulty: item.difficulty,
          }),
        };
      });
    }

    setVerdict({ outcome: result.outcome, expected: item.expected_answer });
  }, [answer, item, startedAt, techniqueId, verdict]);

  const next = useCallback(() => {
    setAnswer("");
    setVerdict(null);
    setIndex((i) => Math.min(i + 1, items.length));
  }, [items.length]);

  const mastery = useMemo(() => {
    const state = states[techniqueId];
    return state ? Math.round(bktToMastery(state.pLearned)) : null;
  }, [states, techniqueId]);

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

      <input
        className="mt-5 w-full rounded-lg border border-border bg-background px-3 py-2 text-foreground outline-none focus:border-primary"
        placeholder="Your answer"
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        onKeyDown={(event) => event.key === "Enter" && (verdict ? next() : submit())}
        autoFocus
      />

      {verdict && (
        <p className="mt-3 text-fluid-sm">
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
