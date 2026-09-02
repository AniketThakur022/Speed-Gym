// ============================================================================
// VMSG Neo4j migration 02 — growth/revenue extensions (v2.0, DDL ONLY)
// Source: schemas/neo4j/updated_neo4j_schema.cypher.
// FIX #7 baked in: the delivered file mixed DDL with reference queries
// (PROFILE runs, parameterized GDPR deletes, analytics) — those now live in
// db/neo4j/reference_queries.cypher and are NEVER applied as a migration.
// ============================================================================

// User Journey — tracks funnel progression
CREATE CONSTRAINT userjourney_user_stage IF NOT EXISTS
FOR (uj:UserJourney) REQUIRE (uj.user_id, uj.stage) IS UNIQUE;

// Cohort — groups users by acquisition week
CREATE CONSTRAINT cohort_id IF NOT EXISTS
FOR (c:Cohort) REQUIRE c.cohort_week IS UNIQUE;

// Revenue Event — every monetization event
CREATE CONSTRAINT revenueevent_id IF NOT EXISTS
FOR (re:RevenueEvent) REQUIRE re.event_id IS UNIQUE;

// Marketing Touchpoint — every ad/email/exposure
CREATE CONSTRAINT marketingtouchpoint_id IF NOT EXISTS
FOR (mt:MarketingTouchpoint) REQUIRE mt.touchpoint_id IS UNIQUE;

// Family Account — links parent to children
CREATE CONSTRAINT familyaccount_id IF NOT EXISTS
FOR (fa:FamilyAccount) REQUIRE fa.family_id IS UNIQUE;

// Referral — tracks referral codes
CREATE CONSTRAINT referral_code IF NOT EXISTS
FOR (r:Referral) REQUIRE r.code IS UNIQUE;

// Achievement Badge — gamification
CREATE CONSTRAINT achievement_id IF NOT EXISTS
FOR (a:Achievement) REQUIRE a.achievement_id IS UNIQUE;

// User nodes (runtime writes MERGE on user_id)
CREATE CONSTRAINT user_id IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

// Performance indexes for new labels
CREATE INDEX userjourney_user_id_idx IF NOT EXISTS FOR (uj:UserJourney) ON (uj.user_id);
CREATE INDEX userjourney_stage_idx IF NOT EXISTS FOR (uj:UserJourney) ON (uj.stage);
CREATE INDEX revenueevent_type_idx IF NOT EXISTS FOR (re:RevenueEvent) ON (re.type);
CREATE INDEX revenueevent_timestamp_idx IF NOT EXISTS FOR (re:RevenueEvent) ON (re.timestamp);
CREATE INDEX marketingtouchpoint_campaign_idx IF NOT EXISTS FOR (mt:MarketingTouchpoint) ON (mt.campaign_id);
CREATE INDEX referral_code_idx IF NOT EXISTS FOR (r:Referral) ON (r.code);
CREATE INDEX achievement_user_idx IF NOT EXISTS FOR (a:Achievement) ON (a.user_id);
