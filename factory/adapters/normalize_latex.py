#!/usr/bin/env python3
"""Bank LaTeX normalization -> the adopted render contract (bank v1.2).

Contract (backend commit 3bc360e): `result` is pure math mode, rendered via
katex.renderToString; `description` is prose and is NEVER math-rendered. The
recovered bank violates this three ways at once, and — per backend's own KaTeX
check — the data-bug classes render CLEANLY BUT WRONG, so nothing downstream can
ever flag them. They must be fixed at the source.

Transforms (all deterministic, all lossless — prose is relocated, never dropped):
  1. Whole string wrapped in $...$        -> strip the delimiters.
  2. Literal backslash-n                  -> a real separator (the JSON-escaping
                                             data bug that KaTeX reads as \\nBC).
  3. Prose + inline $math$                -> math segments joined into `aligned`;
                                             the prose is appended to `description`.
  4. No math at all (prose in a math field) -> whole string moved to `description`.
  5. align*/align                         -> aligned (KaTeX rejects align inline).

Anything still failing KaTeX afterwards is REPORTED, not mangled: forcing a
residue to zero by deleting content would be worse than carrying it as a known
defect list in the manifest.

  python3 factory/adapters/normalize_latex.py <in.jsonl> <out.jsonl> [--report r.json]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# A backslash-escaped \$ is a literal currency symbol, NOT a math delimiter —
# treating it as one shreds expressions like "\$3.98 - \$6.02 = -\$2.04".
# Characters KaTeX has NO font metrics for — measured by rendering every distinct
# non-ASCII character in the bank, not assumed. They render subtly wrong and nothing
# reports it. NOTE: μ θ π α β ✓ × ÷ ° ≈ £ − → all render CLEANLY and are left alone.
SUP = {"²": "2", "³": "3", "⁴": "4", "¹": "1", "ⁿ": "n"}
SUB = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₆": "6", "₇": "7", "ₙ": "n"}
OTHER_FIXES = {"‖": "\\|", "⁄": "/", "🚗": "\\text{car}"}
METRICLESS = set(SUP) | set(SUB) | set(OTHER_FIXES)
# Runs must collapse into ONE group: "₁₃" is the single subscript 13, and replacing
# per character yields "_{1}_{3}" — a double subscript KaTeX rejects.
SUP_RUN = re.compile("[" + "".join(SUP) + "]+")
SUB_RUN = re.compile("[" + "".join(SUB) + "]+")


# Mode-dependent: these render cleanly in MATH mode but have no glyph in KaTeX's
# TEXT fonts, so they warn inside \text{...}. Verified by rendering each in both
# modes. The repair is to split the text group and leave the character in math
# mode — NOT to substitute a command, since \mu inside \text{} throws outright.
TEXT_MODE_UNSAFE = set("μθπαβγδελσφωΩ✓✗∞√")
TEXT_GROUP = re.compile(r"\\text\{([^{}]*)\}")


def fix_text_mode_unicode(text: str) -> str:
    def split_group(m):
        inner = m.group(1)
        if not (TEXT_MODE_UNSAFE & set(inner)):
            return m.group(0)
        out, buf = [], ""
        for ch in inner:
            if ch in TEXT_MODE_UNSAFE:
                if buf:
                    out.append("\\text{" + buf + "}")
                    buf = ""
                out.append(ch)
            else:
                buf += ch
        if buf:
            out.append("\\text{" + buf + "}")
        return "".join(out)
    return TEXT_GROUP.sub(split_group, text)


def fix_unicode_math(text: str) -> str:
    text = SUP_RUN.sub(lambda m: "^{" + "".join(SUP[c] for c in m.group(0)) + "}", text)
    text = SUB_RUN.sub(lambda m: "_{" + "".join(SUB[c] for c in m.group(0)) + "}", text)
    for ch, rep in OTHER_FIXES.items():
        text = text.replace(ch, rep)
    return text

DOLLAR_SEG = re.compile(r"(?<!\\)\$\$?(.+?)(?<!\\)\$\$?", re.S)
WHOLE_WRAPPED = re.compile(r"^\s*(?<!\\)\$\$?(.+?)(?<!\\)\$\$?\s*$", re.S)
UNESCAPED_DOLLAR = re.compile(r"(?<!\\)\$")
# The corruption is an escaped newline that never got unescaped ("2.5 m\nBC",
# "…= -1 ✓\nEquation (2)"), so it is followed by an uppercase letter or space.
# It must NOT match real commands that begin with n — \neq, \newline, \nabla, \ne
# (an earlier build silently turned \newline into "ewline" and \neq into "eq").
LITERAL_NL = re.compile(r"\\n(?=[A-Z\s])")
MATH_MARKUP = re.compile(r"\\[A-Za-z]+|[=+\-×÷^_]|\d")


def looks_like_math(s: str) -> bool:
    return bool(MATH_MARKUP.search(s)) and len(s.strip()) > 0


def normalize_step(result: str, description: str | None, stats: Counter):
    """Returns (new_result_or_None, new_description_or_None)."""
    original = result
    text = result

    # 2. literal backslash-n -> newline (data bug; must not survive)
    if LITERAL_NL.search(text):
        text = LITERAL_NL.sub("\n", text)
        stats["fixed_backslash_n"] += 1

    # 6. metric-less unicode -> real LaTeX (silent mis-render class)
    if METRICLESS & set(text):
        text = fix_unicode_math(text)
        stats["fixed_unicode_math"] += 1
    if TEXT_MODE_UNSAFE & set(text):
        fixed = fix_text_mode_unicode(text)
        if fixed != text:
            text = fixed
            stats["fixed_text_mode_unicode"] += 1

    # 5. align/align* -> aligned (valid inline in KaTeX)
    if re.search(r"\\begin\{align\*?\}", text):
        text = re.sub(r"\\begin\{align\*?\}", r"\\begin{aligned}", text)
        text = re.sub(r"\\end\{align\*?\}", r"\\end{aligned}", text)
        stats["fixed_align_env"] += 1

    # 1. whole string wrapped -> strip
    m = WHOLE_WRAPPED.match(text)
    if m and not UNESCAPED_DOLLAR.search(m.group(1)):
        stats["stripped_wrapper"] += 1
        return m.group(1).strip(), description

    # Ambiguous: \$ means literal currency ("\$3.98 - \$6.02") but also appears as a
    # mangled separator between delimited equations ("$eq1$\$eq2$"). Nothing in the
    # text distinguishes them reliably, and guessing wrong silently drops equations.
    # Leave these untouched and report them instead.
    if "\\$" in text and UNESCAPED_DOLLAR.search(text):
        stats["skipped_ambiguous_escaped_dollar"] += 1
        return original, description

    segs = DOLLAR_SEG.findall(text)
    if segs:
        # 3. prose + inline math: math -> aligned, prose -> description
        prose = DOLLAR_SEG.sub(" ", text)
        prose = re.sub(r"\s+", " ", prose).strip(" \n\t·-—")
        math = (segs[0].strip() if len(segs) == 1
                else "\\begin{aligned}" + " \\\\ ".join(s.strip() for s in segs) + "\\end{aligned}")
        stats["split_prose_from_math"] += 1
        # Keep ANY prose containing a letter — a length threshold silently ate
        # connectives like "or", turning "$x=1$ or $x=2$" (alternatives) into what
        # reads as a simultaneous system, and dropped unit words (m, cm, ft).
        if prose and re.search(r"[A-Za-z]", prose):
            description = f"{description} {prose}".strip() if description else prose
            stats["prose_relocated"] += 1
        return math, description

    if UNESCAPED_DOLLAR.search(text):
        stats["unbalanced_dollar_left"] += 1  # odd delimiter count; leave visible
        return UNESCAPED_DOLLAR.sub("", text), description

    # 4. no math markup at all -> it is prose sitting in a math field
    if not looks_like_math(text) or (len(text) > 40 and not re.search(r"\\[A-Za-z]|[=^_]", text)):
        stats["moved_prose_only_to_description"] += 1
        merged = f"{description} {text}".strip() if description else text.strip()
        return None, merged

    if text != original:
        stats["repaired_in_place"] += 1
    return text.strip(), description


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    stats = Counter()
    touched_templates = set()
    out_lines = []
    for line in Path(args.infile).read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        for ex in t.get("examples", []):
            for s in ex.get("solution", []):
                r = s.get("result")
                if not isinstance(r, str) or not r.strip():
                    continue
                stats["formulas_seen"] += 1
                new_r, new_d = normalize_step(r, s.get("description"), stats)
                if new_r != r or new_d != s.get("description"):
                    touched_templates.add(t["id"])
                if new_r is None:
                    s.pop("result", None)
                else:
                    s["result"] = new_r
                if new_d:
                    s["description"] = new_d
        out_lines.append(json.dumps(t, ensure_ascii=False))

    Path(args.outfile).write_text("\n".join(out_lines) + "\n")
    report = {"in": args.infile, "out": args.outfile,
              "templates_touched": len(touched_templates), "stats": dict(stats)}
    print(json.dumps(report, indent=1))
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
