"""Glicko-2 rating updates.

Implemented from Glickman's published algorithm rather than from the corpus's
Appendix D pseudocode. That pseudocode mixes the Glicko-1 ``/400`` scale with a
``g()`` that expects the Glicko-2 log scale and skips the volatility step
entirely ("omitted for brevity"), so following it literally would produce
ratings that drift from the system it claims to be. The spec's *intent* — pairwise
Glicko-2 with outcomes by rank — is preserved.

Scale constant 173.7178 converts between the familiar 1500-centred rating scale
and Glicko-2's internal log scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SCALE = 173.7178
DEFAULT_RATING = 1500.0
DEFAULT_RD = 350.0
DEFAULT_VOLATILITY = 0.06
TAU = 0.5  # constrains volatility change; smaller = steadier ratings
CONVERGENCE = 1e-6
RD_MIN, RD_MAX = 30.0, 350.0


@dataclass
class Rating:
    rating: float = DEFAULT_RATING
    rd: float = DEFAULT_RD
    volatility: float = DEFAULT_VOLATILITY

    def to_glicko2(self) -> tuple[float, float]:
        return (self.rating - DEFAULT_RATING) / SCALE, self.rd / SCALE


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _expected(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _new_volatility(phi: float, sigma: float, v: float, delta: float) -> float:
    """Illinois-variant regula falsi on f(x), per the published procedure."""
    a = math.log(sigma * sigma)
    phi2, delta2 = phi * phi, delta * delta

    def f(x: float) -> float:
        ex = math.exp(x)
        numerator = ex * (delta2 - phi2 - v - ex)
        denominator = 2.0 * (phi2 + v + ex) ** 2
        return numerator / denominator - (x - a) / (TAU * TAU)

    A = a
    if delta2 > phi2 + v:
        B = math.log(delta2 - phi2 - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
            if k > 100:  # pathological input; fall back to the current value
                return sigma
        B = a - k * TAU

    fA, fB = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= CONVERGENCE:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA /= 2.0
        B, fB = C, fC

    return math.exp(A / 2.0)


def update_rating(player: Rating, opponents: list[tuple[Rating, float]]) -> Rating:
    """Update one player against a list of (opponent, score) pairs.

    `score` is 1.0 win / 0.5 draw / 0.0 loss.

    A player who did not compete still loses confidence: RD increases by the
    volatility step, which is why the no-opponent branch is not a no-op.
    """
    mu, phi = player.to_glicko2()

    if not opponents:
        phi_star = math.sqrt(phi * phi + player.volatility**2)
        return Rating(
            rating=player.rating,
            rd=min(RD_MAX, max(RD_MIN, phi_star * SCALE)),
            volatility=player.volatility,
        )

    v_inverse = 0.0
    delta_sum = 0.0
    for opponent, score in opponents:
        mu_j, phi_j = opponent.to_glicko2()
        g_j = _g(phi_j)
        e_j = _expected(mu, mu_j, phi_j)
        v_inverse += g_j * g_j * e_j * (1.0 - e_j)
        delta_sum += g_j * (score - e_j)

    if v_inverse == 0:  # every opponent effectively certain — nothing to learn
        return player

    v = 1.0 / v_inverse
    delta = v * delta_sum

    sigma_prime = _new_volatility(phi, player.volatility, v, delta)
    phi_star = math.sqrt(phi * phi + sigma_prime * sigma_prime)
    phi_prime = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + v_inverse)
    mu_prime = mu + phi_prime * phi_prime * delta_sum

    return Rating(
        rating=mu_prime * SCALE + DEFAULT_RATING,
        rd=min(RD_MAX, max(RD_MIN, phi_prime * SCALE)),
        volatility=sigma_prime,
    )


def seed_rating(theta_u: float) -> Rating:
    """First rating from ability: 1000 + 400·θ, clamped to the ELO floor/ceiling
    (PHASE_B_DESIGN §5.2). The `player_elo_ratings` table defaults to 1500, but
    the spec seeds from θ — so seed explicitly on first insert."""
    rating = min(2400.0, max(600.0, 1000.0 + 400.0 * theta_u))
    return Rating(rating=rating, rd=DEFAULT_RD, volatility=DEFAULT_VOLATILITY)


def update_match(ratings: dict[str, Rating], ranks: dict[str, int]) -> dict[str, Rating]:
    """Update every player in a finished match, pairwise by rank.

    All updates are computed from the PRE-match ratings, so the result does not
    depend on the order players happen to be iterated in.
    """
    updated: dict[str, Rating] = {}
    for user_id, rating in ratings.items():
        opponents: list[tuple[Rating, float]] = []
        for other_id, other_rating in ratings.items():
            if other_id == user_id:
                continue
            if ranks[user_id] < ranks[other_id]:
                score = 1.0
            elif ranks[user_id] > ranks[other_id]:
                score = 0.0
            else:
                score = 0.5
            opponents.append((other_rating, score))
        updated[user_id] = update_rating(rating, opponents)
    return updated
