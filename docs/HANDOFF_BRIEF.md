# Exam Arena / Vedic Math Speed Gym — Project & Go-To-Market Handoff Brief

**Prepared:** 2026-09-04 · **Owner:** Aniket (AMH Solutions) · **Status:** rebuild in progress, pre-launch

---

## How to use this document

This is a **self-contained briefing**. Paste or upload it into a new Claude chat and that chat will have everything it needs — the product, its complete feature set, the architecture, the current build state, the market analysis already done, and the go-to-market recommendations already made. It assumes the reader has **no access to the codebase, no prior memory, and no other documents**.

**If you are the new chat reading this:** you are picking up a live product + marketing discussion with the project's owner. Sections 1–6 are the product. Sections 7–9 are the marketing work already completed. Section 10 says what is open and where the conversation stopped. Treat every figure here as verified unless it is explicitly marked as an estimate. Do not re-derive what is already settled; ask about what section 10 lists as open.

---

## 1. What the product is

**Vedic Math Speed Gym (VMSG)**, shipped to consumers as **Exam Arena** (`com.examarena.app`, examarena.com) — an **offline-first speed-mathematics and exam-preparation app** for web (PWA), Android and iOS (Capacitor shells). Built by AMH Solutions for a client against **RFP v7.2, 365 numbered specifications**.

**Subjects / domains:** Vedic mathematics, CAT, GMAT, GRE, banking.

**The core idea:** it is not a question bank. It watches *how* a learner gets things wrong, drills exactly those weaknesses, and wraps the drilling in competitive play. Two structural commitments make it different from everything else in its category:

1. **The entire practice loop runs on the device** — problem selection, answer checking, mastery updates, fatigue detection. On a plane or in a metro tunnel it behaves identically to a full-signal session. The server is the system of record but is never in the hot path of answering a problem.
2. **No AI anywhere near the game loop, ever.** Every problem a learner sees was generated and verified by an overnight batch factory long before it was served. The app never asks a model to invent a question mid-session, so a learner can never be shown a hallucinated answer.

**Brand direction (already set, and good):** *"Not a coaching platform. A competitive battlefield."* Lime `#C8FF5A` on near-black `#050505` — deliberately unlike the pastel blue/purple of the rest of Indian edtech.

**Commercial model:** free tier = manual Topic Browser + ads. Paid tier unlocks the **Decision Engine**, the planner that composes every session. Tiers as specced: Free $0 / Pro $6 / Bundle-2 $9.60 / Bundle-3 $12.60 per month (a "bundle" = multiple concurrent exam lanes). Stripe + Razorpay. Family plans with up to 3 child seats. COPPA kids mode.

**Delivery model:** Phase 1 = 15 weeks, everything built, running on 2 droplets ($80–120/month). Phase 2 = 6 weeks of activation, triggered at 5,000 daily active users, scaling to 22 droplets ($836/month). **Phase-2 features are built during Phase 1 and dark-launched behind feature flags** — activation is a config flip, not a redeploy.

---

## 2. Complete feature map

Legend: **[P1]** live in Phase 1 · **[flag]** built in Phase 1 but switched off until Phase 2 · **[P2]** Phase-2 scope only · **[factory]** batch pipeline, not user-facing.

### 2.1 Learning engine (the "Decision Engine" — paid tier)

- **[P1] Bayesian Knowledge Tracing** — per-skill mastery. Fixed priors: P(L₀)=0.35, P(T)=0.14, P(S)=0.10, P(G)=0.20, P(F)=0.007/day. Inter-session decay. Fluid gate at P(L) ≥ 0.85. Runs client-side.
- **[P1] Session composer, 60/20/20** — 60% skills you're fluid in, 20% sinking skills that are decaying, 20% new frontier. Persona overrides (SpeedDemon 70/15/15, BrainTrainer 50/30/20). Empty-bucket redistribution. Runs on-device in ~50 ms.
- **[P1] Wrong-answer guards** — max 3 cycles per technique, 5 wrongs per session, 4 consecutive wrongs forces a break, 3 ping-pong toggles in 10 locks the learner into hybrid mode for 24 hours.
- **[P1] Mastery bands → render routing** — Fractured [0, .35) / Fragile [.35, .70) / Fluid [.70, .90) / Mastered [.90, 1] mapped onto guided / solve-along / quick presentation. A weak skill gets taught; a strong one gets raced.
- **[P1] Spaced repetition** — 1 / 3 / 7 / 14 / 30 / 90-day intervals, per-skill decay, feeding a sinking-skill queue.
- **[P1] Cold-start calibration** — a 6-problem warm-up. Correct first try → prior 0.80, hint-or-slow → 0.50, wrong → 0.20.
- **[P1] Cognitive load & fatigue** — a base cognitive-load score per problem (operations, digits, carries, length, special symbols); a fatigue index = 0.40·latency + 0.35·accuracy + 0.25·entropy, with age-modulated z-score gates. Triggers reduce difficulty, force guided mode, cap attempts, and shift the exam-sprint ratio across a 120-minute session (70/30 → 50/50 → 30/70).
- **[P1] Subject router** — dispatches by subject before composition: Quant → IRT + PFA, Logic/DI → Glicko-2, Verbal → DINA. Age time-multipliers scale every budget off a 30-second base.
- **[P1] Behavioural profiling** — K-means personas that shift session mix, pacing and taunt frequency.
- **[shadow] IRT** — 2PL-lite (one θ per subject) live; full 3PL computed and logged but not routing until items have ≥200 responses each.
- **[shadow] Glicko-2** for logic/data-interpretation, across 8 sub-rating facets, with inactivity decay.
- **[shadow] DINA** for verbal — 5 skills (vocabulary, structure, tone, theme, syntax) over a curated Q-matrix; needs ≥640 calibrated attempts before it can route.
- **[P2] hIRT, Thompson-sampling difficulty bandit, weekly churn GBT** — named, not built in Phase 1.

> "Shadow mode" is a deliberate protection: the models are code-complete and logging, but they do not route learners until their data thresholds are met. At 0–5,000 users these models would otherwise produce cold-start garbage.

### 2.2 Content & teaching

- **[P1] 16 Vedic sutras** implemented as *executable methods* that emit their own step-by-step working — Nikhilam, Urdhva-Tiryagbhyam, Ekadhikena, Yavadunam, Paravartya, Shunyam, Sankalana, Puranapuranabhyam, Chalana-Kalana, Vyashti, Shesanyankena, Sopantyadvayam, Gunita-Samuccaya and others.
- **[P1] Solve-along walkthroughs** — step-by-step guided solutions with **11 visual scaffold types**: arrow matrix, place-value chart, number line, grid construction, equation chain, shape canvas, coordinate grid, textual scaffold, rotation diagram, formula generalization, Venn diagram. Pure client-side SVG with step reveal.
- **[P1] Topic Browser** — manual subject → topic → sub-topic navigation. This is the *entire* free-tier practice surface, and what the paid planner replaces.
- **[P1] Explainer cards** — formula-first: the formula always visible, progressive disclosure below it, difficulty tabs at the third level.
- **[P1] Trap taxonomy** — tagged error patterns attached to problems, mapped onto cognitive faculties (working-memory overflow, inhibitory control, pattern switch). Repeated failure of one type can force a teaching mode.
- **[P1] Parametric generation** — templates instantiate fresh problems with randomised parameters, SymPy-checked for equivalence, rejected if trivial. 5-second timeout, circuit breaker after 10 timeouts, static fallback. Practice only — **never mock exams, never calibration**.
- **[P1] Mock exams** — CAT / GMAT / GRE blueprints with sections, timing, percentile scoring, section breakdowns, weak-area extraction, deferred sinking skills. CAT negative marking is −1/3 on MCQs.
- **[P1] Study chatbot** — opt-in, online-only, isolated from the game loop. Reads mastery state, cognitive load and the last 3 failed concepts; retrieves grounded curriculum. **Hard-gated to hints and scaffolding — never gives direct answers.**
- **[planned] Reference library** — 25 written reference pages. The one genuine content-writing task left.

### 2.3 The content factory (batch, zero runtime consumers)

- **[factory] 6-station ingestion** — chunker → digitizer (PDF→markdown) → context lookup → grounded triplet extraction against an ontology registry → SymPy maths audit → dual-DB ingest. Runs only when a book is added.
- **[factory] 7-stage auditor** on every question — fields → LaTeX renders → SymPy recomputation → domain rules → trap sanity → dedup → a 2-of-3 panel of independent AI judges. Stages 1–6 run fully offline.
- **[factory] Trust ladder** — `QUARANTINED → SANDBOX → TRUSTED → LIVE`. Sandbox content (≤50 exposures) is playable but **never feeds mastery and never appears in a mock exam**. Trusted needs ≥30 users at ±15% of expected accuracy; Live needs ≥100 users stable for 14 days.
- **[factory] Hourly replenishment ladder** — when a pool drops below 50 items: T1 resample static → T2 generate next difficulty → T3 bridge to a sibling topic → T4 LLM regenerate (grounded in the graph + top-5 chunks; the *only* AI path, still batch) → T5 convert an explainer, then alert.
- **[factory] Pattern freeze** — 3 quarantined children of one generation pattern freezes the whole pattern.
- **[factory] Prerequisite closure precompute** — the skill dependency graph is derived and its transitive closure precomputed, so "what must I know before this?" is a lookup, not a live traversal.

### 2.4 Gaming

- **[P1] Solo modes** — speed race and accuracy duel against a bot.
- **[P1] 1v1 duels** — matchmaking on a composite of ability and ELO (0.4·θ + 0.6·ELO), pairing within ±100 ELO widening every 5 seconds, live round sync, rematches, ELO updates (K=32 duels / 40 tournaments).
- **[P1] Bot backfill** — after 15 seconds waiting, an IRT-calibrated bot joins. Four personas (overthinker, speedster, improver, choker) with realistic timing, hesitations and plausible wrong answers. **Win-rate capped at 45%.** Never shown to children's accounts, never in ranked tournaments or the daily challenge, ELO weighted at 0.5×, human-plausible IDs only.
- **[P1] Four play topologies** — online, pass-and-play on one device, hotspot peer-to-peer (WebRTC), QR-discovered nearby play (HMAC-signed, 300-second one-time payloads).
- **[P1] Ghost racing** — race a recorded run.
- **[P1] Daily challenge** — one shared problem set per day, global percentile ranking, no bots.
- **[P1] Shareable clips** — dual consent required, opponent anonymised.
- **[P1] Comedy taunts / rage-bait** — generated post-match from solve-latency differences, gated by behavioural cluster (aggressive persona every 3 matches, perfectionist every 5, deliberate/rebuilder never), disabled after 3 losses, off entirely under age 10.
- **[P1] Anti-cheat** — server-authoritative answers, sub-200ms solves rejected, keystroke-interval checks, per-player shuffled queues, 5-second spectator delay, impossible-speed and mastery-jump flags, 10s heartbeat with 15s disconnect grace.
- **[flag] Boss battles** — co-op raid, HP = players × 3, wrong answers heal the boss, 3 wrongs enrage it (+1/3 problems), victory grants +0.05 P(L) on the boss topic.
- **[flag] Relay races** — team baton passing, max 2 retries at +10s, team difficulty = weighted θ × 1.10.
- **[flag] Swiss tournaments** — 5–7 rounds, Buchholz tiebreak, subject brackets, top-8 triathlon final.

### 2.5 Social & growth

- **[P1] Friends, streaks, achievements, leaderboards** (global / friends / subject-scoped), QR friend pairing.
- **[P1] Referral ladder** — 15 referrals → +1 lane, 30 → offline queue, 45 → custom difficulty + analytics, 60 → **lifetime** ad-free Pro. Referee gets a 7-day Pro trial.
- **[P1] Referral fraud gates** — a referral counts only after real usage: 5+ sessions across 2+ dates totalling ≥25 minutes, average >5 min and ≥10 problems, plus fingerprint / email / IP-range / behavioural-z uniqueness, ≤3 signups per IP per 24h, 7-day cooldown.
- **[flag] Virtual hubs** — city / society / school / college / café communities, pre-seeded in Bangalore, Mumbai, Delhi with 10 bots each, auto-archived below 5 users in 30 days.
- **[flag] Location gamification** — proximity discovery, café QR check-in for 2× XP for 60 minutes, GPS geofence ±20 m.

### 2.6 Accounts, money & family

- **[P1] Auth** — email/password, HS256 JWT with 15-minute access tokens, rotating refresh tokens with **replay detection** (presenting an already-rotated token revokes every session on that device fingerprint). Google and phone sign-in are on the contract behind a pluggable identity provider, returning 501 until configured.
- **[P1] QR scanner login** — approve a signed 300-second one-time code from an already-authenticated phone.
- **[P1] Four tiers** with a track-switch lock: free users locked 30 days (bypass via 15 verified referrals), paid users switch freely.
- **[P1] Stripe + Razorpay** — signature-verified webhooks, sticky-routed to the owner node to dodge replication lag.
- **[P1] Offline entitlement tokens** — server signs `HMAC-SHA256(user_id:expires_at)` on every sync; client verifies locally with a 3-day grace period. Tampered or expired → downgrade to free, ads back on. Re-validated server-side on next online action.
- **[P1] Family plans** — parent anchor + up to 3 child seats, volume discount curve (100/80/60%), individually suspendable, seat count synced from the billing webhook.
- **[P1] Kids mode (COPPA)** — under-13: no ads, no bots, no taunts, minimised tracking, parental consent gate, suppressed timers, 10-minute session cap (parent may raise to 20).
- **[P1] Ad engine** — never during solving, guided mode, solve-along, onboarding, remediation or a reveal. Only dashboard, post-session (5s interstitial), profile and settings. Max 180 seconds of ads per hour, 10-minute cooldown. 15 minutes of practice buys past a 30-second ad wall. Videos pre-cache on Wi-Fi above 20% battery; impressions queue offline.

### 2.7 Platform & operations

- **[P1] Offline-first storage** — IndexedDB (Dexie) holds profiles, events, an offline problem pool (500 items, LRU, 7-day expiry), cached ad units, sync queue. Eviction is priority-scored: session_end and subscription events are never dropped; page_view goes first. Buffer 500 (iOS 50), overflow emits an audit event.
- **[P1] Sync engine** — flush on session end, every 5 attempts when intermittent, exponential backoff 1→2→4→8→30s, immediate flush on reconnect. Idempotent by `event_id`. Target: p95 < 500 ms; 500 queued events replay in under 30 seconds on Wi-Fi. **On multi-device conflict the server recomputes mastery from raw events — it never merges P(L) directly.**
- **[P1] Mobile shells** — Android TWA/Capacitor (target SDK 34, min 24), iOS WKWebView/Capacitor (target 16+, min 14). Both force `navigator.storage.persist()` at first launch (iOS evicts IndexedDB otherwise). FCM/APNs push. Cold start <2s, ≥60fps, <2–3%/hr battery. Staged rollout halts if crash-free drops below 99.5%.
- **[P1] Feature flags** — Postgres-backed, Redis-cached, read at session start; emergency kill switch can disable any feature or the whole ad engine in seconds.
- **[P1] Telemetry** — 33 events through a 7-step lifecycle into tiered storage: IndexedDB → 90-day Postgres partitions → Parquet cold storage → permanent aggregates. **Engagement telemetry may be sampled at 10% above 10k DAU; anything feeding mastery is never sampled** (sampling attempts produces P99 ≈ 69 percentage-point mastery error).
- **[P1] Admin console** — materialized dashboards (DAU/MAU, revenue cohorts, ad impressions, technique summaries, pending-sync debt) refreshed every 15 minutes; content operations; fraud alert gate at >3% failures.
- **[P1] Quality gates** — WCAG 2.1 AA, ≥80% statement coverage, contract tests across all 22 REST endpoints and 9 WebSocket events, 12 golden end-to-end journeys, psychometric known-answer suites, k6 load profiles, OWASP scan, and 8 go/no-go gates before launch.

---

## 3. Architecture in brief

Five layers:

| Layer | Role | Stack |
|---|---|---|
| **The app** | Practice, games and scoring on-device; works with no signal | Next.js 14 App Router PWA (static export), Zustand, TanStack Query, Dexie/IndexedDB, Workbox, KaTeX; Capacitor shells |
| **The brain** | Decides what to practise next and how hard | Client-side TypeScript: BKT, allocator, scheduler, calibration, fatigue monitor, subject router |
| **The referee** | Live multiplayer, authoritative on state and timing | Node Socket.IO v4, port 3001, 9 canonical events, shared JWT secret with the API |
| **The ledger & the GPS** | Facts and history / the map of how topics connect | PostgreSQL 15 + pgvector (~39 tables, partitioned events) and Neo4j 5 (skills, problems, traps, sutras) — **never merged**; Redis 7 for cache, lobbies, rate limits |
| **The kitchen** | Generates and verifies content overnight; never touches the live game | Celery workers + beat, SymPy, pgvector retrieval, batch LLM judges — nightly 00:00 UTC + hourly top-up |

Traefik at the edge (TLS, `/api` → FastAPI, `/game` wss → game server). PgBouncer in front of Postgres. FastAPI is the application backend; Node is **only** the game server.

**API contract (settled):** base `{API_URL}/api/v1`, Bearer JWT. The frozen shape from the shipped APK is the outer contract; the architecture doc's auth semantics are implemented inside it. Webhooks stay at `/api/webhooks/{stripe,razorpay}`.

**Neo4j live schema (verified against the June export, not the docs):** `:Skill` 467 (not the stale `:Technique` label), `:Problem` 807, `:SolveAlong` 791, `:Explainer` 590, `:Trap` 908, `:Sutra` 16, `:Book` 6. `PREREQUISITE_OF` is **Skill→Problem** (a Q-matrix, bipartite, depth-1, not transitive) — the architecture doc's technique→technique reading is wrong. `REQUIRES` is Skill→Skill (dependent → prerequisite).

---

## 4. Content assets

**The knowledge graph (delivered, audited):**

| Asset | Count |
|---|---|
| Skills tracked | 467 |
| Verified practice problems | 807 (97.8% machine-verified) |
| Solve-along walkthroughs | 791 |
| Concept explainers | 590 |
| Tagged error traps | 908 |
| Vedic sutras | 16 |
| Skill → problem links | 2,457 |
| Verbatim book chunks | 12,540 across 20 books |

**The extraction corpus (25 books):**

| Metric | Value |
|---|---|
| Questions extracted | 19,619 |
| Playable today | 12,014 (61.2%) |
| Carrying an answer key | 77.5% |
| Topic-resolved | 40.4% |
| Awaiting a vision/OCR pass | 4,384 |
| Templates in the current shipped bank | 823 |

Sources include Arun Sharma (CAT quant + DI), Nishit Sinha, Hall & Knight, Schaum, Tyra, Manhattan 5lb (GRE), and Tirthaji's *Vedic Mathematics*. Answer keys are recovered page-by-page from printed answer grids, with provenance recorded per question (which book, which page, which grid).

**One rule that governs all content claims:** *"answer verified" is never "solution verified."* SymPy recomputes the **answer**; it says nothing about whether the worked walkthrough teaches the right method. Two templates with arithmetically correct answers and self-contradicting derivations passed all seven audit stages. Every surface therefore carries two separate signals, and a bare `verified` flag is banned project-wide.

---

## 5. Build state as of 2026-09-04

**Critical context:** the original codebase was **lost on 2026-09-01** to a dev-laptop disk failure with no backup. Everything below was rebuilt from surviving specs, the recovered corpus, and a teardown of the shipped debug APK — in three days. Work is split across three parallel chats sharing one repository: *main backend*, *data extraction*, and *RAG content factory*.

| Area | State | What exists |
|---|---|---|
| Monorepo & databases | **Built** | Docker stack, Postgres migrations 00–90, Neo4j constraints, seed and verify scripts |
| Auth | **Built** | Register, login, rotating refresh with replay detection, QR pairing; IdP routes stubbed at 501 |
| Practice API | **Built** | Techniques, problems, session composition, content trust enforced on both serving paths |
| Sync | **Built** | Event-batch ingest with idempotency + keyed offline mutation replay |
| Vedic sutras | **Built** | 17 executable methods across core and extended sets, each emitting solution steps |
| Game server | Partial | 9 canonical events, matchmaking and duel logic with tests; **no bots, no boss/relay/tournament** |
| Decision Engine | Partial | BKT, allocator, scheduler, calibration, runtime shipped with tests; IRT / Glicko-2 / DINA / PFA not yet client-side |
| PWA | Partial | Onboarding, dashboard, learn and practice screens; KaTeX rendering; Dexie offline layer |
| Content factory | Partial | Stations 0 and 3, 7-stage auditor, taxonomy builder, closure builder, adapter, nightly/hourly run lanes; **AI judges gated on an API key** |
| Extraction pipeline | Partial | Page store for 20 books, key recovery, patch verification with a content-preservation gate, question-level export, vision task batches |
| Payments | **Not built** | Webhook shells returning 501, pending the processor decision |
| Mock exams, chatbot, ads, social, family | **Not built** | Fully specified, no code yet |

**Blocked on the owner:** an Anthropic/OpenAI API key (gates the 4,384-question vision pass, the 7th audit stage's judge panel, and ontology embedding regeneration); **content-rights confirmation**; a complete Arun Sharma DI scan (the recovered PDF is a Google Books preview rip — 343 of 466 pages are viewing-limit placeholders); RFP v7.2 itself is still unrecovered; and rotation of a key leaked over WhatsApp in March.

**Blocked on the client:** confirm mastery-driving events are excluded from the 10% sampling rule; approve shadow-mode for the heavy models; sign off the AI-opponent disclosure and no-bots-for-under-13 rule; decide the optional middle infrastructure step (~6 droplets, ~$108/mo); name the primary payment region; rule narrator audio in or out of Phase 1.

---

## 6. Invariants — do not propose anything that violates these

1. **Offline-first is the product, not a feature.** The game loop must run at zero network.
2. **No live LLM in the runtime loop, ever.** LLMs run only in the batch content factory and the opt-in online study chatbot — never in the game loop.
3. **Psychometric events are never sampled, never evicted, never blind-merged across devices.**
4. **The dual database is never collapsed.** Postgres = the Ledger, Neo4j = the GPS.
5. **Everything Phase-2 ships in Phase 1 behind a flag.** Activation is a config flip, not a redeploy.
6. **Safety gates are server-authoritative** — answer validation, entitlement, anti-cheat, content trust.
7. **Sandbox content never feeds mastery or mock exams.**
8. **"Answer verified" is never "solution verified."** Never emit a single `verified` boolean.

---

## 7. Market analysis (completed 2026-09-04, with sources)

### 7.1 Segment volumes — the headline finding

| Segment | Annual volume | Fit with our differentiator |
|---|---|---|
| **SSC CGL** | **28,15,445 applicants** (2025); ~13.5 lakh estimated to appear | ~100 questions in 60 minutes, **no calculator**, arithmetic-heavy — speed *is* the exam |
| GRE, India | ~1,15,000 (India is now the world's largest GRE market, ahead of the US) | **On-screen calculator provided** — the speed pitch is structurally weaker here |
| CAT | 2,95,000 registered, 2,58,000 appeared (2025) — **down 12% YoY** | Increasingly a logic/reading exam; quant speed is a supplement |
| GMAT, India | 13,670 in testing year 2025 (31.3% of global volume) | No calculator on quant; small, but pays in dollars |

**SSC CGL alone is roughly 10× CAT, and growing while CAT shrinks.** IBPS/banking and railways add further millions of attempts a year on the same aptitude paper shape.

### 7.2 Competitive pricing — the second finding

| Offer | Price |
|---|---|
| Testbook (entry plan) | **₹299 / year** |
| Adda247 (entry plan) | **₹399 / year** |
| Oliveboard (entry plan) | **₹499 / year** (claims 1 crore users) |
| **Exam Arena Pro as specced ($6/mo)** | **~₹6,400 / year** |
| Cracku, full CAT course | ₹15,999 / year |
| TIME / IMS / Career Launcher, full CAT programme | ₹30,000–47,000 / year |

Against *coaching*, ₹6,400 is cheap. Against *apps in the same store category* — which is where the comparison actually gets made — it is **9 to 21× the going rate.**

### 7.3 Category whitespace

The best-performing Vedic-maths apps on the Play Store sit at **5,000–10,000 downloads**. They are trick lists with no engine behind them. Search demand exists and is completely unserved by a real product — and this build is by a wide margin the most serious Vedic-maths software anyone has attempted.

### 7.4 Sources

- CAT 2025 registrations: mbauniverse.com · attendance: news.careers360.com
- SSC CGL 2025 applications: adda247.com, careerpower.in
- GMAT testing year 2025 India volume: GMAC geographic trend report via poetsandquants.com
- GRE India volume: careers360.com on ETS data
- CAT coaching fees: cracku.in · platform pricing: tryreadable.ai comparison, Oliveboard
- Vedic-maths app download tiers: Google Play listings

---

## 8. Go-to-market recommendations already made

### 8.1 The lead call

> **Go to market as the speed gym for the SSC and banking aspirant — not as a CAT app.** Use Vedic maths as the free top-of-funnel content engine, price it in rupees as a *supplement* rather than a coaching replacement, and launch density-first into a single exam cohort about ten weeks before its Tier-1. Keep CAT for credibility and GMAT for margin.

Rationale: **volume** (10:1 in favour of the segment the roadmap currently ranks last), **fit** (SSC/banking Tier-1 is literally a speed test; GRE hands you a calculator), and **competition** (CAT aspirants already spend ₹16k–47k a year and are sceptical of anything short of a full course, while SSC/banking is under-served on exactly what we're good at).

Segment roles: **SSC/banking = volume engine · CAT = credibility engine (toppers, press) · GMAT = margin engine · GRE = hybrid, but sell accuracy and traps, not raw speed · school/curiosity = reach, not a market.**

### 8.2 Positioning — sell capability, not coverage

Every competitor sells *more*: more mocks, more video hours, more syllabus. Coverage is commoditised to ₹299/year and no aspirant believes their problem is not having seen enough questions.

The honest diagnosis for a repeat aspirant — most of this market — is: **"you already know how to solve it. You are too slow, and you make the same three mistakes under a clock."** This is the only product built to prove that, because it is the only one that measures *how* you err rather than whether you were right.

- **Frame: a gym, not a school.** You don't quit coaching to use it; you use it 15 minutes a day. This removes the "you're not a full course" objection, justifies a daily-habit product, and puts us in the supplement price bracket.
- **Hero claim:** a measured speed delta — *"your average solve time on percentages went from 47 seconds to 29 in three weeks."* Provable, personal, screenshot-shaped, and no competitor can produce it.
- **Second claim:** *every problem is verified before it's served; nothing was invented mid-session* — a real trust wedge while every competitor bolts on a hallucinating AI tutor.
- **Message discipline rule:** **do not lead with "Vedic" to a GMAT or CAT audience** — it reads as folk-maths and costs credibility. Vedic is the top-of-funnel hook and the school/curiosity story; *speed and accuracy under time pressure* is the exam story. Same engine, two vocabularies, kept apart deliberately.

### 8.3 Recommended price architecture

| Market | Offer | Price |
|---|---|---|
| India — free | Topic browser, duels, daily challenge, ads | ₹0 |
| India — Pro | Decision Engine, ad-free, one exam lane | **₹149 / month** |
| India — annual | Same, prepaid | **₹999 / year** |
| India — season pass | Four months to exam day, dated | **₹599** |
| USD markets | Pro / Bundle-2 / Bundle-3, unchanged | $6 / $9.60 / $12.60 |

₹999/year is still 2–3× Testbook, which is defensible because we are not selling the same thing. 12× is not, because nobody reads a store listing carefully enough to learn why.

**Two mechanics to fix before launch:**

1. **Add a dated season pass.** Aspirants buy against a date, not a subscription. A pass that expires the day after the exam converts better than a monthly plan, prices above one month, and removes churn from the model. It maps cleanly onto the existing exam-deadline table.
2. **The referral ladder's top rung is a liability.** 60 referrals granting *lifetime* ad-free Pro is trivially farmable where a single Telegram admin reaches 500 aspirants — the fraud gates verify that referred users are real, not that the referrer is a channel operator. Time-box it to 12 months, or cap lifetime grants at a fixed number and say so.

### 8.4 Growth loops (mostly already in the build)

1. **The duel link** — every duel is an invitation. Make a challenge link open a *playable* round on the web with **no signup**; the static-export PWA already runs its whole practice loop client-side. **This is the single highest-leverage feature addition on this page** — it turns the most viral moment (beating a friend) from a signup wall into a game round.
2. **The daily challenge** — the Wordle mechanic. Needs a **copy-pasteable text result built for WhatsApp groups**, not a screenshot. That one format decision determines whether the loop runs.
3. **The referral ladder** — strong, already built with usage-verified anti-fraud; one bad rung (see above).
4. **Institution leaderboards** — scope a board to a coaching centre or college and the institution recruits users for you. Cheapest B2B2C motion available, needs no sales team.
5. **The sutra content engine** — 16 executable sutras that emit their own working. Point that at a renderer and you have unlimited short-form video at near-zero marginal cost.
6. **The speed-delta card** — proof and advertising in one asset, generated by the product rather than written by marketing.

### 8.5 Channels, ranked by expected cost per user

1. **Short-form Vedic content, owned** — one trick a day on YouTube Shorts / Reels / Telegram, generated from the sutra engine, each ending at the daily challenge. Near-zero marginal cost, compounding, lands in a niche whose entire current supply is 5k-download trick apps. Build this before anything paid.
2. **App store optimisation** — "vedic maths", "speed maths", "mental maths", "SSC quant", "banking aptitude" are high-intent and effectively unowned. Compounds with #1 because content drives branded search.
3. **Telegram / WhatsApp group seeding** — SSC and banking aspirants organise in groups, not on Twitter. The daily-challenge result card is the payload. Needs a real community person, not an agency.
4. **Coaching institutes and campuses** — branded leaderboards given free. One mid-size centre is hundreds of pre-motivated daily actives at ~zero acquisition cost, and the institute markets you internally.
5. **Creator partnerships, SSC/banking first** — large, hyper-targeted, comparatively cheap audiences. A creator who posts their own speed delta is worth ten reading a script.
6. **Forums for the dollar segment** — GMAT Club, r/GRE, r/GMAT. Low volume, high value, receptive to a defensible measurement claim.
7. **Paid acquisition — last.** Indian edtech paid costs are brutal and reward brands that already convert. Do not spend until organic retention and free-to-paid conversion are proven.

### 8.6 Calendar

Intent is seasonal and the seasons are published a year ahead. Confirm each against the current year's official notification before committing spend.

| Cycle | Typical shape | Peak intent | What we push |
|---|---|---|---|
| SSC CGL | Notification mid-year, Tier-1 in autumn | ~10 weeks pre-Tier-1 | Speed. **This is the launch cohort.** |
| IBPS PO / Clerk | Notification mid-year, prelims late summer–autumn | ~8 weeks pre-prelims | Speed + accuracy under a sectional clock |
| CAT | Registration August, exam late November | August–November | Quant speed as the supplement to coaching |
| GRE / GMAT | Rolling; heaviest before autumn intakes | July–October, again in January | Accuracy, traps, no-calculator quant |

**Launch density beats launch reach.** Duels, leaderboards and daily challenges are worth nothing in an empty lobby, and bot backfill only papers over the first 15 seconds. 500 beta users across 5 exams and 4 time zones produces a dead product; 500 concentrated in one exam cohort — ideally one city or one coaching institute — produces a live one.

### 8.7 Targets for the first two quarters post-launch

| Metric | Target |
|---|---|
| Install → first session finished | >70% |
| Day-1 retention | 50% |
| Day-7 retention | 25% |
| Day-30 retention | 12% |
| Daily-challenge play, share of DAU | >35% |
| K-factor from duels + referrals | >0.35 |
| Free → paid, India | 2–3% |
| Free → paid, USD markets | 5–8% |

**Day-30 retention is the real product-market-fit signal** for a gym-shaped product. **Daily-challenge participation is the health metric for the entire growth model** — under a third of DAU means the organic engine isn't running and paid spend won't substitute.

Separately: the plan assumes ad revenue covers the Phase-1 infrastructure bill of $80–120/month. At Indian rewarded-video rates that's a low bar and probably true — but the ad rules deliberately exclude every high-attention moment in the app, so inventory is smaller than a normal ad-supported product. Verify with real numbers before it becomes a line in a business case.

### 8.8 Risks marketing must raise

1. **Content rights are a launch blocker, not a backlog item.** The corpus is extracted from 25 copyrighted books. The project's own open items still list content ownership as unconfirmed. A consumer launch, paid acquisition and press all raise that exposure simultaneously. A post-launch takedown is a brand problem, not merely a legal one. **Resolve before the first rupee of acquisition spend.**
2. **Undisclosed AI opponents are a reputation event waiting to happen.** Bot backfill is the right product call, but *"this app made me duel a bot and didn't tell me"* is exactly the post that spreads. Make disclosure a **feature** — "practice partners, so you're never waiting" — not a line in the terms.
3. **Decide deliberately whether children are a segment.** Vedic content pulls parents and school kids; marketing to under-13s inherits consent flows, ad bans, session caps and app-store scrutiny across the whole product. Fine if kids are a real revenue line through family plans; poor if they're an accidental audience the funnel picked up.
4. **Nothing is live yet.** Payments, mock exams, social and the chatbot are specified but unbuilt; the game server has no bots. Set the marketing calendar from the build's real dates, not the spec's.
5. **"Vedic" cuts both ways** — cheapest reach in the plan, credibility cost with the most sophisticated segment. The two-vocabulary rule in §8.2 is how you keep the upside without paying the downside.

---

## 9. Reference artifacts

Two published pages hold the same material in a designed, browsable form (owner-private):

- **Exam Arena Build Dossier** — product and feature reference: https://claude.ai/code/artifact/227b5422-9a6d-4952-a57a-95619fc474cd
- **The Speed Gym Wedge** — the GTM analysis with market and pricing charts: https://claude.ai/code/artifact/73923840-6425-4d01-9e47-9c255a906540

Repository: `https://github.com/AniketThakur022/Speed-Gym` · local working directory `/Users/harshahirrao/Speed gym`.

---

## 10. Where the discussion stands — pick up here

**Settled in this discussion so far:** the lead segment call (SSC/banking first, CAT for credibility, GMAT for margin); the positioning (capability over coverage, gym not school, speed delta as hero claim); the India price architecture and the season-pass recommendation; the channel ranking; the launch-density principle; the risk list.

**Open — these need the owner's decision, not more analysis:**

1. Does the owner accept re-ordering the launch segments away from the RFP's CAT-first framing? This is a *marketing* recommendation against a *contractual* document — the client signed off on an RFP that orders it differently, so it may need to be raised with the client rather than simply adopted.
2. Is the India price ladder (₹149 / ₹999 / ₹599 season pass) acceptable, given the RFP settled tiers at $6 / $9.60 / $12.60? Changing published tiers may itself be a client decision.
3. Content rights — the blocker above everything else.
4. Are under-13s a marketing segment or only a family-plan feature?
5. What is the actual target launch date, given payments, mocks, social and the chatbot are unbuilt?

**Natural next pieces of work, none of them started:**

- A launch campaign plan for the chosen cohort — creative concepts, channel-by-channel briefs, week-by-week calendar.
- Messaging architecture and copy: store listing, ASO keyword set, landing page, onboarding copy.
- A budget and CAC/LTV model with the ad-revenue assumption tested against real eCPMs.
- A client-facing deck arguing the segment re-ordering and the price change.
- Creative specs for the sutra content engine — what a daily Short actually looks like and how it's generated.
- Naming and packaging for the season pass and the exam lanes.

**Suggested opening for the new chat:** *"Read the attached handoff brief. We're continuing the go-to-market work on Exam Arena — pick up at section 10."*
