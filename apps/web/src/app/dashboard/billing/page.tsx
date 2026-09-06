"use client";

/**
 * Billing — Razorpay Checkout (primary, INR) with Stripe hosted checkout as
 * the secondary. The server owns every price and every grant: this page only
 * relays the provider's handler result to /billing/checkout/verify and then
 * refreshes the entitlement it is handed back (PAY-04).
 */

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cancelSubscription, checkout, getPlans, getSubscription, loadRazorpay, verifyRazorpay, type Plan } from "@/services/billing";
import { useEntitlementStore } from "@/stores/entitlement-store";
import { useAuthStore } from "@/stores/auth-store";

type RazorpayCtor = new (opts: Record<string, unknown>) => { open: () => void };

export default function BillingPage() {
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["billing-plans"], queryFn: getPlans });
  const sub = useQuery({ queryKey: ["billing-subscription"], queryFn: getSubscription });
  const setEntitlement = useEntitlementStore((s) => s.setEntitlement);
  const email = useAuthStore((s) => s.user?.email);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (sub.data?.entitlement) setEntitlement(sub.data.entitlement);
  }, [sub.data, setEntitlement]);

  async function buy(plan: Plan) {
    setBusy(plan.tier);
    setNotice(null);
    try {
      const out = await checkout(plan.tier);
      if (out.provider === "stripe" && out.checkout.url) {
        window.location.href = out.checkout.url;
        return;
      }
      if (!(await loadRazorpay())) throw new Error("Razorpay checkout could not load");
      const Razorpay = (window as unknown as { Razorpay: RazorpayCtor }).Razorpay;
      const rz = new Razorpay({
        key: out.checkout.key_id,
        subscription_id: out.checkout.subscription_id,
        name: out.checkout.name ?? "Exam Arena",
        description: out.checkout.description,
        prefill: { email: out.checkout.prefill?.email ?? email },
        handler: async (r: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) => {
          const v = await verifyRazorpay({ intent_id: out.intent_id, ...r });
          setEntitlement(v.entitlement);
          setNotice(`You're on ${v.tier}. Trial for ${plans.data?.trial_days ?? 7} days.`);
          void qc.invalidateQueries({ queryKey: ["billing-subscription"] });
        },
        modal: { ondismiss: () => setBusy(null) },
      });
      rz.open();
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Checkout failed");
    } finally {
      setBusy(null);
    }
  }

  async function cancel() {
    setBusy("cancel");
    try {
      await cancelSubscription();
      setNotice("Cancellation scheduled for the end of your period. To resume on Razorpay, re-subscribe after your period ends.");
      void qc.invalidateQueries({ queryKey: ["billing-subscription"] });
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not cancel");
    } finally {
      setBusy(null);
    }
  }

  const current = sub.data?.subscription;
  const inr = (paise: number) => `₹${(paise / 100).toFixed(2)}`;

  return (
    <main className="mx-auto min-h-dvh w-full max-w-xl bg-background px-5 py-8">
      <h1 className="text-fluid-xl font-semibold">Plans</h1>
      <p className="mt-1 text-fluid-sm text-muted-foreground">
        Prices in INR via Razorpay. Cards outside India use Stripe. {plans.data ? `Rate ₹${plans.data.usd_inr_rate}/$` : ""}
      </p>
      {current && (
        <div className="mt-4 rounded-lg border border-border bg-card p-3 text-fluid-sm">
          <div className="flex items-center justify-between">
            <span>Current: <strong>{current.tier}</strong> · {current.status}{current.cancel_at_period_end ? " · ends at period end" : ""}</span>
            {!current.cancel_at_period_end && (
              <button type="button" onClick={cancel} disabled={busy === "cancel"} className="text-muted-foreground underline">Cancel</button>
            )}
          </div>
          {current.current_period_end && <p className="mt-1 text-muted-foreground">Renews {new Date(current.current_period_end).toLocaleDateString()}</p>}
        </div>
      )}
      {notice && <p className="mt-3 rounded-lg bg-accent p-3 text-fluid-sm">{notice}</p>}
      <div className="mt-5 grid gap-3">
        {(plans.data?.plans ?? []).filter((p) => p.tier !== "free").map((p) => (
          <div key={p.tier} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-medium capitalize">{p.tier.replace("_", " ")}</h2>
                <p className="text-fluid-xs text-muted-foreground">{p.lanes} exam lane{p.lanes > 1 ? "s" : ""} · ad-free · {p.trial_days}-day trial</p>
              </div>
              <div className="text-right">
                <div className="font-semibold">{inr(p.inr_paise)}<span className="text-fluid-xs text-muted-foreground">/mo</span></div>
                <div className="text-fluid-xs text-muted-foreground">${(p.usd_cents / 100).toFixed(2)}</div>
              </div>
            </div>
            <button
              type="button"
              disabled={busy !== null || current?.tier === p.tier}
              onClick={() => buy(p)}
              className="mt-3 w-full rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground disabled:opacity-50"
            >
              {current?.tier === p.tier ? "Current plan" : busy === p.tier ? "Opening checkout…" : "Start free trial"}
            </button>
          </div>
        ))}
      </div>
      <p className="mt-6 text-fluid-xs text-muted-foreground">
        Family seats (up to 3 children at 100/80/60 %) are added from the Family screen after subscribing.
      </p>
    </main>
  );
}
