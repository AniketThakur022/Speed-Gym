# Vedic Math Speed Gym — Project Brief for Discussion

**For:** Client / Project Owner
**Prepared by:** Engineering
**Date:** 2026-07-04
**Purpose:** A plain-language summary of how we plan to build the app, the decisions we need from you, and the step-by-step plan. This is the conversation starter — the full technical detail lives in a separate document.

---

## 1. What we're building, in one paragraph

An offline-first mobile and web app that trains people in Vedic mathematics and exam prep (CAT/GMAT/GRE). It watches *how* each learner makes mistakes and drills those exact weaknesses, wraps the practice in competitive games, and works even with no internet (subway, flight mode). Free users get manual topic practice with ads; paid users get the smart "Decision Engine" that plans every session for them. We deliver everything in **Phase 1** on cheap infrastructure, then **flip on** the heavy social and analytics features in **Phase 2** once you have enough users to justify the cost.

---

## 2. The good news: your requirements document is solid

Your RFP (v7.2, 365 specifications) is comprehensive and well-organized. It settled several questions that older planning docs had left contradictory — the pricing tiers, which backend technology we use, the core learning-model settings, and the final infrastructure cost. **We can build against it as-is.** The rest of this document is about the handful of decisions worth aligning on before we start, so we don't have to rework things later.

---

## 3. The 5 things most worth discussing

These are the decisions where your input changes what we build. Everything else has a sensible default and we'll just proceed.

### 3.1 Timeline vs. scope — the most important conversation
The plan is **15 weeks** to build *everything* in Phase 1: accounts, payments, the full learning engine, content automation, solo **and** multiplayer games, mock exams, and **both** Android and iOS apps. That is a lot for 15 weeks.

**Our recommendation:** keep the 15-week calendar, but (a) use content that's already prepared rather than re-processing it from scratch mid-project, and (b) ship the most advanced learning models as "built but dormant," switching them on in Phase 2. This keeps the date realistic without cutting features you can see. *We'd like your agreement on this approach.*

### 3.2 "Smart but silent" learning models
Some of the advanced scoring models (the ones for reading and logical-reasoning sections) only become *accurate* after thousands of users have generated data to calibrate them. Turning them on for your first few hundred users would give people **misleading results**.

**Our recommendation:** build them now (as your RFP asks), run them quietly in the background collecting data, and switch them to "live" in Phase 2 once they're trustworthy. The learner never sees a wrong recommendation. *We need your OK on this.*

### 3.3 A protection for the learning data
Your RFP has a scale optimization that would only keep a **sample** of practice attempts at high traffic. The problem: practice attempts are exactly the data the learning engine needs to track mastery — sampling them makes every learner's progress score inaccurate.

**Our recommendation:** apply the sampling only to non-essential data (page views, help clicks), and always keep **100%** of the data that drives learning. Same cost savings, no accuracy damage. *This is a small change from the literal wording of the RFP, so we want to confirm it with you.*

### 3.4 Competitive bots + kids' accounts
To make sure early users never sit in an empty game lobby, the app fills in **AI opponents**. Your RFP also has a **kids' mode** with child-safety (COPPA) rules. Undisclosed AI opponents in an app used by children is a legal and app-store risk.

**Our recommendation:** keep the AI opponents for adults (they solve the empty-lobby problem), but **never** show them to children's accounts, and add a light "may include AI-paced opponents" note in the terms. *We'd like sign-off on this.*

### 3.5 The infrastructure jump
Phase 1 runs on **2 small servers** (~$80–120/month). Phase 2 jumps to **22 servers** (~$836/month) the moment you hit 5,000 daily users. That's a big, all-at-once leap.

**Our recommendation:** keep an optional **middle step** (~6 servers, ~$108/month) ready, so if growth is steady but not yet at 5,000, we can scale up smoothly instead of in one risky jump. *Optional — your call on budget.*

---

## 4. A few things to be aware of (we'll handle these)

- **Content needs a pre-flight check.** Some of the existing question data has gaps (a batch of questions with missing text, and some incomplete topic-linking). We'll clear these in the first two weeks before the learning engine goes live on top of them. Worth confirming who owns the content so this isn't a surprise.
- **Payments in two systems.** We support Stripe and Razorpay (for India). Quick decision needed: which is the *primary* region, as it affects default currency and setup.
- **Narrator voice-over** is mentioned once with no detail — tell us if it's in or out of Phase 1.

---

## 5. How the app is put together (simple version)

Think of it in five layers:

| Layer | What it does | Plain-language role |
|---|---|---|
| **The app** (phone + web) | Runs the practice, games, and scoring **on the device** | Works offline; the phone does the thinking so it's instant |
| **The brain** (Decision Engine) | Decides what to practice next and how hard | The personal coach |
| **The game server** | Runs the live multiplayer matches | The referee for competitions |
| **Two databases** | One stores facts & history; one stores the "map" of how topics connect | The ledger and the GPS |
| **The content factory** | Generates and verifies new practice problems overnight | The kitchen — never touches the live game, everything is checked before serving |

Two principles worth knowing:
- **Nothing that answers a math problem needs the internet** — the app is fast even with no signal.
- **AI never invents a problem on the fly during play** — every problem is verified before it can appear, so learners never see a wrong answer.

---

## 6. How we build it — step by step

### Phase 1 — Build everything (15 weeks)

| Weeks | What we build | You can see / test |
|---|---|---|
| **1–2** | Foundation: project setup, developer pipeline, content pre-flight check | Environment ready |
| **3–4** | Accounts & money: sign-up, QR login, subscriptions, family plans, payments | Log in, subscribe, add a child seat |
| **5–6** | The learning engine: mastery tracking, the 16 Vedic techniques, calibration | Practice adapts to you |
| **7–8** | Head-to-head duels: matchmaking, live scoring, rematches | Play a live 1v1 match |
| **9–10** | Content & the study chatbot: lessons, hints-only tutor, admin panel | Ask the tutor, browse lessons |
| **11–12** | Social & rewards: streaks, referrals, achievements, leaderboards, basic team play | Refer a friend, earn badges |
| **13** | Polish: bug-fixing, security review, accessibility, cross-device testing | Release-candidate build |
| **14–15** | App-store submission + closed beta + launch readiness | Live in beta with 100+ testers |

*The advanced team games (Boss Battles, Relay, Tournaments, location features) are fully built in this phase but kept switched off until Phase 2.*

### Phase 2 — Switch on scale (6 weeks, triggered at 5,000 daily users)

| Week | Activity |
|---|---|
| 16 | Provision the larger infrastructure |
| 17 | Move the data over with zero downtime |
| 18 | Move the services over (no user-facing interruption) |
| 19 | Heavy load-testing (10,000 requests/second) |
| 20 | **Switch on** Boss Battles, Tournaments, advanced analytics & the smart models |
| 21 | Monitoring, dashboards, handover, team training |

### Quality checkpoints (the "go / no-go" gates)
Before launch, the build must pass 8 gates: code quality, security scan, speed under load, works on all target devices, accessibility, all connections tested, a stable beta with real users, and the 5,000-user trigger for Phase 2. Nothing ships until these are green.

---

## 7. What it costs to run

| Stage | Users | Monthly server cost |
|---|---|---|
| Phase 1 launch | 0 – 5,000 | $80 – $120 |
| *(Optional middle step)* | steady growth | ~$108 |
| Phase 2 full scale | 5,000+ | $836 |

Ad revenue from free users is expected to cover the Phase-1 running cost on its own.

---

## 8. What we need from you to start

1. **Approve the plan** for keeping the 15-week date realistic (Section 3.1).
2. **Approve "build now, switch on later"** for the advanced models (Section 3.2).
3. **Confirm the data-protection change** for the learning engine (Section 3.3).
4. **Sign off on the AI-opponent + kids'-mode rules** (Section 3.4).
5. **Decide** on the optional middle infrastructure step (Section 3.5).
6. **Confirm** content ownership, primary payment region, and whether narrator audio is in Phase 1 (Section 4).

Once we're aligned on these six, we can start Sprint 0 immediately.

---

*A detailed technical version of this architecture is available on request. This brief is intentionally high-level for discussion.*
