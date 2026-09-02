# PWA reseed from the recovered Exam Arena sources

The 25 TypeScript/TSX files recovered from the APK's dev-build chunks are now the
live `apps/web` app: `recovered/exam-arena-src/` → `apps/web/src/` with real
paths restored. The build is a Next.js 14 static export (4 routes) that renders
with zero console errors, verified in a browser against a served `out/`.

The recovered files were copied **verbatim** except for the fixes listed below;
the untouched originals remain in `recovered/exam-arena-src/` for diffing.

## What had to be authored (it did not survive)

| File | Why |
|---|---|
| `lib/types/dashboard.ts` | Imported everywhere, never leaked. Shapes derived from actual usage in `lib/mock/dashboard.ts` + `services/dashboard.ts`, so mock data and `/api/v1/dashboard/*` responses both type-check. |
| `lib/types/content-feedback.ts` | Imported by `services/offline/db.ts`. `ContentFeedbackRequest` is the payload for the one sync key the client uses (`content/feedback`) — the human-in-the-loop signal into the trust ladder, so the served trust tier travels with the report. |
| `app/globals.css` | The recovered file was only a webpack stub (`export default "49d9fb99609c"`). Token names reconstructed from the class names the pages use; palette from the APK manifest (lime `#C8FF5A` on `#050505`). |
| `tailwind.config.ts`, `postcss.config.js` | Needed to make those tokens real, including the `text-fluid-*` viewport-interpolated sizes the pages reference. |
| `app/layout.tsx` | Wires the recovered providers in the order they expect: Query → Theme → Online → CapacitorInit + AppEntry. |
| `app/dashboard/page.tsx` | **Shim.** Onboarding and AppEntry both navigate to `/dashboard`, but only `/dashboard/learn` was recovered, so that navigation 404'd. Redirects until the real dashboard index is rebuilt. |

`lib/types/template.ts` is now a re-export of `@vmsg/shared-types` so the
SolveAlongTemplate contract cannot drift between the frontend, the backend
Question Bank, and the RAG factory.

## Bugs fixed during the reseed

1. **Rotated refresh tokens were discarded** (`services/api.ts`). The client read
   only `token` from the refresh response. Our server *rotates* refresh tokens
   and treats a replayed one as theft — it revokes the whole device session — so
   the original code would have logged users out on their second refresh. The
   rotated `refreshToken` is now persisted.
2. **Password login never stored a refresh token** (`stores/auth-store.ts`). The
   real-mode branch set `user`/`token` only; the Firebase branch stored it. A
   password login therefore could never refresh at all.
3. **Auth calls ignored `NEXT_PUBLIC_API_URL`** (`stores/auth-store.ts`). They
   used a bare `/api/v1/...` path. Inside the Capacitor/TWA shells the app origin
   serves static files, so those requests could never reach the backend.

## Known gap — the shipped onboarding cannot actually sign anyone in

The recovered onboarding offers only **Continue with Google** and **Continue with
Phone**, and neither touches Firebase: both call `login()` with a hardcoded
`"mock-password"`, which worked only because the APK ran in mock mode. Against a
real backend both paths fail (401), and the Firebase routes they *nominally*
correspond to are deliberate 501 stubs per `api-contract-v1`.

So going live needs an owner decision, one of:

- **wire Firebase** — add the SDK, exchange a real `idToken` at
  `/api/v1/auth/google|phone` (backend seam already exists; config, not contract), or
- **add a credential form** — an email/password screen against the working
  `/api/v1/auth/login`, which is already implemented and tested.

Nothing is blocked on the backend either way; this is a product/UX call.

## Not yet rebuilt

The APK shipped roughly 25 dashboard routes (sprint, duel, practice, mastery,
flashcards, planner, explorer, feed, clubs, friends, leaderboard, achievements,
analytics, history, questions, reports, notifications, settings, profile) plus 15
static technique pages. Only `/dashboard/learn` and `/onboarding` were among the
leaked chunks; the rest must be rebuilt from the design references rather than
recovered. The offline layer (Dexie cache with trusted/sandbox TTLs, the sync
queue) is present and wired, but no screen writes to it yet.
