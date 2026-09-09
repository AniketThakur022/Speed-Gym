# Accessibility gate (WCAG 2.1 AA) — closed on localhost 2026-09-09

The launch gate is "axe-core + Lighthouse ≥95 for WCAG 2.1 AA" (architecture §13,
DEV-01..08). It needs no deployed host: the PWA is a static export, so it can be
served and audited locally.

## Result

| Check | Before | After |
| --- | --- | --- |
| axe-core (wcag2a, wcag2aa, wcag21a, wcag21aa), 9 routes | 0 violations¹ | **0 violations** |
| Lighthouse accessibility, `/` and `/onboarding` | **95** (color-contrast failing) | **100** |
| Manual alpha-composited contrast walk | 16 failures | **0** |

¹ axe reported 0 violations from the start, and that number was misleading twice
over — see "Why axe alone was not enough".

Fixed: **16** colour-contrast failures, **5** unlabelled form controls, **6**
missing live regions.

## Why axe alone was not enough

Three traps, all of which produced a false clean bill of health:

1. **axe returned `color-contrast: incomplete`, not `pass`.** Incomplete means
   axe declined to compute — it cannot resolve a colour through layered
   semi-transparent backgrounds. Lighthouse (same engine, real rendering) scored
   the identical markup 95 with a genuine contrast failure. *An incomplete result
   is not a passing result.*
2. **axe's WCAG-tagged run does not fail a placeholder-only input.** All five form
   controls in the app had `placeholder` and no accessible name. A placeholder is
   not a label: it is not reliably exposed, and it disappears as soon as the
   learner types (4.1.2, 3.3.2). Found by inspecting accessible names directly.
3. **axe cannot detect a missing live region.** The app had **zero** live regions.
   The practice loop's entire feedback — Correct / Not quite / "enter a number" —
   and every hint appeared with no announcement, so a screen-reader user pressed
   Check and heard silence (4.1.3 Status Messages, AA).

An audit that had stopped at "axe: 0 violations" would have shipped all three.

## The contrast finding

`text-muted-foreground/70` composites `#a3a3a3` down to `#767676` on `#0d0d0d`:
**4.27:1**, under the 4.5:1 required for 11px text. Every lower step (`/60`,
`/50`, `/45`, `/40`, `/25`) is worse, because reducing opacity on light-grey text
over a near-black background pulls it *toward* the background.

Measured minimum passing alpha for `--muted-foreground` on this palette:

| Background | min alpha for 4.5:1 (body text) |
| --- | --- |
| `#050505` page | /72 |
| `#0d0d0d` landing | /73 |
| `#121212` card | /74 |

**So dim-by-opacity is not available for body text on this palette.** There is no
way to express five distinct muted levels for small text and stay AA; that
hierarchy has to come from size and weight instead. All body-text usages now use
the token at full strength (7.4–8.1:1). Three non-text usages stay at `/70`
(4.2:1) — icons and a close control, which need 3:1 under 1.4.11, not 4.5:1.

`text-primary/*` and `text-foreground/*` were checked and pass (6.3–10.8:1 and
8.7–17.2:1): the lime primary and near-white foreground have contrast to spare.

## Method (how to re-run)

```bash
# 1. Build against the local API (mock mode hides the real screens)
cd apps/web && NEXT_PUBLIC_API_URL=http://localhost:8000 NEXT_PUBLIC_API_MOCK=false npm run build

# 2. Serve on 3100 — it must be a port in the API's CORS allow-list, or every
#    authenticated screen renders its error state and you audit nothing.
#    (.claude/launch.json has the `pwa-static` entry.)

# 3. Lighthouse, public routes
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  npx lighthouse@12 http://localhost:3100/ --only-categories=accessibility \
  --chrome-flags="--headless=new" --output=json --output-path=/tmp/lh.json
```

For the authenticated routes, seed the persisted auth store in the browser and
reload — the guard in `components/ui/app-entry.tsx` renders onboarding for every
route until it sees a session:

```js
// after POST /api/v1/auth/register
localStorage.setItem('exam-arena-auth', JSON.stringify({
  state: { user, token, refreshToken, isAuthenticated: true, isOnboarded: true },
  version: 0,
}));
```

Then inject axe-core and run with the four WCAG tags. **Wait for hydration
first** — running immediately after navigation audits an empty DOM and reports a
meaningless 0 violations with 0 passes.

## Coverage and what is still open

Audited populated: `/`, `/onboarding`, `/dashboard`, `/dashboard/practice`
(real graph problem), `/dashboard/friends`, `/dashboard/billing`,
`/dashboard/learn`.

**Not audited populated:** `/dashboard/mocks` and the daily challenge on
`/dashboard/leaderboard` render their empty/503 state, because no exam pool is
bound yet under the staged serving path. Those screens' populated markup is
unaudited and should be re-run once a section binds.

**Lighthouse cannot reach the authenticated routes** — it starts a clean Chrome
profile, so the seeded session does not survive. Those routes are covered by
axe-core (the same engine Lighthouse uses for accessibility) plus the manual
contrast walk. Wiring Lighthouse's Node API with a Puppeteer login would close
that gap and is the natural CI step.

**Two caveats about the manual contrast walk**, which reads computed styles
directly: it must composite the *whole* background stack (an early version
treated `bg-primary/20` as opaque and produced ratios of exactly 1.00), and it
cannot see `background-image`, so gradient-backed elements read as failures. The
one such element, the active exam chip, was verified by hand against both
gradient stops: 13.6:1 and 15.8:1.

Screen-reader behaviour itself (VoiceOver/TalkBack) has not been exercised; the
live regions above are the mechanism, not proof that the announcement reads well.
