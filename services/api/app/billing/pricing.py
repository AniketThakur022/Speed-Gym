"""Tier prices, currency conversion and the family seat curve.

Prices are the RFP's USD figures (SUB-01..04): Free $0, Pro $6, Bundle_2 $9.60,
Bundle_3 $12.60 per month. INR is derived from the configured USD→INR rate at
quote time and frozen onto the checkout intent, so a rate change never
re-prices a subscription already sold.

Family plan (FAM-PRC-*): the parent pays full price; child seats 1/2/3 cost
100/80/60 % of the tier price. Seats are billed on the parent's subscription
as one amount — there is no per-child payment method.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TIER_USD_CENTS: dict[str, int] = {"free": 0, "pro": 600, "bundle_2": 960, "bundle_3": 1260}
PAID_TIERS: tuple[str, ...] = ("pro", "bundle_2", "bundle_3")
TIER_LANES: dict[str, int] = {"free": 1, "pro": 1, "bundle_2": 2, "bundle_3": 3}

MAX_FAMILY_SEATS = 3
SEAT_DISCOUNT_PCT: dict[int, int] = {1: 100, 2: 80, 3: 60}

SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"INR", "USD"})


class PricingError(ValueError):
    pass


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def usd_cents_to_minor(usd_cents: int, currency: str, usd_inr_rate: float) -> int:
    """Convert a USD-cent price to the minor unit of `currency`.

    1 cent × rate = 1 paisa-equivalent: $6.00 = 600 cents → 600 × 84 = 50,400
    paise = ₹504.00. Half-up rounding keeps a price like $9.60 × 83.5 exact.
    """
    if currency == "USD":
        return int(usd_cents)
    if currency == "INR":
        if usd_inr_rate <= 0:
            raise PricingError("usd_inr_rate must be positive")
        return _round_half_up(Decimal(usd_cents) * Decimal(str(usd_inr_rate)))
    raise PricingError(f"unsupported currency: {currency}")


def to_usd_cents(amount_minor: int, currency: str, usd_inr_rate) -> int:
    """Inverse of usd_cents_to_minor, for MRR/revenue bookkeeping in USD cents.
    INR needs the rate that was frozen at sale time — never the current one."""
    if currency == "USD":
        return int(amount_minor)
    if currency == "INR":
        rate = float(usd_inr_rate or 0)
        if rate <= 0:
            raise PricingError("usd_inr_rate required to convert INR to USD cents")
        return _round_half_up(Decimal(amount_minor) / Decimal(str(rate)))
    raise PricingError(f"unsupported currency: {currency}")


def seat_discount_pct(seat_number: int) -> int:
    try:
        return SEAT_DISCOUNT_PCT[seat_number]
    except KeyError:
        raise PricingError(f"seat_number must be 1..{MAX_FAMILY_SEATS}") from None


def family_multiplier_pct(seats_count: int) -> int:
    """Parent (100 %) + the seat curve: 0→100, 1→200, 2→280, 3→340."""
    if not 0 <= seats_count <= MAX_FAMILY_SEATS:
        raise PricingError(f"seats_count must be 0..{MAX_FAMILY_SEATS}")
    return 100 + sum(SEAT_DISCOUNT_PCT[n] for n in range(1, seats_count + 1))


@dataclass(frozen=True)
class Quote:
    tier: str
    seats_count: int
    currency: str
    usd_inr_rate: float
    unit_minor: int            # one full-price subscription in minor units
    parent_minor: int
    seat_minor: tuple[int, ...]
    total_minor: int

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "seats_count": self.seats_count,
            "currency": self.currency,
            "usd_inr_rate": self.usd_inr_rate if self.currency == "INR" else None,
            "unit_minor": self.unit_minor,
            "parent_minor": self.parent_minor,
            "seat_minor": list(self.seat_minor),
            "total_minor": self.total_minor,
            "lanes": TIER_LANES[self.tier],
        }


def quote(tier: str, seats_count: int, currency: str, usd_inr_rate: float) -> Quote:
    if tier not in PAID_TIERS:
        raise PricingError(f"tier must be one of {PAID_TIERS}")
    if currency not in SUPPORTED_CURRENCIES:
        raise PricingError(f"unsupported currency: {currency}")
    if not 0 <= seats_count <= MAX_FAMILY_SEATS:
        raise PricingError(f"seats_count must be 0..{MAX_FAMILY_SEATS}")

    unit = usd_cents_to_minor(TIER_USD_CENTS[tier], currency, usd_inr_rate)
    seats = tuple(
        _round_half_up(Decimal(unit) * Decimal(seat_discount_pct(n)) / Decimal(100))
        for n in range(1, seats_count + 1)
    )
    return Quote(
        tier=tier,
        seats_count=seats_count,
        currency=currency,
        usd_inr_rate=usd_inr_rate,
        unit_minor=unit,
        parent_minor=unit,
        seat_minor=seats,
        total_minor=unit + sum(seats),
    )


def plan_catalog(usd_inr_rate: float, trial_days: int) -> list[dict]:
    """What `GET /billing/plans` shows: every tier in both currencies."""
    out = []
    for tier, cents in TIER_USD_CENTS.items():
        out.append(
            {
                "tier": tier,
                "lanes": TIER_LANES[tier],
                "usd_cents": cents,
                "inr_paise": usd_cents_to_minor(cents, "INR", usd_inr_rate),
                "trial_days": trial_days if tier in PAID_TIERS else 0,
                "ad_free": tier in PAID_TIERS,
            }
        )
    return out
