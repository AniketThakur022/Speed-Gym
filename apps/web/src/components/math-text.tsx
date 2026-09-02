"use client";

/**
 * Renders corpus text that mixes prose with LaTeX.
 *
 * The book-extracted corpus is LaTeX-heavy — question text arrives as
 * "Determine $735 + 167$" or a full \[ \begin{array} … \] block — so without a
 * renderer the learner sees raw markup. KaTeX is already the project's math
 * engine (the factory auditor validates with katex_parser), so this keeps one
 * engine across producer and consumer.
 *
 * Rendering is deliberately fault-tolerant: a malformed expression falls back
 * to its source text rather than blanking the question. A learner reading
 * slightly ugly markup can still answer; an empty question is unanswerable.
 */

import { useMemo } from "react";
import katex from "katex";

type Segment = { type: "text" | "math"; value: string; display: boolean };

/** Split on $…$, $$…$$, \(…\) and \[…\] without disturbing surrounding prose. */
export function segment(source: string): Segment[] {
  const pattern = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\$([^$\n]+?)\$|\\\(([\s\S]+?)\\\)/g;
  const segments: Segment[] = [];
  let cursor = 0;

  for (let match = pattern.exec(source); match !== null; match = pattern.exec(source)) {
    if (match.index > cursor) {
      segments.push({ type: "text", value: source.slice(cursor, match.index), display: false });
    }
    const [, blockDollar, blockBracket, inlineDollar, inlineParen] = match;
    const body = blockDollar ?? blockBracket ?? inlineDollar ?? inlineParen ?? "";
    segments.push({
      type: "math",
      value: body,
      display: Boolean(blockDollar || blockBracket),
    });
    cursor = match.index + match[0].length;
  }

  if (cursor < source.length) {
    segments.push({ type: "text", value: source.slice(cursor), display: false });
  }
  return segments;
}

export function MathText({ children, className }: { children: string; className?: string }) {
  const rendered = useMemo(() => {
    return segment(children).map((part, index) => {
      if (part.type === "text") {
        return (
          <span key={index} className="whitespace-pre-wrap">
            {part.value}
          </span>
        );
      }
      try {
        const html = katex.renderToString(part.value, {
          displayMode: part.display,
          throwOnError: true,
          strict: false,
        });
        return <span key={index} dangerouslySetInnerHTML={{ __html: html }} />;
      } catch {
        // Unparsable: show the source so the problem stays answerable.
        return (
          <code key={index} className="text-muted-foreground">
            {part.value}
          </code>
        );
      }
    });
  }, [children]);

  return <span className={className}>{rendered}</span>;
}
