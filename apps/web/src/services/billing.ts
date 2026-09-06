import { apiGet, apiPost } from "./api";

export type Plan = { tier: string; lanes: number; usd_cents: number; inr_paise: number; trial_days: number; ad_free: boolean };
export type Plans = { default_provider: string; default_currency: string; providers_available: string[]; usd_inr_rate: number; trial_days: number; plans: Plan[] };
export type CheckoutOut = {
  intent_id: string;
  provider: "razorpay" | "stripe";
  quote: { total_minor: number; currency: string };
  checkout: { key_id?: string; subscription_id?: string; name?: string; description?: string; prefill?: { email?: string }; url?: string; session_id?: string };
};
export type Subscription = { tier: string; subscription: null | { status: string; tier: string; current_period_end: string | null; cancel_at_period_end: boolean; provider: string }; entitlement: { tier: string; expires_at: number; grace_days: number; signature: string } };

export const getPlans = () => apiGet<Plans>("/billing/plans");
export const getSubscription = () => apiGet<Subscription>("/billing/subscription");
export const checkout = (tier: string, provider?: string) => apiPost<CheckoutOut>("/billing/checkout", { tier, provider });
export const verifyRazorpay = (body: { intent_id: string; razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) =>
  apiPost<{ tier: string; entitlement: Subscription["entitlement"] }>("/billing/checkout/verify", body);
export const cancelSubscription = () => apiPost("/billing/cancel");

/** Razorpay Checkout is a hosted script; load it once, on demand. */
export function loadRazorpay(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  const w = window as unknown as { Razorpay?: unknown };
  if (w.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });
}
