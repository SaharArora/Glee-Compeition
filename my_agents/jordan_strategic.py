from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import AgentAction, GameState, compact_id


class StrategicMode(str, Enum):
    SAFE = "SAFE"
    EXPLORE = "EXPLORE"
    EXPLOIT = "EXPLOIT"
    COMMIT = "COMMIT"


@dataclass(frozen=True)
class StrategicControl:
    mode: StrategicMode
    submode: str
    expected_gain: float
    posterior_regret: float
    evidence: dict[str, float]
    beliefs: dict[str, float]
    reason: str


class JordanStrategicAgent(CandidateAgent):
    """Evidence-gated strategic-control agent from the redesign PDF.

    This is a first deployable version of the architecture:
    exact-ish economic rules, hierarchical-style population priors, local
    opponent evidence, conservative evidence gates, and game-specific policy
    arms. It intentionally avoids LLM calls and learns only from the legally
    visible state passed by the harness.
    """

    agent_id = "jordan_strategic_v1"

    def __init__(
        self,
        seed: int = 0,
        exploit_evidence_threshold: float = 2.1,
        explore_evidence_threshold: float = 1.25,
        max_posterior_regret: float = 0.18,
        max_counterfactual_uncertainty: float = 0.30,
    ):
        self.rng = random.Random(seed)
        self.exploit_evidence_threshold = exploit_evidence_threshold
        self.explore_evidence_threshold = explore_evidence_threshold
        self.max_posterior_regret = max_posterior_regret
        self.max_counterfactual_uncertainty = max_counterfactual_uncertainty

    def decide(self, state: GameState) -> AgentAction:
        if state.game_family == "bargaining":
            return self._bargaining(state)
        if state.game_family == "negotiation":
            return self._negotiation(state)
        if state.game_family == "persuasion":
            return self._persuasion(state)
        return self._action(state, "unknown", {}, control=self._control(state, {}, {}, "unknown"))

    # ------------------------------------------------------------------
    # Bargaining
    # ------------------------------------------------------------------
    def _bargaining(self, state: GameState) -> AgentAction:
        money = self._float(state.public_parameters.get("money_to_divide"), 100.0)
        beliefs = self._bargaining_beliefs(state, money)
        evidence = self._bargaining_evidence(state, beliefs)
        control = self._control(state, beliefs, evidence, "bargaining")

        if state.valid_action_schema.get("kind") == "offer":
            share = self._bargaining_offer_share(state, control)
            self_gain = round(money * share, 2)
            other_gain = round(money - self_gain, 2)
            structured = {
                "self_gain": self_gain,
                "other_gain": other_gain,
                "message": self._bargaining_message(control, self_gain, other_gain),
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": evidence,
                "beliefs": beliefs,
            }
            return self._action(state, "offer", structured, numeric=self_gain, control=control)

        last_offer = self._last_offer(state)
        offered_share = self._bargaining_share_to_role(last_offer, state.role, money)
        threshold = self._bargaining_accept_threshold(state, control)
        decision = "accept" if offered_share >= threshold else "reject"
        structured = {
            "decision": decision,
            "offered_share": offered_share,
            "accept_threshold": threshold,
            "strategic_mode": control.mode.value,
            "submode": control.submode,
            "evidence": evidence,
            "beliefs": beliefs,
        }
        return self._action(state, "decision", structured, accept_reject=decision, control=control)

    def _bargaining_beliefs(self, state: GameState, money: float) -> dict[str, float]:
        opponent_offers = [item for item in state.visible_transcript if item.get("action_type") == "offer" and item.get("role") != state.role]
        opponent_decisions = [item for item in state.visible_transcript if item.get("action_type") == "decision" and item.get("role") != state.role]
        self_offers = [item for item in state.visible_transcript if item.get("action_type") == "offer" and item.get("role") == state.role]

        opponent_self_shares = [self._float(item.get("self_gain"), money / 2) / money for item in opponent_offers]
        concessions = [opponent_self_shares[i - 1] - opponent_self_shares[i] for i in range(1, len(opponent_self_shares))]
        mean_concession = sum(concessions) / len(concessions) if concessions else 0.0
        last_offer = opponent_offers[-1] if opponent_offers else {}
        last_share_to_us = self._bargaining_share_to_role(last_offer, state.role, money)
        rejection_count = sum(1 for item in opponent_decisions if item.get("accept_reject") == "reject")
        acceptance_count = sum(1 for item in opponent_decisions if item.get("accept_reject") == "accept")
        last_self_offer_share = self._float(self_offers[-1].get("other_gain"), money * 0.45) / money if self_offers else 0.45
        fairness_pressure = max(0.0, 1.0 - abs((last_share_to_us or 0.5) - 0.5) * 4)
        return {
            "concession_rate": self._clip(mean_concession, -0.20, 0.20),
            "opponent_fairness": self._clip(fairness_pressure, 0.0, 1.0),
            "opponent_rejection_rate": rejection_count / max(1, rejection_count + acceptance_count),
            "estimated_accept_threshold": self._clip(last_self_offer_share + 0.03 * rejection_count, 0.35, 0.65),
            "last_offer_share_to_us": self._clip(last_share_to_us, 0.0, 1.0),
        }

    def _bargaining_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        rounds_seen = max(1, len(state.visible_transcript))
        return {
            "E_concessionary": 1.0 + max(0.0, beliefs["concession_rate"]) * 10.0,
            "E_fairness": 1.0 + beliefs["opponent_fairness"] * 1.5,
            "E_impatient": 1.0 + max(0.0, 1.0 - state.round / max(1, state.horizon)) * max(0.0, beliefs["concession_rate"]) * 8.0,
            "E_sample": 1.0 + min(1.0, rounds_seen / 8.0),
        }

    def _bargaining_offer_share(self, state: GameState, control: StrategicControl) -> float:
        remaining = self._remaining(state)
        threshold = control.beliefs.get("estimated_accept_threshold", 0.47)
        if control.mode == StrategicMode.EXPLOIT:
            share = 1.0 - max(0.34, threshold - 0.02)
        elif control.mode == StrategicMode.EXPLORE:
            share = 0.61 if state.round <= 2 else 0.57
        else:
            share = 0.55 if control.beliefs.get("opponent_fairness", 0.5) < 0.70 else 0.52
        if remaining <= 2:
            share = min(share, 0.58)
        return self._clip(share, 0.50, 0.72)

    def _bargaining_accept_threshold(self, state: GameState, control: StrategicControl) -> float:
        remaining = self._remaining(state)
        base = 0.45
        if control.mode == StrategicMode.EXPLOIT:
            base = 0.43
        elif control.mode == StrategicMode.EXPLORE:
            base = 0.47
        if remaining <= 2:
            base -= 0.05
        return self._clip(base, 0.35, 0.50)

    def _bargaining_message(self, control: StrategicControl, self_gain: float, other_gain: float) -> str:
        if control.mode == StrategicMode.EXPLOIT:
            return f"This split closes the deal now while still leaving you {other_gain:g}."
        if control.mode == StrategicMode.EXPLORE:
            return f"This is a serious opening proposal; your response helps us converge quickly."
        return f"This is a balanced offer: {self_gain:g} for me and {other_gain:g} for you."

    # ------------------------------------------------------------------
    # Negotiation
    # ------------------------------------------------------------------
    def _negotiation(self, state: GameState) -> AgentAction:
        beliefs = self._negotiation_beliefs(state)
        evidence = self._negotiation_evidence(state, beliefs)
        control = self._control(state, beliefs, evidence, "negotiation")
        order = self._float(state.public_parameters.get("product_price_order"), 1_000_000.0)

        if state.valid_action_schema.get("kind") == "offer":
            normalized_price = self._negotiation_offer_price(state, control)
            price = round(normalized_price * order, 2)
            structured = {
                "product_price": price,
                "message": self._negotiation_message(state, control, normalized_price),
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": evidence,
                "beliefs": beliefs,
            }
            return self._action(state, "offer", structured, numeric=price, control=control)

        last_price = self._last_numeric(state)
        normalized = last_price / order if last_price is not None else None
        decision = self._negotiation_decision(state, control, normalized)
        structured = {
            "decision": decision,
            "offered_normalized_price": normalized,
            "strategic_mode": control.mode.value,
            "submode": control.submode,
            "evidence": evidence,
            "beliefs": beliefs,
        }
        return self._action(state, "decision", structured, accept_reject=decision, control=control)

    def _negotiation_beliefs(self, state: GameState) -> dict[str, float]:
        seller_value = self._float(state.private_parameters.get("seller_value"), self._float(state.public_parameters.get("seller_value"), 0.72))
        buyer_value = self._float(state.private_parameters.get("buyer_value"), self._float(state.public_parameters.get("buyer_value"), 1.08))
        order = self._float(state.public_parameters.get("product_price_order"), 1_000_000.0)
        opponent_prices = [
            self._float(item.get("numeric_action"), None) / order
            for item in state.visible_transcript
            if item.get("action_type") == "offer" and item.get("role") != state.role and item.get("numeric_action") is not None
        ]
        opponent_prices = [price for price in opponent_prices if price is not None]
        concessions = [abs(opponent_prices[i] - opponent_prices[i - 1]) for i in range(1, len(opponent_prices))]
        mean_concession = sum(concessions) / len(concessions) if concessions else 0.0
        rejection_count = sum(
            1
            for item in state.visible_transcript
            if item.get("action_type") == "decision" and item.get("role") != state.role and item.get("accept_reject") == "RejectOffer"
        )
        if state.role == "seller":
            inferred_buyer_value = max([buyer_value] + opponent_prices + [seller_value + 0.12])
            surplus_room = max(0.0, inferred_buyer_value - seller_value)
        else:
            inferred_seller_value = min([seller_value] + opponent_prices + [buyer_value - 0.12])
            surplus_room = max(0.0, buyer_value - inferred_seller_value)
        return {
            "seller_value": seller_value,
            "buyer_value": buyer_value,
            "opponent_concession_rate": self._clip(mean_concession, 0.0, 0.30),
            "opponent_rejection_count": float(rejection_count),
            "surplus_room": self._clip(surplus_room, 0.0, 1.0),
            "strategic_delay": self._clip(rejection_count / max(1, state.round), 0.0, 1.0),
        }

    def _negotiation_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {
            "E_concessionary": 1.0 + beliefs["opponent_concession_rate"] * 8.0,
            "E_commitment_sensitive": 1.0 + beliefs["strategic_delay"] * (1.0 if state.round >= 2 else 0.25),
            "E_surplus": 1.0 + min(1.0, beliefs["surplus_room"] * 2.0),
            "E_sample": 1.0 + min(1.0, len(state.visible_transcript) / 8.0),
        }

    def _negotiation_offer_price(self, state: GameState, control: StrategicControl) -> float:
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        remaining = self._remaining(state)
        concession = 0.02 * max(0, state.round - 1)
        if state.role == "seller":
            if control.mode == StrategicMode.EXPLOIT:
                price = buyer_value - 0.04 - min(0.06, concession)
            elif control.mode == StrategicMode.COMMIT:
                price = seller_value + min(0.26, max(0.12, control.beliefs["surplus_room"] * 0.55))
            elif control.mode == StrategicMode.EXPLORE:
                price = seller_value + min(0.34, max(0.18, control.beliefs["surplus_room"] * 0.70))
            else:
                price = seller_value + min(0.20, max(0.08, control.beliefs["surplus_room"] * 0.45))
            if remaining <= 2:
                price = min(price, seller_value + max(0.08, control.beliefs["surplus_room"] * 0.40))
            return self._clip(price, seller_value, max(seller_value, buyer_value))

        if control.mode == StrategicMode.EXPLOIT:
            price = seller_value + 0.04 + min(0.06, concession)
        elif control.mode == StrategicMode.EXPLORE:
            price = buyer_value - min(0.32, max(0.18, control.beliefs["surplus_room"] * 0.70))
        else:
            price = buyer_value - min(0.20, max(0.08, control.beliefs["surplus_room"] * 0.45))
        if remaining <= 2:
            price = max(price, buyer_value - max(0.08, control.beliefs["surplus_room"] * 0.40))
        return self._clip(price, min(seller_value, buyer_value), buyer_value)

    def _negotiation_decision(self, state: GameState, control: StrategicControl, normalized_price: float | None) -> str:
        if normalized_price is None:
            return "RejectOffer"
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        remaining = self._remaining(state)
        margin = 0.025 if remaining > 2 else 0.0
        if state.role == "seller":
            return "AcceptOffer" if normalized_price >= seller_value + margin else "RejectOffer"
        return "AcceptOffer" if normalized_price <= buyer_value - margin else "RejectOffer"

    def _negotiation_message(self, state: GameState, control: StrategicControl, normalized_price: float) -> str:
        if control.mode == StrategicMode.COMMIT:
            return f"This price is my firm level for closing now: {normalized_price:.3f} of the normalized scale."
        if control.mode == StrategicMode.EXPLORE:
            return f"This offer tests whether we can close quickly while preserving surplus."
        if control.mode == StrategicMode.EXPLOIT:
            return f"This price captures the value indicated by the negotiation so far."
        return f"This is a practical price for a mutually acceptable deal."

    # ------------------------------------------------------------------
    # Persuasion
    # ------------------------------------------------------------------
    def _persuasion(self, state: GameState) -> AgentAction:
        beliefs = self._persuasion_beliefs(state)
        evidence = self._persuasion_evidence(state, beliefs)
        control = self._control(state, beliefs, evidence, "persuasion")

        if state.role == "seller":
            quality = state.metadata.get("quality")
            if quality is None:
                quality = "high-quality" if beliefs.get("base_quality_prob", 0.5) >= 0.5 else "low-quality"
            decision = self._persuasion_recommendation(state, control, quality)
            structured = {
                "decision": decision,
                "message": self._persuasion_message(control, decision, quality),
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": evidence,
                "beliefs": beliefs,
            }
            return self._action(state, "recommendation", structured, buy_no_buy=decision, control=control)

        decision = self._persuasion_buy_decision(state, control)
        structured = {
            "decision": decision,
            "strategic_mode": control.mode.value,
            "submode": control.submode,
            "evidence": evidence,
            "beliefs": beliefs,
        }
        return self._action(state, "buy_decision", structured, buy_no_buy=decision, control=control)

    def _persuasion_beliefs(self, state: GameState) -> dict[str, float]:
        p = self._float(state.private_parameters.get("p"), self._float(state.public_parameters.get("p"), 0.55))
        v = self._float(state.private_parameters.get("v"), self._float(state.public_parameters.get("v"), 1.2))
        c = self._float(state.private_parameters.get("c"), self._float(state.public_parameters.get("c"), 0.0))
        seller_actions = [item for item in state.visible_transcript if item.get("role") == "seller"]
        buyer_actions = [item for item in state.visible_transcript if item.get("role") == "buyer"]
        qualities = {int(item.get("round", 0)): item for item in state.visible_transcript if item.get("action_type") == "nature_quality"}
        truthful = 0
        truth_total = 0
        for item in seller_actions:
            rec = item.get("buy_no_buy") or (item.get("structured") or {}).get("decision")
            quality = qualities.get(int(item.get("round", 0)), {}).get("quality")
            if rec in {"yes", "no"} and quality:
                truth_total += 1
                truthful += int((rec == "yes") == (quality == "high-quality"))
        buys_after_yes = 0
        yes_seen = 0
        seller_by_round = {int(item.get("round", 0)): item for item in seller_actions}
        for item in buyer_actions:
            seller_item = seller_by_round.get(int(item.get("round", 0)), {})
            rec = seller_item.get("buy_no_buy") or (seller_item.get("structured") or {}).get("decision")
            if rec == "yes":
                yes_seen += 1
                buys_after_yes += int(item.get("buy_no_buy") == "yes")
        honesty = (truthful + 1) / (truth_total + 2)
        obedience = (buys_after_yes + 1) / (yes_seen + 2)
        base_ev = p * (v - 1.0) + (1.0 - p) * (c - 1.0)
        return {
            "base_quality_prob": self._clip(p, 0.0, 1.0),
            "high_value": v,
            "low_value": c,
            "base_expected_value": base_ev,
            "seller_honesty": honesty,
            "receiver_obedience": obedience,
            "receiver_skepticism": 1.0 - obedience,
        }

    def _persuasion_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {
            "E_receiver_obedient": 1.0 + max(0.0, beliefs["receiver_obedience"] - 0.5) * 4.0,
            "E_receiver_skeptical": 1.0 + max(0.0, beliefs["receiver_skepticism"] - 0.5) * 4.0,
            "E_seller_honest": 1.0 + max(0.0, beliefs["seller_honesty"] - 0.5) * 4.0,
            "E_sample": 1.0 + min(1.0, len(state.visible_transcript) / 20.0),
        }

    def _persuasion_recommendation(self, state: GameState, control: StrategicControl, quality: str) -> str:
        is_high = quality == "high-quality"
        remaining_fraction = self._remaining(state) / max(1, state.horizon)
        if is_high:
            return "yes"
        if (
            control.mode == StrategicMode.EXPLOIT
            and control.evidence.get("E_receiver_obedient", 1.0) >= self.exploit_evidence_threshold
            and remaining_fraction <= 0.35
        ):
            return "yes"
        return "no"

    def _persuasion_buy_decision(self, state: GameState, control: StrategicControl) -> str:
        last = state.visible_transcript[-1] if state.visible_transcript else {}
        recommendation = last.get("buy_no_buy") or (last.get("structured") or {}).get("decision") or "no"
        if recommendation == "no":
            return "no"
        posterior_quality = 0.68 if control.beliefs.get("seller_honesty", 0.5) >= 0.55 else 0.52
        ev = posterior_quality * (control.beliefs["high_value"] - 1.0) + (1.0 - posterior_quality) * (control.beliefs["low_value"] - 1.0)
        return "yes" if ev >= -0.02 else "no"

    def _persuasion_message(self, control: StrategicControl, decision: str, quality: str) -> str:
        if decision == "yes":
            return "I recommend buying this product."
        return "I recommend passing on this product."

    # ------------------------------------------------------------------
    # Common control and helpers
    # ------------------------------------------------------------------
    def _control(
        self,
        state: GameState,
        beliefs: dict[str, float],
        evidence: dict[str, float],
        family: str,
    ) -> StrategicControl:
        strongest = max(evidence.values()) if evidence else 1.0
        remaining = self._remaining(state)
        uncertainty = self._counterfactual_uncertainty(state, beliefs, evidence)
        expected_gain = self._expected_exploitation_gain(state, family, beliefs, evidence)
        posterior_regret = self._posterior_regret(state, beliefs, evidence)

        if (
            expected_gain > 0
            and posterior_regret <= self.max_posterior_regret
            and strongest >= self.exploit_evidence_threshold
            and uncertainty <= self.max_counterfactual_uncertainty
        ):
            return StrategicControl(StrategicMode.EXPLOIT, "evidence_gated", expected_gain, posterior_regret, evidence, beliefs, "exploit gate passed")

        if family == "negotiation" and remaining > 2 and evidence.get("E_commitment_sensitive", 1.0) >= 1.7:
            return StrategicControl(StrategicMode.COMMIT, "commitment_screen", expected_gain, posterior_regret, evidence, beliefs, "commitment sensitivity evidence")

        if remaining > 2 and strongest >= self.explore_evidence_threshold:
            return StrategicControl(StrategicMode.EXPLORE, "active_information", expected_gain, posterior_regret, evidence, beliefs, "information value remains")

        return StrategicControl(StrategicMode.SAFE, "robust_floor", expected_gain, posterior_regret, evidence, beliefs, "default robust floor")

    def _expected_exploitation_gain(self, state: GameState, family: str, beliefs: dict[str, float], evidence: dict[str, float]) -> float:
        if family == "bargaining":
            return max(0.0, beliefs.get("estimated_accept_threshold", 0.5) - 0.42) * 0.5
        if family == "negotiation":
            return max(0.0, beliefs.get("surplus_room", 0.0) - 0.15) * 0.35
        if family == "persuasion":
            return max(0.0, beliefs.get("receiver_obedience", 0.5) - 0.55) * 0.4
        return 0.0

    def _posterior_regret(self, state: GameState, beliefs: dict[str, float], evidence: dict[str, float]) -> float:
        sample_e = evidence.get("E_sample", 1.0)
        strongest = max(evidence.values()) if evidence else 1.0
        horizon_penalty = 0.04 if self._remaining(state) <= 2 else 0.10
        return self._clip((0.32 / max(sample_e, 1.0)) + horizon_penalty - 0.05 * (strongest - 1.0), 0.02, 0.50)

    def _counterfactual_uncertainty(self, state: GameState, beliefs: dict[str, float], evidence: dict[str, float]) -> float:
        sample_e = evidence.get("E_sample", 1.0)
        return self._clip(0.42 / max(sample_e, 1.0), 0.05, 0.45)

    def _last_offer(self, state: GameState) -> dict[str, Any]:
        for item in reversed(state.visible_transcript):
            if item.get("action_type") == "offer":
                return item
        return {}

    def _last_numeric(self, state: GameState) -> float | None:
        for item in reversed(state.visible_transcript):
            if item.get("numeric_action") is not None:
                return self._float(item.get("numeric_action"), None)
            structured = item.get("structured") or {}
            if structured.get("product_price") is not None:
                return self._float(structured.get("product_price"), None)
        return None

    def _bargaining_share_to_role(self, offer: dict[str, Any], role: str, money: float) -> float:
        if not offer:
            return 0.0
        if offer.get("role") == role:
            return self._float(offer.get("self_gain"), 0.0) / money
        if offer.get("other_gain") is not None:
            return self._float(offer.get("other_gain"), 0.0) / money
        raw = offer.get("raw") or offer.get("raw_record") or {}
        role_key = "alice_gain" if role in {"player_1", "seller"} else "bob_gain"
        return self._float(raw.get(role_key), 0.0) / money

    def _remaining(self, state: GameState) -> int:
        return max(1, int(state.horizon or state.round or 1) - int(state.round or 1) + 1)

    def _action(
        self,
        state: GameState,
        action_type: str,
        structured: dict[str, Any],
        *,
        numeric: float | None = None,
        message: str | None = None,
        accept_reject: str | None = None,
        buy_no_buy: str | None = None,
        control: StrategicControl,
    ) -> AgentAction:
        structured = dict(structured)
        structured.setdefault("strategic_control", self._control_payload(control))
        return AgentAction(
            action_id=compact_id(state.game_id, state.round, self.agent_id, action_type),
            actor_role=state.role,
            round=state.round,
            raw_text=json.dumps(structured, sort_keys=True),
            action_type=action_type,
            numeric_action=numeric,
            message=message or structured.get("message"),
            accept_reject=accept_reject,
            buy_no_buy=buy_no_buy,
            structured=structured,
        )

    @staticmethod
    def _control_payload(control: StrategicControl) -> dict[str, Any]:
        return {
            "mode": control.mode.value,
            "submode": control.submode,
            "expected_gain": control.expected_gain,
            "posterior_regret": control.posterior_regret,
            "reason": control.reason,
        }

    @staticmethod
    def _float(value: Any, default: float | None = 0.0) -> float | None:
        if value is None:
            return default
        if isinstance(value, (int, float)):
            if isinstance(value, float) and math.isnan(value):
                return default
            return float(value)
        text = str(value).strip()
        if not text:
            return default
        try:
            return float(text.replace("$", "").replace(",", ""))
        except ValueError:
            return default

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))


class MyAgent(JordanStrategicAgent):
    """Alias so `my_agents.jordan_strategic:MyAgent` works like other examples."""
    pass
