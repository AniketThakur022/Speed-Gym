"""Pricing, INR conversion, the family seat curve, and the pure provider
helpers (signatures + webhook normalisation). No databases, no network."""

import hashlib
import hmac
import json
import time

import pytest

from app.billing import pricing
from app.billing.providers import (
    parse_razorpay_event,
    parse_stripe_event,
    verify_razorpay_checkout,
    verify_razorpay_webhook,
    verify_stripe_webhook,
)
from app.billing.state import effective_tier


# ── prices ───────────────────────────────────────────────────────────────────


def test_rfp_usd_prices_are_the_source_of_truth():
    assert pricing.TIER_USD_CENTS == {"free": 0, "pro": 600, "bundle_2": 960, "bundle_3": 1260}


@pytest.mark.parametrize(
    "tier,rate,expected_paise",
    [("pro", 84.0, 50_400), ("bundle_2", 84.0, 80_640), ("bundle_3", 84.0, 105_840)],
)
def test_inr_is_derived_from_the_configured_rate(tier, rate, expected_paise):
    assert pricing.usd_cents_to_minor(pricing.TIER_USD_CENTS[tier], "INR", rate) == expected_paise


def test_inr_rounding_is_half_up_not_bankers():
    # 600 × 83.3375 = 50002.5 → 50003 (half-up); Python's round() would give 50002.
    assert pricing.usd_cents_to_minor(600, "INR", 83.3375) == 50_003


def test_usd_passes_through_untouched():
    assert pricing.usd_cents_to_minor(960, "USD", 84.0) == 960


def test_unknown_currency_and_bad_rate_are_rejected():
    with pytest.raises(pricing.PricingError):
        pricing.usd_cents_to_minor(600, "EUR", 84.0)
    with pytest.raises(pricing.PricingError):
        pricing.usd_cents_to_minor(600, "INR", 0)


# ── family curve ─────────────────────────────────────────────────────────────


def test_seat_curve_is_100_80_60_and_nothing_else():
    assert [pricing.seat_discount_pct(n) for n in (1, 2, 3)] == [100, 80, 60]
    with pytest.raises(pricing.PricingError):
        pricing.seat_discount_pct(4)


@pytest.mark.parametrize("seats,pct", [(0, 100), (1, 200), (2, 280), (3, 340)])
def test_family_multiplier(seats, pct):
    assert pricing.family_multiplier_pct(seats) == pct


def test_quote_breakdown_adds_up_and_matches_the_curve():
    q = pricing.quote("pro", 3, "INR", 84.0)
    assert q.unit_minor == 50_400
    assert q.seat_minor == (50_400, 40_320, 30_240)
    assert q.total_minor == 50_400 + 50_400 + 40_320 + 30_240 == 171_360
    assert q.total_minor == q.unit_minor * pricing.family_multiplier_pct(3) // 100


def test_quote_rejects_free_tier_and_too_many_seats():
    with pytest.raises(pricing.PricingError):
        pricing.quote("free", 0, "INR", 84.0)
    with pytest.raises(pricing.PricingError):
        pricing.quote("pro", 4, "INR", 84.0)


def test_catalog_lists_every_tier_with_both_currencies():
    cat = pricing.plan_catalog(84.0, 7)
    assert [p["tier"] for p in cat] == ["free", "pro", "bundle_2", "bundle_3"]
    pro = next(p for p in cat if p["tier"] == "pro")
    assert pro["usd_cents"] == 600 and pro["inr_paise"] == 50_400 and pro["trial_days"] == 7
    assert next(p for p in cat if p["tier"] == "free")["trial_days"] == 0


# ── tier grant rule ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("status,expect", [
    ("active", "pro"), ("trialing", "pro"), ("past_due", "pro"),
    ("unpaid", "free"), ("cancelled", "free"), (None, "free"),
])
def test_past_due_keeps_the_tier_during_grace_unpaid_drops_it(status, expect):
    assert effective_tier("pro", status) == expect


# ── razorpay signatures ──────────────────────────────────────────────────────


def _hex(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def test_razorpay_webhook_signature_is_over_the_raw_body():
    body = b'{"event":"subscription.activated"}'
    assert verify_razorpay_webhook(body, _hex("whs", body), "whs")
    assert not verify_razorpay_webhook(body + b" ", _hex("whs", body), "whs")
    assert not verify_razorpay_webhook(body, _hex("other", body), "whs")


def test_razorpay_rejects_when_secret_or_signature_is_empty():
    body = b"{}"
    assert not verify_razorpay_webhook(body, _hex("whs", body), "")
    assert not verify_razorpay_webhook(body, "", "whs")


def test_razorpay_checkout_signature_is_payment_pipe_subscription():
    sig = _hex("keysecret", b"pay_1|sub_1")
    assert verify_razorpay_checkout("pay_1", "sub_1", sig, "keysecret")
    assert not verify_razorpay_checkout("pay_1", "sub_2", sig, "keysecret")
    assert not verify_razorpay_checkout("pay_1", "sub_1", sig, "")


def test_razorpay_event_normalises_status_and_notes():
    payload = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {"entity": {
                "id": "sub_1", "status": "active", "customer_id": "cust_1",
                "current_start": 1_700_000_000, "current_end": 1_702_592_000,
                "notes": {"user_id": "u-1", "intent_id": "i-1"},
            }},
            "payment": {"entity": {"amount": 50400, "currency": "INR"}},
        },
    }
    ev = parse_razorpay_event(payload, "evt_1")
    assert ev.relevant and ev.status == "active"
    assert ev.subscription_ref == "sub_1" and ev.user_id == "u-1" and ev.intent_id == "i-1"
    assert ev.amount_minor == 50400 and ev.currency == "INR"
    assert ev.period_end.year == 2023


def test_razorpay_authenticated_is_a_trial_until_start_at():
    payload = {"event": "subscription.authenticated", "payload": {"subscription": {"entity": {
        "id": "sub_2", "status": "authenticated", "start_at": 1_800_000_000, "notes": {}}}}}
    ev = parse_razorpay_event(payload, "evt_2")
    assert ev.status == "trialing"
    assert ev.trial_end is not None and ev.period_end == ev.trial_end


def test_razorpay_halted_maps_to_unpaid_and_payment_events_are_irrelevant():
    halted = {"event": "subscription.halted", "payload": {"subscription": {"entity": {"id": "s", "status": "halted"}}}}
    assert parse_razorpay_event(halted, "e").status == "unpaid"
    assert parse_razorpay_event({"event": "payment.captured", "payload": {}}, "e").relevant is False


# ── stripe signatures ────────────────────────────────────────────────────────


def _stripe_header(secret: str, body: bytes, ts: int) -> str:
    return f"t={ts},v1={_hex(secret, f'{ts}.'.encode() + body)}"


def test_stripe_signature_verifies_timestamp_dot_body():
    body = b'{"id":"evt_1","type":"invoice.paid"}'
    ts = int(time.time())
    assert verify_stripe_webhook(body, _stripe_header("whsec", body, ts), "whsec")
    assert not verify_stripe_webhook(body, _stripe_header("wrong", body, ts), "whsec")
    assert not verify_stripe_webhook(body + b"x", _stripe_header("whsec", body, ts), "whsec")


def test_stripe_rejects_stale_timestamps_replay_window():
    body = b"{}"
    old = int(time.time()) - 600
    assert not verify_stripe_webhook(body, _stripe_header("whsec", body, old), "whsec")
    assert verify_stripe_webhook(body, _stripe_header("whsec", body, old), "whsec", now=old + 10)


def test_stripe_accepts_any_matching_v1_when_secret_rotates():
    body = b"{}"
    ts = int(time.time())
    good = _hex("new", f"{ts}.".encode() + body)
    header = f"t={ts},v1={_hex('old', b'x')},v1={good}"
    assert verify_stripe_webhook(body, header, "new")


def test_stripe_subscription_event_normalises():
    payload = {"id": "evt_9", "type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_9", "customer": "cus_9", "status": "past_due",
        "current_period_start": 1_700_000_000, "current_period_end": 1_702_592_000,
        "cancel_at_period_end": True, "metadata": {"user_id": "u-9", "intent_id": "i-9"},
    }}}
    ev = parse_stripe_event(payload)
    assert ev.status == "past_due" and ev.cancel_at_period_end is True
    assert ev.user_id == "u-9" and ev.subscription_ref == "sub_9"


def test_stripe_checkout_completed_links_but_carries_no_status():
    payload = {"id": "evt_c", "type": "checkout.session.completed", "data": {"object": {
        "subscription": "sub_c", "customer": "cus_c", "client_reference_id": "u-c",
        "metadata": {"intent_id": "i-c"}, "amount_total": 600, "currency": "usd"}}}
    ev = parse_stripe_event(payload)
    assert ev.relevant and ev.status is None
    assert ev.subscription_ref == "sub_c" and ev.intent_id == "i-c" and ev.currency == "USD"


def test_stripe_unrelated_events_are_irrelevant():
    assert parse_stripe_event({"id": "e", "type": "charge.refunded", "data": {"object": {}}}).relevant is False
