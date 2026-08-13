"""Game-theoretic reference points, used as the benchmark regret is measured against.

The harness previously scored regret against a hard-coded 0.5 for bargaining and
negotiation. That is not an achievable payoff in either family: in a negotiation
config with no gains from trade the best any player can do is 0, so optimal play
was charged 0.5 regret and then labelled UNDER_AGGRESSIVE. Every benchmark here
is derived from the config instead, so "regret" means distance from something the
candidate could actually have obtained.

These are upper bounds on what the candidate could get, not predictions of what a
particular opponent concedes. Bargaining is the exception and the interesting one:
its subgame-perfect share is an equilibrium value, which is the structural prior
the design memo asks for.
"""

from __future__ import annotations

from typing import Any

from glee_eval.data.ingest import as_float


def _delta(config: dict[str, Any], key: str) -> float:
    value = as_float(config.get(key))
    if value is None:
        return 1.0
    return min(1.0, max(0.0, value))


# Deltas in the released bargaining configs are near-uniform over this grid
# (delta_1 and delta_2 each ~8.3k games per level across 33,739 games), pooled
# mean 0.9133. Used as the prior for an unobserved opponent delta under
# complete_information=False.
EMPIRICAL_DELTA_GRID = (0.8, 0.9, 0.95, 1.0)
EMPIRICAL_DELTA_MEAN = 0.9133

# Negotiation values are likewise near-uniform over a four-point grid: seller
# mean 1.1230, buyer mean 1.1255 over 33,627 games. Used as the prior for an
# unobserved counterpart value under complete_information=False. Note both means
# sit *above* 1.0, so the old hard-coded defaults of 0.72 (seller) and 1.08
# (buyer) were both biased, and the buyer one was biased in the direction that
# invents gains from trade.
EMPIRICAL_VALUE_GRID = (0.8, 1.0, 1.2, 1.5)
EMPIRICAL_SELLER_VALUE_MEAN = 1.1230
EMPIRICAL_BUYER_VALUE_MEAN = 1.1255


def bargaining_secured_shares(config: dict[str, Any]) -> list[float]:
    """`A(r)` for every round: the share the round-`r` proposer secures in SPE.

    Index `r - 1` holds `A(r)`. Player 1 proposes in odd rounds.
    """

    horizon = max(1, int(as_float(config.get("max_rounds")) or 1))
    delta_1 = _delta(config, "delta_1")
    delta_2 = _delta(config, "delta_2")
    secured = [0.0] * horizon
    secured[horizon - 1] = 1.0
    for round_number in range(horizon - 1, 0, -1):
        responder_delta = delta_2 if round_number % 2 else delta_1
        value = 1.0 - responder_delta * secured[round_number]
        secured[round_number - 1] = min(1.0, max(0.0, value))
    return secured


def bargaining_accept_floor(config: dict[str, Any], role: str, round_number: int) -> float:
    """Smallest share a responder should accept at `round_number`.

    Rejecting makes you the proposer next round, securing `A(r+1)` one period
    later, so accepting `y` now beats rejecting exactly when
    `y >= delta_you * A(r+1)`. In the final round the continuation is nothing, so
    any non-negative share is worth taking.
    """

    horizon = max(1, int(as_float(config.get("max_rounds")) or 1))
    round_number = max(1, int(round_number or 1))
    if round_number >= horizon:
        return 0.0
    secured = bargaining_secured_shares(config)
    own_delta = _delta(config, "delta_1" if role == "player_1" else "delta_2")
    return min(1.0, max(0.0, own_delta * secured[round_number]))


def bargaining_spe_shares(config: dict[str, Any]) -> tuple[float, float]:
    """Subgame-perfect equilibrium shares for finite-horizon alternating offers.

    GLEE pays a share `s` agreed in round `r` as `s * delta_i**(r-1)`, and player 1
    proposes in odd rounds. Backward induction on the proposer's secured share:

        A(T) = 1                        -- the last proposer can offer ~0
        A(r) = 1 - delta_responder(r) * A(r+1)

    because a responder rejecting at `r` becomes the proposer at `r+1` and must be
    left indifferent. Returns the round-1 shares, which are undiscounted and so are
    the payoffs themselves.

    With an infinite horizon and a common delta this reduces to 1/(1+delta), the
    standard Rubinstein result.
    """

    horizon = int(as_float(config.get("max_rounds")) or 1)
    horizon = max(1, horizon)
    delta_1 = _delta(config, "delta_1")
    delta_2 = _delta(config, "delta_2")

    del delta_1, delta_2, horizon  # handled by bargaining_secured_shares
    first = bargaining_secured_shares(config)[0]
    return first, 1.0 - first


def negotiation_max_surplus(config: dict[str, Any]) -> float:
    """The whole pie in a negotiation: 0 when there are no gains from trade."""

    seller_value = as_float(config.get("seller_value"))
    buyer_value = as_float(config.get("buyer_value"))
    if seller_value is None or buyer_value is None:
        return 0.0
    return max(0.0, buyer_value - seller_value)


def persuasion_max_payoff(role: str, config: dict[str, Any], transcript: list[dict[str, Any]] | None = None) -> float:
    """Best payoff achievable *from that role's own information*.

    Deliberately not a perfect-foresight bound. A buyer cannot see the round's
    quality, so scoring them against "bought exactly the profitable rounds" would
    charge regret for information they never had. The information-feasible ceiling
    is buying whenever recommended by a truthful sender, worth `p * (v - 1)` per
    round -- the Bayesian-persuasion benchmark, and never worse than the 0 of
    never buying.

    A seller's ceiling is selling in every round, which is achievable against a
    trusting receiver.

    `transcript` is accepted so callers need not special-case by role, and is
    unused: including it would reintroduce the omniscient bound.
    """

    if role == "seller":
        return 1.0
    p = as_float(config.get("p"))
    v = as_float(config.get("v"))
    if p is None or v is None:
        return 0.0
    return max(0.0, p * (v - 1.0))


def reference_payoff(
    game_family: str,
    role: str,
    config: dict[str, Any],
    *,
    transcript: list[dict[str, Any]] | None = None,
) -> float:
    """Benchmark the candidate's payoff is compared against, in payoff units."""

    if game_family == "bargaining":
        p1_share, p2_share = bargaining_spe_shares(config)
        return p1_share if role == "player_1" else p2_share
    if game_family == "negotiation":
        return negotiation_max_surplus(config)
    if game_family == "persuasion":
        return persuasion_max_payoff(role, config, transcript)
    return 0.0
