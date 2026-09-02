// ============================================================================
// VMSG Neo4j REFERENCE QUERIES — NEVER APPLIED AS A MIGRATION (FIX #7)
// Extracted from schemas/neo4j/updated_neo4j_schema.cypher (v2.0): relationship
// vocabulary sketches, funnel definitions, cohort/revenue/growth analytics,
// ops PROFILE runs, and the parameterized GDPR cascade delete.
// ============================================================================

-- ══════════════════════════════════════════════════════════════
-- SECTION B: NEW RELATIONSHIP TYPES
-- ══════════════════════════════════════════════════════════════

// User Journey Traversal
(:User)-[:ENTERED funnel_stage: string, timestamp: datetime]->(:UserJourney)
(:User)-[:PROGRESSED_TO {from_stage, to_stage, timestamp}]->(:UserJourney)
(:User)-[:REACHED]->(:UserJourney {stage: "paid_subscriber"})

// Cohort Assignment
(:User)-[:BELONGS_TO]->(:Cohort {cohort_week, acquisition_channel})
(:Cohort)-[:HAS_MEMBER]->(:User)

// Revenue Relationships
(:User)-[:GENERATED_REVENUE {amount_cents, currency, source, timestamp}]->(:RevenueEvent)
(:RevenueEvent)-[:ATTRIBUTED_TO {attribution_weight, model: "time_decay"}]->(:MarketingTouchpoint)
(:User)-[:WAS_EXPOSED_TO {campaign_id, email_sent_at, email_opened_at, email_clicked_at}]->(:MarketingTouchpoint)

// Subscription Lifecycle
(:User)-[:SUBSCRIBED_TO {tier, started_at, trial_ends_at}]->(:RevenueEvent {type: "subscription_created"})
(:User)-[:CANCELLED {reason, cancelled_at}]->(:RevenueEvent {type: "subscription_cancelled"})
(:User)-[:UPGRADED_TO {from_tier, to_tier, upgraded_at}]->(:RevenueEvent {type: "subscription_upgraded"})

// Family Structures
(:User {role: "parent"})-[:MANAGES]->(:FamilyAccount)
(:FamilyAccount)-[:INCLUDES {child_user_id, added_at}]->(:User {role: "child"})
(:User {role: "child"})-[:HAS_PARENT]->(:User {role: "parent"})

// Referral Network
(:User)-[:GENERATED_REFERRAL_CODE {code, created_at}]->(:Referral)
(:Referral)-[:WAS_USED_BY {used_at}]->(:User)
(:User)-[:REFERRED_BY]->(:Referral)
(:User)-[:RECEIVED_REWARD {reward_type, claimed_at}]->(:Referral)

// Achievement System
(:User)-[:EARNED {earned_at, evidence: "session_count_100"}]->(:Achievement)
(:Achievement)-[:UNLOCKS {reward_type}]->(:UserJourney)  // e.g., unlocks next technique

// Ad Exposure
(:User)-[:SAW_AD {placement, screen, duration_seconds, timestamp}]->(:MarketingTouchpoint)
(:User)-[:CLICKED_AD {revenue_cents, timestamp}]->(:MarketingTouchpoint)

-- ══════════════════════════════════════════════════════════════
-- SECTION C: USER JOURNEY FUNNEL DEFINITION
-- ══════════════════════════════════════════════════════════════

// Funnel stages with typical conversion rates
(:UserJourney {stage: "anonymous_landing", description: "User landed on app but not onboarded"})
(:UserJourney {stage: "onboarding_started", description: "Clicked "Get Started""})
(:UserJourney {stage: "onboarding_completed", description: "Finished 6-question calibration"})
(:UserJourney {stage: "first_session", description: "Completed at least 1 problem"})
(:UserJourney {stage: "streak_3_days", description: "3 consecutive days of practice"})
(:UserJourney {stage: "streak_7_days", description: "7 consecutive days (viral milestone)"})
(:UserJourney {stage: "first_purchase", description: "Upgraded to Pro or Master"})
(:UserJourney {stage: "paid_subscriber", description: "Active paid subscription"})
(:UserJourney {stage: "referral_sent", description: "Sent at least 1 referral"})
(:UserJourney {stage: "advocate", description: "3+ referrals converted"})

-- ══════════════════════════════════════════════════════════════
-- SECTION D: COHORT ANALYSIS QUERIES
-- ══════════════════════════════════════════════════════════════

// Week-over-week retention by cohort
// (Run weekly for dashboard)
MATCH (c:Cohort)
WITH c, c.cohort_week AS week
MATCH (c)-[:HAS_MEMBER]->(u:User)
WHERE u.first_session_at IS NOT NULL
WITH week, u, 
  CASE 
    WHEN u.sessions_count >= 1 THEN 1 ELSE 0 
  END AS week_0,
  CASE 
    WHEN u.sessions_count >= 2 THEN 1 ELSE 0 
  END AS week_1,
  CASE 
    WHEN u.sessions_count >= 3 THEN 1 ELSE 0 
  END AS week_2
RETURN 
  week,
  COUNT(u) AS cohort_size,
  ROUND(100.0 * SUM(week_1) / COUNT(u), 1) AS retention_w1,
  ROUND(100.0 * SUM(week_2) / COUNT(u), 1) AS retention_w2
ORDER BY week DESC
LIMIT 12;

// Persona distribution by cohort
MATCH (c:Cohort)-[:HAS_MEMBER]->(u:User)
WHERE u.detected_persona IS NOT NULL
WITH c.cohort_week AS week, u.detected_persona AS persona, COUNT(u) AS count
WITH week, SUM(count) AS total, 
  {persona: persona, count: count} AS personas
RETURN week, total, personas
ORDER BY week DESC;

-- ══════════════════════════════════════════════════════════════
-- SECTION E: REVENUE ATTRIBUTION QUERIES
-- ══════════════════════════════════════════════════════════════

// How many users converted after seeing a specific email campaign?
MATCH (mt:MarketingTouchpoint {campaign_id: "retention_d7_dormant"})
MATCH (u:User)-[:WAS_EXPOSED_TO]->(mt)
OPTIONAL MATCH (u)-[:GENERATED_REVENUE]->(re:RevenueEvent {type: "subscription_created"})
WHERE re.timestamp > mt.email_sent_at
RETURN 
  COUNT(u) AS total_exposed,
  COUNT(re) AS converted,
  ROUND(100.0 * COUNT(re) / COUNT(u), 1) AS conversion_rate;

// Time-decay attribution: weighted by recency (7-day half-life)
MATCH (u:User)-[:GENERATED_REVENUE]->(re:RevenueEvent)
MATCH (u)-[:WAS_EXPOSED_TO]->(mt:MarketingTouchpoint)
WITH u, re, mt,
  duration.inSeconds(mt.timestamp, re.timestamp).seconds AS seconds_before_conversion,
  EXP(-0.000099 * duration.inSeconds(mt.timestamp, re.timestamp).seconds) AS weight
WITH u, re, mt, weight
ORDER BY weight DESC
WITH u, re, collect(mt)[0] AS last_touchpoint, sum(weight) AS total_weight
RETURN 
  re.event_id,
  re.amount_cents,
  last_touchpoint.campaign_id AS attributed_campaign,
  last_touchpoint.touchpoint_id AS attributed_touchpoint;

-- ══════════════════════════════════════════════════════════════
-- SECTION F: GROWTH LOOP QUERIES
-- ══════════════════════════════════════════════════════════════

// Viral coefficient: average referrals per user by persona
MATCH (u:User)-[:GENERATED_REFERRAL_CODE]->(r:Referral)
OPTIONAL MATCH (r)-[:WAS_USED_BY]->(converted:User)
WITH u.detected_persona AS persona, COUNT(r) AS codes_sent, COUNT(converted) AS codes_used
RETURN 
  persona,
  AVG(codes_sent) AS avg_referrals_sent,
  AVG(codes_used) AS avg_referrals_converted,
  ROUND(100.0 * SUM(codes_used) / SUM(codes_sent), 1) AS conversion_rate
ORDER BY avg_referrals_converted DESC;

// Which techniques drive the most paid conversions?
MATCH (u:User)-[:COMPLETED]->(p:Problem)
WHERE p.technique IS NOT NULL
WITH u, p.technique AS technique, COUNT(p) AS problems
WITH u, technique, problems
ORDER BY problems DESC
WITH u, collect(technique)[0] AS top_technique
MATCH (u)-[:GENERATED_REVENUE]->(re:RevenueEvent {type: "subscription_created"})
RETURN 
  top_technique,
  COUNT(u) AS converters,
  AVG(re.amount_cents) / 100.0 AS avg_revenue
ORDER BY converters DESC;

-- ══════════════════════════════════════════════════════════════
-- SECTION G: OPS & MONITORING QUERIES
-- ══════════════════════════════════════════════════════════════

// Slowest graph traversals (for performance tuning)
PROFILE
MATCH (u:User)-[:COMPLETED]->(p:Problem)-[:REQUIRES_TECHNIQUE]->(t:Technique)
WHERE u.id = "anon_abc123"
RETURN p.id, t.name
LIMIT 100;

// Most active users in last 24 hours (for real-time ops)
MATCH (u:User)-[:COMPLETED]->(p:Problem)
WHERE p.timestamp >= datetime() - duration({hours: 24})
WITH u, COUNT(p) AS problems_today
WHERE problems_today > 20
RETURN u.id, problems_today
ORDER BY problems_today DESC
LIMIT 100;

-- ══════════════════════════════════════════════════════════════
-- SECTION H: GDPR & DATA DELETION
-- ══════════════════════════════════════════════════════════════

// Cascade delete user and all related nodes
MATCH (u:User {id: $user_id})
OPTIONAL MATCH (u)-[r1]-(uj:UserJourney)
OPTIONAL MATCH (u)-[r2]-(re:RevenueEvent)
OPTIONAL MATCH (u)-[r3]-(mt:MarketingTouchpoint)
OPTIONAL MATCH (u)-[r4]-(ref:Referral)
OPTIONAL MATCH (u)-[r5]-(a:Achievement)
DELETE r1, r2, r3, r4, r5, uj, re, mt, ref, a, u;

