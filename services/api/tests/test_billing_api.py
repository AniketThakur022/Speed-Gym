"""Billing + family + webhooks through the real API against the dev Postgres.

Providers are FAKED at the adapter seam (no network); signature verification
stays REAL — the fake never bypasses it. Test secrets below are fixtures, not
credentials.
"""

import hashlib
import hmac
import json
import socket
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.billing.providers import CheckoutPayload, PaymentProvider, set_provider_override
from app.main import create_app


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable("localhost", 5432), reason="dev Postgres not running")

RZP_KEY_SECRET = "test-key-secret"
RZP_WEBHOOK_SECRET = "test-webhook-secret"
STRIPE_WEBHOOK_SECRET = "whsec_test"


class FakeProvider(PaymentProvider):
    """Records calls, returns provider-shaped references."""

    def __init__(self, name: str, configured: bool = True):
        self.name = name
        self._configured = configured
        self.calls: list[tuple] = []
        self.counter = 0

    def configured(self) -> bool:
        return self._configured

    async def create_checkout(self, *, user, quote, intent_id, trial_days):
        self.counter += 1
        self.calls.append(("checkout", quote.tier, quote.seats_count, quote.total_minor, trial_days))
        ref = f"{'sub' if self.name == 'razorpay' else 'cs'}_{self.counter}_{intent_id[:8]}"
        return CheckoutPayload(self.name, ref, f"plan_{self.counter}", {"ref": ref})

    async def cancel(self, ref, *, at_period_end):
        self.calls.append(("cancel", ref, at_period_end))

    async def resume(self, ref):
        self.calls.append(("resume", ref))

    async def reprice(self, ref, quote):
        self.calls.append(("reprice", ref, quote.seats_count, quote.total_minor))
        return f"plan_reprice_{quote.seats_count}"


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    p = MonkeyPatch()
    yield p
    p.undo()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    from app.config import get_settings

    monkeypatch_module.setenv("RAZORPAY_KEY_ID", "rzp_test_fixture")
    monkeypatch_module.setenv("RAZORPAY_KEY_SECRET", RZP_KEY_SECRET)
    monkeypatch_module.setenv("RAZORPAY_WEBHOOK_SECRET", RZP_WEBHOOK_SECRET)
    monkeypatch_module.setenv("STRIPE_SECRET_KEY", "sk_test_fixture")
    monkeypatch_module.setenv("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET)
    monkeypatch_module.setenv("USD_INR_RATE", "84.0")
    get_settings.cache_clear()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def fakes():
    rz, st = FakeProvider("razorpay"), FakeProvider("stripe")
    set_provider_override("razorpay", rz)
    set_provider_override("stripe", st)
    yield {"razorpay": rz, "stripe": st}
    set_provider_override("razorpay", None)
    set_provider_override("stripe", None)


def _register(client, prefix="bill"):
    creds = {"email": f"{prefix}-{uuid.uuid4().hex[:10]}@vsg.com", "password": "correct-horse-battery"}
    tokens = client.post("/api/v1/auth/register", json=creds).json()
    return {"Authorization": f"Bearer {tokens['token']}"}, tokens["user"]["id"], creds


def _me_tier(client, auth) -> str:
    return client.get("/api/v1/auth/me", headers=auth).json()["user"]["tier"]


def _hex(secret: str, msg: bytes) -> str:
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _rzp_webhook(client, event: str, sub_id: str, status: str, notes: dict, event_id=None, **entity):
    body = json.dumps({
        "event": event,
        "payload": {"subscription": {"entity": {"id": sub_id, "status": status, "notes": notes, **entity}}},
    }).encode()
    headers = {
        "X-Razorpay-Signature": _hex(RZP_WEBHOOK_SECRET, body),
        "X-Razorpay-Event-Id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "Content-Type": "application/json",
    }
    return client.post("/api/webhooks/razorpay", content=body, headers=headers)


def _stripe_webhook(client, payload: dict, secret=STRIPE_WEBHOOK_SECRET):
    body = json.dumps(payload).encode()
    ts = int(time.time())
    header = f"t={ts},v1={_hex(secret, f'{ts}.'.encode() + body)}"
    return client.post(
        "/api/webhooks/stripe", content=body,
        headers={"Stripe-Signature": header, "Content-Type": "application/json"},
    )


def _checkout(client, auth, tier="pro", seats=0, provider=None):
    body = {"tier": tier, "seats_count": seats}
    if provider:
        body["provider"] = provider
    res = client.post("/api/v1/billing/checkout", json=body, headers=auth)
    assert res.status_code == 200, res.text
    return res.json()


def _verify_rzp(client, auth, intent_id, sub_ref):
    pay = f"pay_{uuid.uuid4().hex[:8]}"
    sig = _hex(RZP_KEY_SECRET, f"{pay}|{sub_ref}".encode())
    return client.post("/api/v1/billing/checkout/verify", json={
        "intent_id": intent_id, "razorpay_payment_id": pay,
        "razorpay_subscription_id": sub_ref, "razorpay_signature": sig,
    }, headers=auth)


# ── plans ────────────────────────────────────────────────────────────────────


def test_plans_are_public_and_razorpay_inr_by_default(client, fakes):
    body = client.get("/api/v1/billing/plans").json()
    assert body["default_provider"] == "razorpay" and body["default_currency"] == "INR"
    assert set(body["providers_available"]) == {"razorpay", "stripe"}
    pro = next(p for p in body["plans"] if p["tier"] == "pro")
    assert pro["usd_cents"] == 600 and pro["inr_paise"] == 50_400
    assert body["family"]["seat_discount_pct"] == {"1": 100, "2": 80, "3": 60}


# ── razorpay checkout → verify → tier ────────────────────────────────────────


def test_razorpay_checkout_quotes_inr_and_creates_a_pending_intent(client, fakes):
    auth, _, _ = _register(client)
    out = _checkout(client, auth)
    assert out["provider"] == "razorpay"
    assert out["quote"]["currency"] == "INR" and out["quote"]["total_minor"] == 50_400
    assert out["trial_days"] == 7
    assert fakes["razorpay"].calls[0] == ("checkout", "pro", 0, 50_400, 7)
    assert _me_tier(client, auth) == "free"  # nothing granted until verified


def test_verify_with_valid_signature_grants_tier_and_resigns_entitlement(client, fakes):
    auth, user_id, _ = _register(client)
    out = _checkout(client, auth)
    res = _verify_rzp(client, auth, out["intent_id"], out["checkout"]["ref"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tier"] == "pro" and body["subscription"]["status"] == "trialing"
    assert body["entitlement"]["tier"] == "pro" and body["entitlement"]["grace_days"] == 3
    assert _me_tier(client, auth) == "pro"
    # entitlement is also what sync hands back (PAY-04)
    sync = client.post("/api/v1/sync", json={"events": []}, headers=auth).json()
    assert sync["entitlement"]["tier"] == "pro"


def test_verify_with_forged_signature_grants_nothing(client, fakes):
    auth, _, _ = _register(client)
    out = _checkout(client, auth)
    res = client.post("/api/v1/billing/checkout/verify", json={
        "intent_id": out["intent_id"], "razorpay_payment_id": "pay_x",
        "razorpay_subscription_id": out["checkout"]["ref"], "razorpay_signature": "0" * 64,
    }, headers=auth)
    assert res.status_code == 400
    assert _me_tier(client, auth) == "free"


def test_verify_cannot_claim_another_users_intent(client, fakes):
    auth_a, _, _ = _register(client)
    auth_b, _, _ = _register(client)
    out = _checkout(client, auth_a)
    res = _verify_rzp(client, auth_b, out["intent_id"], out["checkout"]["ref"])
    assert res.status_code == 404
    assert _me_tier(client, auth_b) == "free"


def test_second_checkout_while_live_is_refused(client, fakes):
    auth, _, _ = _register(client)
    out = _checkout(client, auth)
    _verify_rzp(client, auth, out["intent_id"], out["checkout"]["ref"])
    res = client.post("/api/v1/billing/checkout", json={"tier": "bundle_2"}, headers=auth)
    assert res.status_code == 409


def test_unconfigured_provider_answers_503_not_501(client, fakes):
    set_provider_override("stripe", FakeProvider("stripe", configured=False))
    auth, _, _ = _register(client)
    res = client.post("/api/v1/billing/checkout", json={"tier": "pro", "provider": "stripe"}, headers=auth)
    assert res.status_code == 503


# ── webhooks: razorpay ───────────────────────────────────────────────────────


def test_razorpay_webhook_rejects_bad_signature_and_missing_secret(client, fakes, monkeypatch):
    body = b'{"event":"subscription.activated"}'
    res = client.post("/api/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": "nope"})
    assert res.status_code == 400

    from app.config import get_settings
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    try:
        res = client.post("/api/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": _hex("x", body)})
        assert res.status_code == 503
    finally:
        monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", RZP_WEBHOOK_SECRET)
        get_settings.cache_clear()


def test_razorpay_webhook_activates_via_notes_and_is_idempotent(client, fakes):
    auth, user_id, _ = _register(client)
    out = _checkout(client, auth, tier="bundle_2")
    sub_ref = out["checkout"]["ref"]
    notes = {"user_id": user_id, "intent_id": out["intent_id"]}

    # Unique per run: the idempotency ledger persists in the dev DB across runs.
    event_id = f"evt_same_{uuid.uuid4().hex[:8]}"
    res = _rzp_webhook(client, "subscription.activated", sub_ref, "active", notes, event_id=event_id,
                       current_start=int(time.time()), current_end=int(time.time()) + 30 * 86400)
    assert res.status_code == 200 and res.json()["handled"] is True
    assert _me_tier(client, auth) == "bundle_2"

    dup = _rzp_webhook(client, "subscription.activated", sub_ref, "active", notes, event_id=event_id)
    assert dup.json()["status"] == "duplicate"


def test_razorpay_halted_drops_tier_and_pending_keeps_it(client, fakes):
    auth, user_id, _ = _register(client)
    out = _checkout(client, auth)
    sub_ref = out["checkout"]["ref"]
    _verify_rzp(client, auth, out["intent_id"], sub_ref)
    assert _me_tier(client, auth) == "pro"

    _rzp_webhook(client, "subscription.pending", sub_ref, "pending", {})
    assert _me_tier(client, auth) == "pro"  # grace window
    sub = client.get("/api/v1/billing/subscription", headers=auth).json()["subscription"]
    assert sub["status"] == "past_due"

    _rzp_webhook(client, "subscription.halted", sub_ref, "halted", {})
    assert _me_tier(client, auth) == "free"


def test_unresolvable_webhook_is_acknowledged_not_applied(client, fakes):
    res = _rzp_webhook(client, "subscription.activated", f"sub_ghost_{uuid.uuid4().hex[:8]}", "active", {})
    assert res.status_code == 200
    assert res.json()["handled"] is False and res.json()["reason"] == "unresolved_subscription"


def test_event_naming_a_different_user_than_the_subscription_is_refused(client, fakes):
    """A provider ref is authoritative, but if the event also names a user and
    it is NOT the subscription's owner, nothing is applied to either account."""
    auth_a, user_a, _ = _register(client)
    auth_b, user_b, _ = _register(client)
    out = _checkout(client, auth_a)
    sub_ref = out["checkout"]["ref"]
    _verify_rzp(client, auth_a, out["intent_id"], sub_ref)

    res = _rzp_webhook(client, "subscription.cancelled", sub_ref, "cancelled", {"user_id": user_b})
    assert res.json()["handled"] is False and res.json()["reason"] == "user_mismatch"
    assert _me_tier(client, auth_a) == "pro"
    assert _me_tier(client, auth_b) == "free"


# ── webhooks: stripe ─────────────────────────────────────────────────────────


def test_stripe_flow_checkout_completed_then_subscription_events(client, fakes):
    auth, user_id, _ = _register(client)
    out = _checkout(client, auth, tier="pro", provider="stripe")
    assert out["quote"]["currency"] == "INR"  # default currency, even on stripe
    intent_id = out["intent_id"]
    sub_ref = f"sub_st_{uuid.uuid4().hex[:8]}"  # unique per run; refs persist in the dev DB

    res = _stripe_webhook(client, {"id": f"evt_{uuid.uuid4().hex[:8]}", "type": "checkout.session.completed",
                                   "data": {"object": {"id": out["checkout"]["ref"], "subscription": sub_ref,
                                            "customer": "cus_1", "client_reference_id": user_id,
                                            "metadata": {"intent_id": intent_id}}}})
    assert res.status_code == 200 and res.json()["handled"] is True
    assert _me_tier(client, auth) == "pro"

    res = _stripe_webhook(client, {"id": f"evt_{uuid.uuid4().hex[:8]}", "type": "customer.subscription.deleted",
                                   "data": {"object": {"id": sub_ref, "status": "canceled",
                                            "metadata": {"user_id": user_id}}}})
    assert res.json()["handled"] is True
    assert _me_tier(client, auth) == "free"


def test_stripe_bad_signature_is_400(client, fakes):
    res = _stripe_webhook(client, {"id": "evt_x", "type": "invoice.paid", "data": {"object": {}}}, secret="wrong")
    assert res.status_code == 400


# ── cancel / resume / change ─────────────────────────────────────────────────


def test_cancel_schedules_at_period_end_and_keeps_tier(client, fakes):
    auth, _, _ = _register(client)
    out = _checkout(client, auth)
    _verify_rzp(client, auth, out["intent_id"], out["checkout"]["ref"])
    res = client.post("/api/v1/billing/cancel", headers=auth)
    assert res.status_code == 200
    assert res.json()["subscription"]["cancel_at_period_end"] is True
    assert _me_tier(client, auth) == "pro"
    assert ("cancel", out["checkout"]["ref"], True) in fakes["razorpay"].calls


def test_change_tier_reprices_and_updates_tier(client, fakes):
    auth, _, _ = _register(client)
    out = _checkout(client, auth)
    _verify_rzp(client, auth, out["intent_id"], out["checkout"]["ref"])
    res = client.post("/api/v1/billing/change", json={"tier": "bundle_3"}, headers=auth)
    assert res.status_code == 200, res.text
    assert res.json()["quote"]["total_minor"] == 105_840
    assert _me_tier(client, auth) == "bundle_3"


# ── family ───────────────────────────────────────────────────────────────────


def _paid_parent(client, fakes, tier="pro"):
    auth, user_id, _ = _register(client, "parent")
    out = _checkout(client, auth, tier=tier)
    _verify_rzp(client, auth, out["intent_id"], out["checkout"]["ref"])
    return auth, user_id, out["checkout"]["ref"]


def _child_body(age=15):
    return {"email": f"kid-{uuid.uuid4().hex[:8]}@vsg.com", "password": "kid-password-1", "age": age}


def test_free_parent_cannot_add_seats(client, fakes):
    auth, _, _ = _register(client)
    res = client.post("/api/v1/family/sub-account/create", json=_child_body(), headers=auth)
    assert res.status_code == 402


def test_seats_follow_the_curve_and_cap_at_three(client, fakes):
    auth, user_id, sub_ref = _paid_parent(client, fakes)
    totals = []
    for n in range(3):
        res = client.post("/api/v1/family/sub-account/create", json=_child_body(), headers=auth)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["seat"]["seat_number"] == n + 1
        assert body["seat"]["discount_pct"] == [100, 80, 60][n]
        assert body["seat"]["effective_tier"] == "pro"
        totals.append(body["quote"]["total_minor"])
    assert totals == [100_800, 141_120, 171_360]
    assert ("reprice", sub_ref, 3, 171_360) in fakes["razorpay"].calls

    fourth = client.post("/api/v1/family/sub-account/create", json=_child_body(), headers=auth)
    assert fourth.status_code == 409


def test_child_can_log_in_but_cannot_checkout_or_manage_family(client, fakes):
    auth, _, _ = _paid_parent(client, fakes)
    kid = _child_body(age=11)
    created = client.post("/api/v1/family/sub-account/create", json=kid, headers=auth).json()
    assert created["seat"]["kids_mode"] is True

    login = client.post("/api/v1/auth/login", json={"email": kid["email"], "password": kid["password"]})
    assert login.status_code == 200
    kid_auth = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.post("/api/v1/billing/checkout", json={"tier": "pro"}, headers=kid_auth).status_code == 403
    assert client.post("/api/v1/family/sub-account/create", json=_child_body(), headers=kid_auth).status_code == 403


def test_suspend_drops_child_tier_and_reactivate_restores_it(client, fakes):
    auth, _, _ = _paid_parent(client, fakes)
    kid = _child_body()
    child_id = client.post("/api/v1/family/sub-account/create", json=kid, headers=auth).json()["seat"]["child_user_id"]

    res = client.post("/api/v1/family/sub-account/override", json={"child_user_id": child_id, "status": "suspended"}, headers=auth)
    assert res.status_code == 200
    seat = next(s for s in res.json()["seats"] if s["child_user_id"] == child_id)
    assert seat["status"] == "suspended" and seat["effective_tier"] == "free"

    res = client.post("/api/v1/family/sub-account/override", json={"child_user_id": child_id, "status": "active"}, headers=auth)
    seat = next(s for s in res.json()["seats"] if s["child_user_id"] == child_id)
    assert seat["effective_tier"] == "pro"


def test_parent_losing_subscription_drops_every_child(client, fakes):
    """The webhook syncs seat entitlement (FAM-PRC): children never outlive the parent's tier."""
    auth, user_id, sub_ref = _paid_parent(client, fakes)
    kid = _child_body()
    client.post("/api/v1/family/sub-account/create", json=kid, headers=auth)
    login = client.post("/api/v1/auth/login", json={"email": kid["email"], "password": kid["password"]}).json()
    kid_auth = {"Authorization": f"Bearer {login['token']}"}
    assert _me_tier(client, kid_auth) == "pro"

    _rzp_webhook(client, "subscription.cancelled", sub_ref, "cancelled", {})
    assert _me_tier(client, auth) == "free"
    assert _me_tier(client, kid_auth) == "free"
    # child entitlement follows the parent anchor
    ent = client.post("/api/v1/sync", json={"events": []}, headers=kid_auth).json()["entitlement"]
    assert ent["tier"] == "free"


def test_remove_seat_reprices_down_and_frees_the_child(client, fakes):
    auth, _, sub_ref = _paid_parent(client, fakes)
    child_id = client.post("/api/v1/family/sub-account/create", json=_child_body(), headers=auth).json()["seat"]["child_user_id"]
    res = client.post("/api/v1/family/sub-account/remove", json={"child_user_id": child_id}, headers=auth)
    assert res.status_code == 200
    assert res.json()["seats"] == [] and res.json()["quote"]["total_minor"] == 50_400
    assert ("reprice", sub_ref, 0, 50_400) in fakes["razorpay"].calls
