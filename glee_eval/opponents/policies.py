from __future__ import annotations

import json
import random
from typing import Any

from glee_eval.data.schemas import AgentAction, GameState, OpponentSpec, compact_id
from glee_eval.opponents.base import OpponentPolicy


def _last_numeric_offer(state: GameState) -> float | None:
    for item in reversed(state.visible_transcript):
        if item.get("action_type") == "offer" and item.get("numeric_action") is not None:
            return float(item["numeric_action"])
    return None


def _last_bargaining_offer_to_role(state: GameState) -> dict[str, Any] | None:
    for item in reversed(state.visible_transcript):
        if item.get("action_type") == "offer":
            return item
    return None


class BargainingPolicy(OpponentPolicy):
    def decide(self, state: GameState) -> AgentAction:
        params = self.spec.parameters
        rng = random.Random(self.spec.seed + state.round)
        money = float(state.public_parameters.get("money_to_divide", 100))
        target_share = float(params.get("target_share", _target_share(self.spec.archetype)))
        concession_rate = float(params.get("concession_rate", 0.04))
        threshold = float(params.get("accept_threshold", max(0.35, 1 - target_share - 0.05)))
        noise = float(params.get("action_noise", 0.0))
        if state.valid_action_schema.get("kind") == "offer":
            # The fitted concession is the change between this player's
            # successive offers. A player offers every other global round, so
            # applying it to `round - 1` doubled the fitted temporal slope.
            own_offer_index = max(0, (state.round - 1) // 2)
            share = target_share - concession_rate * own_offer_index
            if self.spec.archetype in {"boulware", "late_conceding"} and state.round < state.horizon * 0.75:
                share = target_share
            share += rng.uniform(-noise, noise)
            share = min(0.95, max(0.05, share))
            self_gain = round(money * share, 2)
            other_gain = round(money - self_gain, 2)
            structured = {"self_gain": self_gain, "other_gain": other_gain}
            return _action(state, "offer", structured, numeric=self_gain)
        offer = _last_bargaining_offer_to_role(state) or {}
        other_gain = offer.get("other_gain")
        if other_gain is None:
            raw = offer.get("raw") or {}
            for key, value in raw.items():
                if key.endswith("_gain") and key.split("_gain")[0] not in {state.metadata.get("opponent_name", "").lower()}:
                    try:
                        other_gain = float(value)
                    except (TypeError, ValueError):
                        pass
        offered_share = float(other_gain) / money if other_gain is not None else 0.0
        decision = "accept" if offered_share >= threshold else "reject"
        return _action(state, "decision", {"decision": decision}, accept_reject=decision)


class NegotiationPolicy(OpponentPolicy):
    def decide(self, state: GameState) -> AgentAction:
        params = self.spec.parameters
        rng = random.Random(self.spec.seed + state.round)
        order = float(state.public_parameters.get("product_price_order", 1_000_000))
        seller_value = float(state.private_parameters.get("seller_value", state.public_parameters.get("seller_value", 0.75)))
        buyer_value = float(state.private_parameters.get("buyer_value", state.public_parameters.get("buyer_value", 1.05)))
        role = state.role
        concession = float(params.get("concession_rate", 0.04))
        noise = float(params.get("action_noise", 0.0))
        if state.valid_action_schema.get("kind") == "offer":
            if role == "seller":
                aspiration = float(params.get("aspiration_price", buyer_value if buyer_value else 1.1))
                price = aspiration - concession * max(state.round - 1, 0)
                price = max(seller_value, price + rng.uniform(-noise, noise))
            else:
                aspiration = float(params.get("aspiration_price", seller_value if seller_value else 0.7))
                price = aspiration + concession * max(state.round - 1, 0)
                price = min(buyer_value, price + rng.uniform(-noise, noise))
            normalized = min(1.5, max(0.0, price))
            return _action(state, "offer", {"product_price": round(normalized * order, 2)}, numeric=round(normalized * order, 2))
        offer_price = _last_numeric_offer(state)
        normalized_offer = offer_price / order if offer_price is not None else None
        exit_action = "SellToJhon" if role == "seller" else "BuyFromJhon"
        if normalized_offer is None:
            decision = "RejectOffer"
        elif role == "seller":
            min_accept = seller_value + float(params.get("accept_margin", 0.02))
            decision = "AcceptOffer" if normalized_offer >= min_accept else "RejectOffer"
        else:
            max_accept = buyer_value - float(params.get("accept_margin", 0.02))
            decision = "AcceptOffer" if normalized_offer <= max_accept else "RejectOffer"
        if decision == "RejectOffer" and state.round >= max(1, int(state.horizon or 1)):
            # Real players end 19.2% of negotiation decisions on Jhon's deal rather
            # than a bare rejection, concentrated in the closing round.
            decision = exit_action
        return _action(state, "decision", {"decision": decision}, accept_reject=decision)


class PersuasionPolicy(OpponentPolicy):
    """Persuasion opponent driven by the two rates measured off real play.

    `yes_on_low_rate` is P(recommend yes | low quality) and `trust_prior` is
    P(buy | recommended yes), both fitted per configuration segment. Both are used
    as probabilities, which is how they were estimated.

    The previous version applied them as deterministic thresholds -- a seller lied
    on every low-quality round iff `honesty < 0.5`, and a buyer bought on every
    recommendation iff `trust >= 0.35`. That turned a population with a real
    78% obedience rate into a mix of always-buy and never-buy opponents, and made
    the fitted magnitudes meaningless.
    """

    def decide(self, state: GameState) -> AgentAction:
        params = self.spec.parameters
        rng = random.Random(self.spec.seed + state.round)
        if state.role == "seller":
            quality = state.metadata.get("quality", "high-quality")
            if quality == "high-quality":
                # Truthfulness on high quality is the residual of measured honesty.
                honesty = float(params.get("honesty", _honesty(self.spec.archetype)))
                decision = "yes" if rng.random() < max(0.0, min(1.0, honesty)) else "no"
            else:
                lie_rate = params.get("yes_on_low_rate")
                if lie_rate is None:
                    lie_rate = 1.0 - float(params.get("honesty", _honesty(self.spec.archetype)))
                decision = "yes" if rng.random() < max(0.0, min(1.0, float(lie_rate))) else "no"
            if state.valid_action_schema.get("seller_message_type") == "text":
                msg = "I recommend buying this product." if decision == "yes" else "I would pass on this product."
                return _action(state, "message", {"message": msg}, message=msg, buy_no_buy=decision)
            return _action(state, "recommendation", {"decision": decision}, buy_no_buy=decision)
        trust = float(params.get("trust_prior", _trust(self.spec.archetype)))
        last = state.visible_transcript[-1] if state.visible_transcript else {}
        seller_decision = (last.get("buy_no_buy") or (last.get("structured") or {}).get("decision") or "yes")
        if seller_decision == "yes":
            buy = rng.random() < max(0.0, min(1.0, trust))
        else:
            # Real buyers almost never buy against a "no": 962 of 42,970.
            buy = rng.random() < 0.022
        decision = "yes" if buy else "no"
        return _action(state, "buy_decision", {"decision": decision}, buy_no_buy=decision)


def _target_share(archetype: str) -> float:
    if archetype in {"aggressive", "aggressive_extractor"}:
        return 0.75
    if archetype in {"fairness", "fairness_sensitive", "reciprocal"}:
        return 0.52
    if archetype in {"conceding", "soft"}:
        return 0.48
    if archetype in {"random", "noisy"}:
        return 0.60
    return 0.58


def _honesty(archetype: str) -> float:
    if archetype in {"deceptive", "aggressive"}:
        return 0.2
    if archetype in {"honest", "fairness", "rational"}:
        return 0.9
    return 0.6


def _trust(archetype: str) -> float:
    if archetype in {"gullible", "soft", "conceding"}:
        return 0.8
    if archetype in {"skeptical", "adaptive", "exploitation_aware"}:
        return 0.25
    return 0.55


def _action(
    state: GameState,
    action_type: str,
    structured: dict[str, Any],
    *,
    numeric: float | None = None,
    message: str | None = None,
    accept_reject: str | None = None,
    buy_no_buy: str | None = None,
) -> AgentAction:
    return AgentAction(
        action_id=compact_id(state.game_id, state.round, state.role, action_type),
        actor_role=state.role,
        round=state.round,
        raw_text=json.dumps(structured, sort_keys=True),
        action_type=action_type,
        numeric_action=numeric,
        message=message,
        accept_reject=accept_reject,
        buy_no_buy=buy_no_buy,
        structured=structured,
    )


class PolicyFactory:
    @staticmethod
    def create(game_family: str, spec_like: dict[str, Any] | OpponentSpec) -> OpponentPolicy:
        if isinstance(spec_like, OpponentSpec):
            spec = spec_like
        else:
            spec = OpponentSpec(
                archetype=spec_like.get("archetype", "rational"),
                game_family=game_family,
                parameters=dict(spec_like.get("parameters", {}) or {}),
                seed=int(spec_like.get("seed", 0)),
                description=spec_like.get("description", ""),
            )
        if game_family == "bargaining":
            return BargainingPolicy(spec)
        if game_family == "negotiation":
            return NegotiationPolicy(spec)
        if game_family == "persuasion":
            return PersuasionPolicy(spec)
        raise ValueError(f"Unsupported game family: {game_family}")
