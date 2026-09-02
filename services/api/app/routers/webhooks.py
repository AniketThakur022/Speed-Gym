"""Payment webhook shells — provider-agnostic per the parked owner decision
(Razorpay-first vs Stripe-first). Routes and signature-verification seams
exist so the frozen paths never change; both return 501 until a provider is
chosen and configured. Server-to-server paths stay OUTSIDE /api/v1
(api-contract-v1).
"""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Stripe-Signature HMAC check — wired when STRIPE_WEBHOOK_SECRET lands."""
    raise NotImplementedError


def verify_razorpay_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """X-Razorpay-Signature HMAC check — wired when RAZORPAY_KEY_SECRET lands."""
    raise NotImplementedError


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    raise HTTPException(
        status_code=501,
        detail="payments not wired: Razorpay-first vs Stripe-first is an open owner decision",
    )


@router.post("/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    raise HTTPException(
        status_code=501,
        detail="payments not wired: Razorpay-first vs Stripe-first is an open owner decision",
    )
