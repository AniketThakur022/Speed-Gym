"""Billing — subscriptions, family seats, provider adapters, entitlement.

Razorpay primary, Stripe secondary (owner, 2026-09-04). The provider adapters
are thin and injectable; every business rule (pricing, seat curve, status
normalisation, tier grants, family sync) lives in provider-neutral code so the
two processors cannot drift.
"""
