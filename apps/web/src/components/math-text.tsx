"use client";

/**
 * Math rendering, per docs/rag/LATEX_RENDER_CONTRACT.md.
 *
 * There are two genuinely different kinds of string in this product, and one
 * render call cannot serve both:
 *
 *   mode="prose" (default) — book-extracted `question_text`, which is prose
 *     with inline math delimited by $…$, $$…$$, \(…\) or \[…\]. Segment it and
 *     render only the math runs.
 *   mode="math" — factory `result`/formula fields, which the contract fixes as
 *     RAW math-mode with NO delimiters ("5 \times 7 = 35"). Passing these
 *     through the prose path would render them as plain text, silently, which
 *     is precisely the failure the contract exists to prevent. `description` is
 *     prose and must NOT be rendered as math.
 *
 * `throwOnError: false` is contractual: a malformed formula degrades to visible
 * source instead of blanking a step, and a partially-valid expression still
 * renders the parts KaTeX understands.
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
    segments.push({ type: "math", value: body, display: Boolean(blockDollar || blockBracket) });
    cursor = match.index + match[0].length;
  }

  if (cursor < source.length) {
    segments.push({ type: "text", value: source.slice(cursor), display: false });
  }
  return segments;
}

function renderMath(tex: string, display: boolean): string | null {
  try {
    return katex.renderToString(tex, {
      displayMode: display,
      // Contractual: degrade visibly rather than blanking the step.
      throwOnError: false,
      strict: false,
    });
  } catch {
    // KaTeX still throws on a few pathological inputs even with throwOnError
    // false; fall back to source text so the item stays answerable.
    return null;
  }
}

export function MathText({
  children,
  className,
  mode = "prose",
  display = false,
}: {
  children: string;
  className?: string;
  mode?: "prose" | "math";
  display?: boolean;
}) {
  const rendered = useMemo(() => {
    const source = children ?? "";

    if (mode === "math") {
      const html = renderMath(source, display);
      return html === null ? (
        <code className="text-muted-foreground">{source}</code>
      ) : (
        <span dangerouslySetInnerHTML={{ __html: html }} />
      );
    }

    return segment(source).map((part, index) => {
      if (part.type === "text") {
        return (
          <span key={index} className="whitespace-pre-wrap">
            {part.value}
          </span>
        );
      }
      const html = renderMath(part.value, part.display);
      return html === null ? (
        <code key={index} className="text-muted-foreground">
          {part.value}
        </code>
      ) : (
        <span key={index} dangerouslySetInnerHTML={{ __html: html }} />
      );
    });
  }, [children, mode, display]);

  return <span className={className}>{rendered}</span>;
}

/** A factory `result`/formula field: raw math-mode, no delimiters. */
export function MathExpr({ children, className }: { children: string; className?: string }) {
  return (
    <MathText mode="math" className={className}>
      {children}
    </MathText>
  );
}
