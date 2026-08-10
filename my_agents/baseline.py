from __future__ import annotations

import json
import random

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import AgentAction, GameState, compact_id


class MyAgent(CandidateAgent):
    """Small editable baseline showing the CandidateAgent interface."""

    agent_id = "my_agent_baseline"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def decide(self, state: GameState) -> AgentAction:
        if state.game_family == "bargaining":
            return self._bargaining(state)
        if state.game_family == "negotiation":
            return self._negotiation(state)
        if state.game_family == "persuasion":
            return self._persuasion(state)
        return self._action(state, "unknown", {})

    def _bargaining(self, state: GameState) -> AgentAction:
        money = float(state.public_parameters.get("money_to_divide", 100))
        if state.valid_action_schema.get("kind") == "offer":
            self_gain = round(money * 0.55, 2)
            return self._action(state, "offer", {"self_gain": self_gain, "other_gain": money - self_gain}, numeric=self_gain)
        last_offer = self._last_offer(state)
        offered_share = float(last_offer.get("other_gain", money * 0.45)) / money if last_offer else 0.45
        decision = "accept" if offered_share >= 0.45 else "reject"
        return self._action(state, "decision", {"decision": decision}, accept_reject=decision)

    def _negotiation(self, state: GameState) -> AgentAction:
        order = float(state.public_parameters.get("product_price_order", 1_000_000))
        seller_value = float(state.private_parameters.get("seller_value", state.public_parameters.get("seller_value", 0.75)))
        buyer_value = float(state.private_parameters.get("buyer_value", state.public_parameters.get("buyer_value", 1.05)))
        if state.valid_action_schema.get("kind") == "offer":
            if state.role == "seller":
                normalized_price = min(buyer_value, seller_value + 0.18)
            else:
                normalized_price = max(seller_value, buyer_value - 0.18)
            price = round(normalized_price * order, 2)
            return self._action(state, "offer", {"product_price": price}, numeric=price)
        last_price = self._last_numeric(state)
        normalized = last_price / order if last_price is not None else None
        if normalized is None:
            decision = "RejectOffer"
        elif state.role == "seller":
            decision = "AcceptOffer" if normalized >= seller_value + 0.02 else "RejectOffer"
        else:
            decision = "AcceptOffer" if normalized <= buyer_value - 0.02 else "RejectOffer"
        return self._action(state, "decision", {"decision": decision}, accept_reject=decision)

    def _persuasion(self, state: GameState) -> AgentAction:
        if state.role == "seller":
            quality = state.metadata.get("quality", "high-quality")
            decision = "yes" if quality == "high-quality" else "no"
            return self._action(state, "recommendation", {"decision": decision}, buy_no_buy=decision)
        last = state.visible_transcript[-1] if state.visible_transcript else {}
        recommendation = last.get("buy_no_buy") or (last.get("structured") or {}).get("decision") or "no"
        decision = "yes" if recommendation == "yes" else "no"
        return self._action(state, "buy_decision", {"decision": decision}, buy_no_buy=decision)

    def _last_offer(self, state: GameState) -> dict:
        for item in reversed(state.visible_transcript):
            if item.get("action_type") == "offer":
                return item
        return {}

    def _last_numeric(self, state: GameState) -> float | None:
        for item in reversed(state.visible_transcript):
            if item.get("numeric_action") is not None:
                return float(item["numeric_action"])
        return None

    def _action(
        self,
        state: GameState,
        action_type: str,
        structured: dict,
        *,
        numeric: float | None = None,
        accept_reject: str | None = None,
        buy_no_buy: str | None = None,
    ) -> AgentAction:
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, self.agent_id, action_type),
            actor_role=state.role,
            round=state.round,
            raw_text=json.dumps(structured, sort_keys=True),
            action_type=action_type,
            numeric_action=numeric,
            accept_reject=accept_reject,
            buy_no_buy=buy_no_buy,
            structured=structured,
        )
