from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass
from enum import Enum
from typing import Any

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import AgentAction, GameState, compact_id
from glee_eval.data.transcripts import transcript_item_decision, transcript_item_quality
from glee_eval.response_models.runtime import EmpiricalResponseModel, ResponseEstimate
from glee_eval.simulate.coverage_gate import CoverageGate
from my_agents.message_composer import PersuasionMessageComposer, shadow_record
from glee_eval.theory.benchmarks import (
    EMPIRICAL_BUYER_VALUE_MEAN,
    EMPIRICAL_DELTA_MEAN,
    EMPIRICAL_SELLER_VALUE_MEAN,
    bargaining_accept_floor,
    bargaining_spe_shares,
)

# Real bargaining offers cluster hard at a self-share of 0.5-0.7 (45,633 of
# ~93k offers land in 0.5-0.6 and 26,095 in 0.6-0.7), i.e. the observed
# population is fairness-anchored rather than playing SPE. So SPE is used to
# decide how hard to push, never as a target to concede down to: conceding to a
# 0.0 equilibrium share against a fairness-anchored opponent would give away a
# pot they would have split.
BARGAINING_FAIRNESS_FLOOR = 0.50


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
    coverage: dict[str, Any] | None = None
    counterfactual_uncertainty: float | None = None


class JordanStrategicAgent(CandidateAgent):
    """Evidence-gated strategic-control agent from the redesign PDF.

    This is a first deployable version of the architecture:
    exact-ish economic rules, hierarchical-style population priors, local
    opponent evidence, conservative evidence gates, and game-specific policy
    arms. It intentionally avoids LLM calls and learns only from the legally
    visible state passed by the harness.

    Two empirical-support signals feed this agent, and they are deliberately
    kept separate because they answer different questions:

    * The audit support index, read through `CoverageGate`, answers "do we have
      real data about this situation at all?". It is context-level, shared with
      the simulation dispatcher and the negotiation diagnostic, and it governs
      the binary question of whether the agent is allowed to escalate to
      EXPLOIT, plus which decisions get flagged for counterfactual simulation.
    * The trained response model's own `support_quality` answers "how tightly is
      this specific offer bucket estimated?". It is bucket-local to one binned
      table and is only used to weigh candidate numeric values against each
      other, where a bucket-local answer is the right one.
    """

    agent_id = "jordan_strategic_v1"

    def __init__(
        self,
        seed: int = 0,
        exploit_evidence_threshold: float = 2.1,
        explore_evidence_threshold: float = 1.25,
        max_posterior_regret: float = 0.18,
        max_counterfactual_uncertainty: float = 0.30,
        response_model_path: str | None = None,
        support_index_path: str | None = None,
        coverage_uncertainty_weight: float = 0.15,
        use_theory_anchor: bool = True,
        message_mode: str = "shadow",
        persuasion_explore: bool = False,
        max_exploration_loss: float = 0.45,
    ):
        self.rng = random.Random(seed)
        self.exploit_evidence_threshold = exploit_evidence_threshold
        self.explore_evidence_threshold = explore_evidence_threshold
        self.max_posterior_regret = max_posterior_regret
        self.max_counterfactual_uncertainty = max_counterfactual_uncertainty
        self.coverage_uncertainty_weight = coverage_uncertainty_weight
        # Drive the offer and accept rules from the SPE share and the
        # continuation-value accept floor. On by default, but only on the strength
        # of a measurement taken against *calibrated* opponents -- the sign of this
        # effect depends entirely on who the opponent is:
        #
        #   vs hand-picked opponents   -0.040 payoff (t=-5.83), agreement 0.99 -> 0.87
        #   vs fitted real population  +0.046 payoff (t=+6.60), agreement 0.64 -> 0.75
        #
        # Both are paired over 800 bargaining episodes across the real delta grid.
        # The first number is the artifact: hand-picked opponents accepted anything
        # above ~0.30-0.55, so the delta-blind constants of 0.52-0.58 were tuned to
        # invented behavior. Against opponents that accept where real ones do
        # (0.41-0.50) reasoning about time preference wins clearly, and wins *more*
        # deals rather than fewer.
        #
        # Either way the SPE share and accept floor are always computed and always
        # reported in the action's beliefs, so time preference stays legible in the
        # ledger even with this off.
        self.use_theory_anchor = use_theory_anchor
        # "shadow": compose a candidate persuasion message, record it, but keep
        # sending the existing template. "live": actually send the composed one.
        #
        # Shadow by default because the promotion gate cannot run on message text.
        # Nothing in the simulator reads messages -- replacing every template with
        # "." moves persuasion payoff by 0.000000 -- so an in-simulator A/B of a
        # language change measures nothing, and calibrating a message-reading
        # opponent on the same step-3 numbers we would be testing would be
        # circular. Real logged games are the only non-circular evidence, and
        # shadow mode is how they accumulate without risking rated games on a
        # change no gate has passed.
        self.message_mode = message_mode
        self.message_composer = PersuasionMessageComposer()
        # Buy occasionally despite negative EV to break the persuasion cold start.
        #
        # OFF by default: it was rejected by the promotion gate. Paired over 1,600
        # holdout persuasion episodes it measured +0.0051 (t=+3.36) -- real, but
        # below the 0.0100 minimum effect, and `minimum_effect` is one of the checks
        # the defect carve-out may not waive. It also stayed concentrated in the
        # config regimes where a cold start exists (0.627 concentration, 0.500 of
        # regimes regressing).
        #
        # Kept because the case it addresses is live-only and the simulator only
        # half-reproduces it: a live buyer in a high-break-even config declines every
        # round forever, since its posterior cannot move until it buys once. That
        # argument is not something the gate can test, so the flag stays available
        # and off rather than the reasoning being deleted.
        self.persuasion_explore = persuasion_explore
        # Never explore when a single buy would cost more than this in price units.
        self.max_exploration_loss = max_exploration_loss
        self.response_model = EmpiricalResponseModel.load(response_model_path or os.getenv("GLEE_RESPONSE_MODEL"))
        self.coverage_gate = CoverageGate.from_path(support_index_path or os.getenv("GLEE_SUPPORT_INDEX"))

    def attach_coverage_gate(self, gate: CoverageGate) -> None:
        """Accept the run-level coverage gate from the simulation dispatcher.

        A gate handed over this way carries a dispatcher, so out-of-support
        decisions can request a targeted counterfactual simulation. A gate built
        from `GLEE_SUPPORT_INDEX` alone is measurement-only.
        """

        self.coverage_gate = gate

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
            empirical = self._bargaining_empirical_offer_share(state, control)
            if empirical:
                share, empirical_payload = empirical
            else:
                empirical_payload = None
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
            if empirical_payload:
                structured["empirical_response_model"] = empirical_payload
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
        opponent_offers = [item for item in self._transcript(state) if item.get("action_type") == "offer" and item.get("role") != state.role]
        opponent_decisions = [item for item in self._transcript(state) if item.get("action_type") == "decision" and item.get("role") != state.role]
        self_offers = [item for item in self._transcript(state) if item.get("action_type") == "offer" and item.get("role") == state.role]

        opponent_self_shares = [self._float(item.get("self_gain"), money / 2) / money for item in opponent_offers]
        concessions = [opponent_self_shares[i - 1] - opponent_self_shares[i] for i in range(1, len(opponent_self_shares))]
        mean_concession = sum(concessions) / len(concessions) if concessions else 0.0
        last_offer = opponent_offers[-1] if opponent_offers else {}
        last_share_to_us = self._bargaining_share_to_role(last_offer, state.role, money)
        rejection_count = sum(1 for item in opponent_decisions if item.get("accept_reject") == "reject")
        acceptance_count = sum(1 for item in opponent_decisions if item.get("accept_reject") == "accept")
        last_self_offer_share = self._float(self_offers[-1].get("other_gain"), money * 0.45) / money if self_offers else 0.45
        fairness_pressure = max(0.0, 1.0 - abs((last_share_to_us or 0.5) - 0.5) * 4)
        theory = self._bargaining_theory(state)
        return {
            "concession_rate": self._clip(mean_concession, -0.20, 0.20),
            "opponent_fairness": self._clip(fairness_pressure, 0.0, 1.0),
            "opponent_rejection_rate": rejection_count / max(1, rejection_count + acceptance_count),
            "estimated_accept_threshold": self._clip(last_self_offer_share + 0.03 * rejection_count, 0.35, 0.65),
            "last_offer_share_to_us": self._clip(last_share_to_us, 0.0, 1.0),
            **theory,
        }

    def _bargaining_theory(self, state: GameState) -> dict[str, float]:
        """Time preference: our SPE share and the share we should stop accepting below.

        In alternating-offers bargaining the equilibrium split is determined
        entirely by the two discount factors, and 75% of real games have
        asymmetric ones -- so ignoring them, as this agent previously did, throws
        away the central strategic parameter of the family.

        Under `complete_information=False` only our own delta is visible. The
        opponent's is filled in with the empirical mean of the released delta grid
        rather than assumed equal to ours, and `delta_other_known` records which
        happened so the caller can stay more cautious when it was a guess.
        """

        own_key = "delta_1" if state.role == "player_1" else "delta_2"
        other_key = "delta_2" if state.role == "player_1" else "delta_1"
        own = self._float(state.private_parameters.get(own_key), self._float(state.public_parameters.get(own_key), None))
        other = self._float(state.private_parameters.get(other_key), self._float(state.public_parameters.get(other_key), None))
        known = other is not None
        config = {
            "max_rounds": self._horizon(state),
            own_key: own if own is not None else EMPIRICAL_DELTA_MEAN,
            other_key: other if other is not None else EMPIRICAL_DELTA_MEAN,
        }
        p1_share, p2_share = bargaining_spe_shares(config)
        return {
            "own_delta": config[own_key],
            "other_delta": config[other_key],
            "delta_other_known": 1.0 if known else 0.0,
            "spe_share": p1_share if state.role == "player_1" else p2_share,
            "spe_accept_floor": bargaining_accept_floor(config, state.role, self._round(state)),
        }

    def _bargaining_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        rounds_seen = max(1, len(self._transcript(state)))
        return {
            "E_concessionary": 1.0 + max(0.0, beliefs["concession_rate"]) * 10.0,
            "E_fairness": 1.0 + beliefs["opponent_fairness"] * 1.5,
            "E_impatient": 1.0 + max(0.0, 1.0 - self._round(state) / self._horizon(state)) * max(0.0, beliefs["concession_rate"]) * 8.0,
            "E_sample": 1.0 + min(1.0, rounds_seen / 8.0),
        }

    def _bargaining_offer_share(self, state: GameState, control: StrategicControl) -> float:
        """Ask for the fairness anchor, or the SPE share when theory says we are stronger.

        Previously this returned a constant 0.52-0.61 clipped to [0.50, 0.72] with
        no reference to time preference, so a config where our equilibrium share is
        0.74 was played identically to one where it is 0.17.
        """

        remaining = self._remaining(state)
        threshold = control.beliefs.get("estimated_accept_threshold", 0.47)
        if not self.use_theory_anchor:
            return self._bargaining_offer_share_flat(state, control)
        spe_share = control.beliefs.get("spe_share", BARGAINING_FAIRNESS_FLOOR)
        # SPE only raises the ask. Conceding down to a low equilibrium share
        # against the observed fairness-anchored population would give away value
        # those opponents were willing to leave us.
        anchor = max(BARGAINING_FAIRNESS_FLOOR, spe_share)
        # A guessed opponent delta is weaker evidence, so bank less of the edge.
        if not control.beliefs.get("delta_other_known", 0.0):
            anchor = BARGAINING_FAIRNESS_FLOOR + 0.5 * (anchor - BARGAINING_FAIRNESS_FLOOR)

        if control.mode == StrategicMode.EXPLOIT:
            share = max(anchor, 1.0 - max(0.34, threshold - 0.02))
        elif control.mode == StrategicMode.EXPLORE:
            share = anchor + (0.08 if self._round(state) <= 2 else 0.05)
        else:
            share = anchor + (0.05 if control.beliefs.get("opponent_fairness", 0.5) < 0.70 else 0.02)
        if remaining <= 2:
            # Closing window: do not push past what still clears the fairness anchor.
            share = min(share, max(anchor, 0.58))
        return self._clip(share, BARGAINING_FAIRNESS_FLOOR, 0.80)

    def _bargaining_offer_share_flat(self, state: GameState, control: StrategicControl) -> float:
        """Fairness-anchored constants: the default until opponents are calibrated."""

        remaining = self._remaining(state)
        threshold = control.beliefs.get("estimated_accept_threshold", 0.47)
        if control.mode == StrategicMode.EXPLOIT:
            share = 1.0 - max(0.34, threshold - 0.02)
        elif control.mode == StrategicMode.EXPLORE:
            share = 0.61 if self._round(state) <= 2 else 0.57
        else:
            share = 0.55 if control.beliefs.get("opponent_fairness", 0.5) < 0.70 else 0.52
        if remaining <= 2:
            share = min(share, 0.58)
        return self._clip(share, 0.50, 0.72)

    def _bargaining_accept_threshold_flat(self, state: GameState, control: StrategicControl) -> float:
        """Flat accept threshold: the default until opponents are calibrated."""

        remaining = self._remaining(state)
        base = 0.45
        if control.mode == StrategicMode.EXPLOIT:
            base = 0.43
        elif control.mode == StrategicMode.EXPLORE:
            base = 0.47
        if remaining <= 2:
            base -= 0.05
        return self._clip(base, 0.35, 0.50)

    def _bargaining_empirical_offer_share(self, state: GameState, control: StrategicControl) -> tuple[float, dict[str, Any]] | None:
        if not self.response_model:
            return None
        remaining = self._remaining(state)
        responder = "player_2" if state.role == "player_1" else "player_1"
        mode_cap = {
            StrategicMode.SAFE: 0.58,
            StrategicMode.EXPLORE: 0.62,
            StrategicMode.COMMIT: 0.60,
            StrategicMode.EXPLOIT: 0.68,
        }.get(control.mode, 0.58)
        max_share = min(0.76 if remaining > 2 else 0.56, mode_cap)
        candidates = [round(0.50 + i * 0.02, 2) for i in range(int((max_share - 0.50) / 0.02) + 1)]
        best: tuple[float, float, ResponseEstimate] | None = None
        for self_share in candidates:
            offered_share = 1.0 - self_share
            estimate = self.response_model.bargaining_acceptance(state, responder, offered_share)
            if not estimate or estimate.is_global_fallback:
                continue
            robust_score = (
                self_share * estimate.probability
                - 0.12 * estimate.uncertainty
                - 0.05 * estimate.ood_penalty
                - 0.01 * estimate.fallback_level
            )
            if best is None or robust_score > best[0]:
                best = (robust_score, self_share, estimate)
        if best is None:
            return None
        _, share, estimate = best
        if estimate.support_quality < 0.20 and control.mode != StrategicMode.EXPLORE:
            return None
        return self._clip(share, 0.50, max_share), {
            "family": "bargaining",
            "selected_self_share": share,
            "selected_offered_share": 1.0 - share,
            "acceptance_estimate": estimate.to_dict(),
        }

    def _bargaining_accept_threshold(self, state: GameState, control: StrategicControl) -> float:
        """Accept above our continuation value, not above a flat 0.45.

        Rejecting makes us the proposer next round, so the share we should insist
        on is `delta_us * A(round+1)` -- high when we are patient enough to wait,
        low when waiting costs us. A constant threshold got this backwards in both
        directions: it held out for 0.45 while impatient (walking into a
        no-agreement worth 0) and settled for 0.45 while patient enough to demand
        far more.
        """

        remaining = self._remaining(state)
        if not self.use_theory_anchor:
            return self._bargaining_accept_threshold_flat(state, control)
        floor = control.beliefs.get("spe_accept_floor")
        base = 0.45 if floor is None else float(floor)
        if not control.beliefs.get("delta_other_known", 0.0):
            # Opponent delta was a prior, so pull the floor toward the neutral 0.45.
            base = 0.45 + 0.5 * (base - 0.45)
        if control.mode == StrategicMode.EXPLOIT:
            base += 0.02
        elif control.mode == StrategicMode.EXPLORE:
            base += 0.01
        if remaining <= 1:
            # Final round: the continuation is nothing, so anything positive beats
            # walking away with zero.
            return 0.01
        return self._clip(base, 0.20, 0.70)

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
            empirical = self._negotiation_empirical_offer_price(state, control)
            if empirical:
                normalized_price, empirical_payload = empirical
            else:
                empirical_payload = None
            price = round(normalized_price * order, 2)
            structured = {
                "product_price": price,
                "message": self._negotiation_message(state, control, normalized_price),
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": evidence,
                "beliefs": beliefs,
            }
            if empirical_payload:
                structured["empirical_response_model"] = empirical_payload
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
        """Beliefs about the trade zone, without inventing one.

        Two fixes over the previous version. The hard-coded fallbacks of 0.72
        (seller) and 1.08 (buyer) are replaced by the empirical grid means, both of
        which are above 1.0. And the counterpart value is no longer inferred as
        `max(prior, observed_prices, own_value + 0.12)`: that used the prior and an
        arbitrary +0.12 as *floors*, so as a seller the agent could never believe
        the buyer valued the good below 1.08 and therefore never believed a
        no-trade zone existed -- in 61% of real configs, where one does.

        The replacement is an evidence bound rather than an optimistic floor. A
        buyer offering price `p` reveals their value is at least `p`; a seller
        offering `p` reveals theirs is at most `p`. With no offers observed yet the
        prior stands on its own.
        """

        own_key = "seller_value" if state.role == "seller" else "buyer_value"
        other_key = "buyer_value" if state.role == "seller" else "seller_value"
        own_observed = self._float(state.private_parameters.get(own_key), self._float(state.public_parameters.get(own_key), None))
        other_observed = self._float(state.private_parameters.get(other_key), self._float(state.public_parameters.get(other_key), None))
        counterpart_known = other_observed is not None
        prior = {"seller_value": EMPIRICAL_SELLER_VALUE_MEAN, "buyer_value": EMPIRICAL_BUYER_VALUE_MEAN}
        own_value = own_observed if own_observed is not None else prior[own_key]

        order = self._float(state.public_parameters.get("product_price_order"), 1_000_000.0)
        opponent_prices = [
            self._float(item.get("numeric_action"), None) / order
            for item in self._transcript(state)
            if item.get("action_type") == "offer" and item.get("role") != state.role and item.get("numeric_action") is not None
        ]
        opponent_prices = [price for price in opponent_prices if price is not None]
        concessions = [abs(opponent_prices[i] - opponent_prices[i - 1]) for i in range(1, len(opponent_prices))]
        mean_concession = sum(concessions) / len(concessions) if concessions else 0.0
        rejection_count = sum(
            1
            for item in self._transcript(state)
            if item.get("action_type") == "decision" and item.get("role") != state.role and item.get("accept_reject") == "RejectOffer"
        )

        if counterpart_known:
            other_value = other_observed
        elif opponent_prices:
            # Evidence bound, not a floor: their offers reveal which side of the
            # price their value must lie on.
            other_value = max(opponent_prices) if state.role == "seller" else min(opponent_prices)
        else:
            other_value = prior[other_key]

        seller_value = own_value if state.role == "seller" else other_value
        buyer_value = other_value if state.role == "seller" else own_value
        return {
            "seller_value": seller_value,
            "buyer_value": buyer_value,
            "counterpart_value_known": 1.0 if counterpart_known else 0.0,
            "opponent_concession_rate": self._clip(mean_concession, 0.0, 0.30),
            "opponent_rejection_count": float(rejection_count),
            "surplus_room": self._clip(max(0.0, buyer_value - seller_value), 0.0, 1.0),
            "strategic_delay": self._clip(rejection_count / max(1, self._round(state)), 0.0, 1.0),
        }

    def _negotiation_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {
            "E_concessionary": 1.0 + beliefs["opponent_concession_rate"] * 8.0,
            "E_commitment_sensitive": 1.0 + beliefs["strategic_delay"] * (1.0 if self._round(state) >= 2 else 0.25),
            "E_surplus": 1.0 + min(1.0, beliefs["surplus_room"] * 2.0),
            "E_sample": 1.0 + min(1.0, len(self._transcript(state)) / 8.0),
        }

    def _negotiation_offer_price(self, state: GameState, control: StrategicControl) -> float:
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        remaining = self._remaining(state)
        concession = 0.02 * max(0, self._round(state) - 1)
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

    def _negotiation_empirical_offer_price(self, state: GameState, control: StrategicControl) -> tuple[float, dict[str, Any]] | None:
        if not self.response_model:
            return None
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        if buyer_value <= seller_value:
            return None
        responder = "buyer" if state.role == "seller" else "seller"
        low = seller_value
        high = buyer_value
        step = 0.02
        candidates = [round(low + i * step, 4) for i in range(int((high - low) / step) + 1)]
        candidates.append(high)
        best: tuple[float, float, ResponseEstimate] | None = None
        # Pass our current belief about the responder's value so the model can be
        # queried on the responder's gain rather than on the confounded absolute
        # price. Under complete information this is the true value; otherwise it is
        # the evidence bound from _negotiation_beliefs.
        responder_value = buyer_value if state.role == "seller" else seller_value
        for price in sorted(set(candidates)):
            estimate = self.response_model.negotiation_acceptance(state, responder, price, responder_value)
            if not estimate or estimate.is_global_fallback:
                continue
            payoff_if_accepted = max(0.0, price - seller_value) if state.role == "seller" else max(0.0, buyer_value - price)
            robust_score = (
                payoff_if_accepted * estimate.probability
                - 0.10 * estimate.uncertainty
                - 0.04 * estimate.ood_penalty
                - 0.01 * estimate.fallback_level
            )
            if best is None or robust_score > best[0]:
                best = (robust_score, price, estimate)
        if best is None:
            return None
        _, price, estimate = best
        if estimate.support_quality < 0.08 and control.mode != StrategicMode.EXPLORE:
            return None
        return self._clip(price, low, high), {
            "family": "negotiation",
            "selected_normalized_price": price,
            "responder_role": responder,
            "acceptance_estimate": estimate.to_dict(),
        }

    def _negotiation_outside_option(
        self,
        state: GameState,
        control: StrategicControl,
        normalized_price: float | None,
    ) -> str | None:
        """Take Jhon's deal when no profitable agreement is reachable.

        `SellToJhon` / `BuyFromJhon` transact at the player's own value
        (`final_value = product_price_order * seller_value` upstream), so the
        outside option is worth exactly zero surplus -- the same as running the
        clock out. It is therefore not a way to win more payoff; it is the action
        real players take in 19.2% of negotiation decisions, and 16,003 of those
        are in no-trade-zone configs where they take it 7.6x more often than they
        accept. Without it our action distribution cannot match the population the
        response model and support index are built from.

        Only taken where it is provably not worse than continuing: when the trade
        zone is known to be empty, or in the closing round when nothing on the
        table beats our own value.
        """

        exit_action = "SellToJhon" if state.role == "seller" else "BuyFromJhon"
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        own_value = seller_value if state.role == "seller" else buyer_value
        counterpart_known = bool(control.beliefs.get("counterpart_value_known", 0.0))

        if counterpart_known and buyer_value <= seller_value:
            return exit_action
        if self._remaining(state) <= 1 and normalized_price is not None:
            beats_own_value = normalized_price > own_value if state.role == "seller" else normalized_price < own_value
            if not beats_own_value:
                return exit_action
        return None

    def _negotiation_decision(self, state: GameState, control: StrategicControl, normalized_price: float | None) -> str:
        outside = self._negotiation_outside_option(state, control, normalized_price)
        if outside:
            return outside
        if normalized_price is None:
            return "RejectOffer"
        seller_value = control.beliefs["seller_value"]
        buyer_value = control.beliefs["buyer_value"]
        remaining = self._remaining(state)
        surplus = max(0.0, buyer_value - seller_value)
        margin = 0.025 if remaining > 2 else 0.0
        if control.mode == StrategicMode.EXPLOIT:
            capture_floor = 0.16
        elif control.mode == StrategicMode.COMMIT:
            capture_floor = 0.18
        else:
            capture_floor = 0.22
        if remaining <= 2:
            capture_floor = min(capture_floor, 0.10)
        required_margin = max(margin, surplus * capture_floor)
        if state.role == "seller":
            return "AcceptOffer" if normalized_price >= seller_value + required_margin else "RejectOffer"
        return "AcceptOffer" if normalized_price <= buyer_value - required_margin else "RejectOffer"

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
            shadow = shadow_record(
                self.message_composer,
                decision == "yes",
                market_sold=int(beliefs.get("market_products_sold") or 0),
                market_high_quality=int(beliefs.get("market_high_quality_sold") or 0),
            )
            message = self._persuasion_message(control, decision, quality)
            if self.message_mode == "live":
                shadow["mode"] = "live"
                message = shadow["would_send"]["text"]
            structured = {
                "decision": decision,
                "message": message,
                "message_experiment": shadow,
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": evidence,
                "beliefs": beliefs,
            }
            return self._action(state, "recommendation", structured, buy_no_buy=decision, control=control)

        decision = self._persuasion_buy_decision(state, control)
        structured = {
            "decision": decision,
            "exploration": getattr(self, "_last_exploration", None),
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
        seller_actions = [item for item in self._transcript(state) if item.get("role") == "seller"]
        buyer_actions = [item for item in self._transcript(state) if item.get("role") == "buyer"]
        qualities = {int(item.get("round", 0)): item for item in self._transcript(state) if item.get("action_type") == "nature_quality"}
        truthful = 0
        truth_total = 0
        yes_on_high = 0
        high_total = 0
        yes_on_low = 0
        low_total = 0
        for item in seller_actions:
            rec = transcript_item_decision(item)
            quality = transcript_item_quality(qualities.get(int(item.get("round", 0))))
            if rec in {"yes", "no"} and quality:
                truth_total += 1
                truthful += int((rec == "yes") == (quality == "high-quality"))
                if quality == "high-quality":
                    high_total += 1
                    yes_on_high += int(rec == "yes")
                elif quality == "low-quality":
                    low_total += 1
                    yes_on_low += int(rec == "yes")
        buys_after_yes = 0
        yes_seen = 0
        seller_by_round = {int(item.get("round", 0)): item for item in seller_actions}
        for item in buyer_actions:
            rec = transcript_item_decision(seller_by_round.get(int(item.get("round", 0))))
            if rec == "yes":
                yes_seen += 1
                buys_after_yes += int(transcript_item_decision(item) == "yes")
        honesty = (truthful + 1) / (truth_total + 2)
        yes_given_high = (yes_on_high + 2) / (high_total + 3)
        yes_given_low = (yes_on_low + 1) / (low_total + 3)
        yes_denominator = p * yes_given_high + (1.0 - p) * yes_given_low
        posterior_quality_given_yes = (p * yes_given_high / yes_denominator) if yes_denominator > 0 else p
        obedience = (buys_after_yes + 1) / (yes_seen + 2)

        # A myopic buyer carries no round history -- upstream wipes its chat every
        # round -- and is handed aggregate market statistics instead. Those counts
        # are its only evidence, and the fraction of sold products that turned out
        # high quality is a direct estimate of exactly the quantity the purchase
        # rule needs. Without this the buyer falls back to an uninformative prior in
        # the ~49% of real persuasion games that are myopic.
        stats = next((item for item in self._transcript(state) if item.get("action_type") == "market_statistics"), None)
        market_sold = market_high = 0
        if stats is not None:
            market_sold = int(self._float(stats.get("products_sold"), 0) or 0)
            market_high = int(self._float(stats.get("high_quality_sold"), 0) or 0)
            if market_sold > 0:
                # Laplace-smoothed toward the prior so a single early sale does not
                # swing the posterior to 0 or 1.
                prior_weight = 4.0
                posterior_quality_given_yes = (market_high + prior_weight * p) / (market_sold + prior_weight)
        base_ev = p * (v - 1.0) + (1.0 - p) * (c - 1.0)
        return {
            "base_quality_prob": self._clip(p, 0.0, 1.0),
            "high_value": v,
            "low_value": c,
            "base_expected_value": base_ev,
            "seller_honesty": honesty,
            "yes_given_high": self._clip(yes_given_high, 0.0, 1.0),
            "yes_given_low": self._clip(yes_given_low, 0.0, 1.0),
            "posterior_quality_given_yes": self._clip(posterior_quality_given_yes, 0.0, 1.0),
            "receiver_obedience": obedience,
            "receiver_skepticism": 1.0 - obedience,
            # Kept separate on purpose. `transcript_observations` is the channel a
            # persistent buyer learns through without spending anything; when it is
            # zero the only way to learn is to buy. That distinction is what defines
            # a cold start, and conflating the two either over- or under-triggers
            # exploration.
            "transcript_observations": float(truth_total),
            "evidence_observations": float(truth_total + market_sold),
            "market_products_sold": float(market_sold),
            "market_high_quality_sold": float(market_high),
            "myopic_buyer": 1.0 if stats is not None else 0.0,
        }

    def _persuasion_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {
            "E_receiver_obedient": 1.0 + max(0.0, beliefs["receiver_obedience"] - 0.5) * 4.0,
            "E_receiver_skeptical": 1.0 + max(0.0, beliefs["receiver_skepticism"] - 0.5) * 4.0,
            "E_seller_honest": 1.0 + max(0.0, beliefs["seller_honesty"] - 0.5) * 4.0,
            "E_sample": 1.0 + min(1.0, len(self._transcript(state)) / 20.0),
        }

    def _persuasion_recommendation(self, state: GameState, control: StrategicControl, quality: str) -> str:
        is_high = quality == "high-quality"
        remaining_fraction = self._remaining(state) / self._horizon(state)
        if is_high:
            return "yes"
        if self._persuasion_empirical_low_quality_yes(state, control, quality, remaining_fraction):
            return "yes"
        if (
            control.mode == StrategicMode.EXPLOIT
            and control.evidence.get("E_receiver_obedient", 1.0) >= self.exploit_evidence_threshold
            and remaining_fraction <= 0.35
        ):
            return "yes"
        return "no"

    def _persuasion_empirical_low_quality_yes(
        self,
        state: GameState,
        control: StrategicControl,
        quality: str,
        remaining_fraction: float,
    ) -> bool:
        if not self.response_model or quality != "low-quality":
            return False
        if remaining_fraction > 0.35 or control.mode != StrategicMode.EXPLOIT:
            return False
        yes = self.response_model.persuasion_buy(state, "yes", quality, "I recommend buying this product.")
        no = self.response_model.persuasion_buy(state, "no", quality, "I recommend passing on this product.")
        if not yes or yes.is_global_fallback or yes.support_quality < 0.35:
            return False
        no_probability = no.probability if no else 0.0
        return yes.probability - no_probability >= 0.25

    def _persuasion_explore_buy(self, state: GameState, control: StrategicControl) -> dict[str, Any] | None:
        """Should we buy despite negative expected value, in order to learn?

        There is a cold start in this family. The buyer's posterior only moves once
        it has bought something, so in any configuration whose break-even sits above
        the prior-only posterior of `2p/(1+p)` it declines forever, generates no
        observations, and never discovers whether this particular seller is
        informative. Real sellers are: `P(high | rec=yes)` is 0.7999 across 88,910
        real decisions against 0.5434 unconditional.

        Deliberately stateless. The agent instance is reused across every live game,
        so an exploration counter held on `self` would leak between games; the count
        of purchases so far is read from the recovered market statistics instead.

        Three conditions, all of which have to hold:

        * evidence is still thin -- fewer purchases than the budget;
        * enough of the game remains to exploit what is learned;
        * a single exploratory buy is not catastrophic in this configuration.
        """

        if not self.persuasion_explore:
            return None
        beliefs = control.beliefs
        # A cold start means there is no free channel to learn through. A persistent
        # buyer reads the transcript and learns without spending anything, so paying
        # negative EV there is pure cost -- measured at -0.0018 to -0.0003 across
        # every persistent regime, against +0.039 to +0.041 where the cold start is
        # real. A myopic or live buyer has no transcript at all and can only learn by
        # buying. Gating on the transcript channel specifically, rather than on total
        # evidence, is what separates the two: gating on total evidence caps
        # exploration at a single purchase, which cannot move a smoothed posterior.
        if int(self._float(beliefs.get("transcript_observations"), 0) or 0) > 0:
            return None
        sold = int(self._float(beliefs.get("market_products_sold"), 0) or 0)
        horizon = self._horizon(state)
        round_number = self._round(state)
        # Small and horizon-scaled: two observations in a 20-round game.
        budget = max(1, min(3, horizon // 7))
        if sold >= budget:
            return None
        # Half the game must remain, or there is nothing left to exploit with.
        if round_number > max(1, horizon // 2):
            return None

        high_value = self._float(beliefs.get("high_value"), 1.0) or 1.0
        low_value = self._float(beliefs.get("low_value"), 0.0) or 0.0
        prior = self._float(beliefs.get("base_quality_prob"), 0.5) or 0.5
        blind_ev = prior * (high_value - 1.0) + (1.0 - prior) * (low_value - 1.0)
        if blind_ev < -self.max_exploration_loss:
            # One buy would cost more than the exploration is worth risking.
            return None

        return {
            "reason": "cold_start_information_gathering",
            "observations_so_far": sold,
            "budget": budget,
            "blind_buy_ev": blind_ev,
            "note": "posterior cannot move until at least one purchase is observed",
        }

    def _persuasion_buy_decision(self, state: GameState, control: StrategicControl) -> str:
        # Search back for the seller's action in this round rather than taking the
        # last transcript row. With allow_buyer_message enabled the buyer's own
        # message is the last row, and the blind read misclassified the
        # recommendation as absent (defaulting to "no"). No released config enables
        # that flag, but any extra row -- a nature event, a system note -- breaks
        # the positional assumption the same way.
        recommendation = "no"
        for item in reversed(self._transcript(state)):
            if item.get("role") != "seller":
                continue
            value = transcript_item_decision(item)
            if value in {"yes", "no"}:
                recommendation = value
                break
        if recommendation == "no":
            return "no"
        high_value = control.beliefs["high_value"]
        low_value = control.beliefs["low_value"]
        posterior_quality = control.beliefs.get("posterior_quality_given_yes")
        if posterior_quality is None:
            posterior_quality = 0.66 if control.beliefs.get("seller_honesty", 0.5) >= 0.60 else control.beliefs.get("base_quality_prob", 0.5)
        if high_value <= low_value:
            return "no"
        break_even_quality = self._clip((1.0 - low_value) / (high_value - low_value), 0.0, 1.0)
        sample = control.evidence.get("E_sample", 1.0)
        safety_margin = 0.04 if sample < 1.5 else 0.02
        ev = posterior_quality * (high_value - 1.0) + (1.0 - posterior_quality) * (low_value - 1.0)
        if posterior_quality >= break_even_quality + safety_margin and ev >= 0.02:
            return "yes"
        explore = self._persuasion_explore_buy(state, control)
        if explore is not None:
            self._last_exploration = explore
            return "yes"
        self._last_exploration = None
        return "no"

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
        coverage = self._context_coverage(state, family)
        uncertainty = self._counterfactual_uncertainty(state, beliefs, evidence, coverage)
        expected_gain = self._expected_exploitation_gain(state, family, beliefs, evidence)
        posterior_regret = self._posterior_regret(state, beliefs, evidence)
        extra = {"coverage": coverage, "counterfactual_uncertainty": uncertainty}

        if (
            expected_gain > 0
            and posterior_regret <= self.max_posterior_regret
            and strongest >= self.exploit_evidence_threshold
            and uncertainty <= self.max_counterfactual_uncertainty
        ):
            return StrategicControl(StrategicMode.EXPLOIT, "evidence_gated", expected_gain, posterior_regret, evidence, beliefs, "exploit gate passed", **extra)

        if family == "negotiation" and remaining > 2 and evidence.get("E_commitment_sensitive", 1.0) >= 1.7:
            return StrategicControl(StrategicMode.COMMIT, "commitment_screen", expected_gain, posterior_regret, evidence, beliefs, "commitment sensitivity evidence", **extra)

        if remaining > 2 and strongest >= self.explore_evidence_threshold:
            return StrategicControl(StrategicMode.EXPLORE, "active_information", expected_gain, posterior_regret, evidence, beliefs, "information value remains", **extra)

        reason = "default robust floor"
        if coverage.get("known") and uncertainty > self.max_counterfactual_uncertainty:
            reason = "default robust floor (empirical coverage too thin to escalate)"
        return StrategicControl(StrategicMode.SAFE, "robust_floor", expected_gain, posterior_regret, evidence, beliefs, reason, **extra)

    def _planned_action_type(self, state: GameState) -> str:
        """The action type this turn will produce, known before the value is chosen."""

        if state.game_family == "persuasion":
            return "recommendation" if state.role == "seller" else "buy_decision"
        return "offer" if state.valid_action_schema.get("kind") == "offer" else "decision"

    def _context_coverage(self, state: GameState, family: str) -> dict[str, Any]:
        """How much real data the audit support index holds for this situation."""

        if not self.coverage_gate or not self.coverage_gate.has_index:
            return {"known": False, "reason": "no support index available"}
        support = self.coverage_gate.context_coverage(
            family,
            dict(state.public_parameters),
            state.role,
            self._planned_action_type(state),
            state,
        )
        return {"known": bool(support.get("found")), **support}

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

    def _counterfactual_uncertainty(
        self,
        state: GameState,
        beliefs: dict[str, float],
        evidence: dict[str, float],
        coverage: dict[str, Any] | None = None,
    ) -> float:
        """Uncertainty about what a counterfactual action would have produced.

        The in-game part shrinks as the transcript grows. The empirical part is
        the audit support index: the thinner the real-data coverage for this
        context, the more uncertain any counterfactual claim is, which is what
        keeps `max_counterfactual_uncertainty` from waving through an EXPLOIT
        escalation in a region the dataset never visited. When no support index
        is loaded the empirical term is omitted rather than assumed to be zero
        coverage, so a data-less run is not silently penalized.
        """

        sample_e = evidence.get("E_sample", 1.0)
        base = 0.42 / max(sample_e, 1.0)
        if coverage and coverage.get("known"):
            context_score = float(coverage.get("context_score") or 0.0)
            base += self.coverage_uncertainty_weight * (1.0 - self._clip(context_score, 0.0, 1.0))
        return self._clip(base, 0.05, 0.60)

    def _last_offer(self, state: GameState) -> dict[str, Any]:
        for item in reversed(self._transcript(state)):
            if item.get("action_type") == "offer":
                return item
        return {}

    def _last_numeric(self, state: GameState) -> float | None:
        for item in reversed(self._transcript(state)):
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

    @staticmethod
    def _horizon(state: GameState) -> int:
        """Horizon as a usable positive int.

        A missing or unparseable horizon previously reached `max(1, state.horizon)`
        directly and raised TypeError, killing the whole decision rather than
        degrading. The harness always supplies one; an external one might not.
        """

        value = JordanStrategicAgent._float(getattr(state, "horizon", None), None)
        if value is None or value != value or value < 1:
            return 1
        return int(value)

    @staticmethod
    def _round(state: GameState) -> int:
        """Round number as a usable positive int."""

        value = JordanStrategicAgent._float(getattr(state, "round", None), None)
        if value is None or value != value or value < 1:
            return 1
        return int(value)

    @staticmethod
    def _transcript(state: GameState) -> list[dict[str, Any]]:
        """Transcript with non-dict entries dropped.

        A single `None` row used to raise AttributeError on the first `.get`.
        """

        items = getattr(state, "visible_transcript", None) or []
        return [item for item in items if isinstance(item, dict)]

    def _remaining(self, state: GameState) -> int:
        return max(1, self._horizon(state) - self._round(state) + 1)

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
        candidate = {
            "action_type": action_type,
            "numeric_action": numeric,
            "structured": structured,
            "accept_reject": accept_reject,
            "buy_no_buy": buy_no_buy,
        }
        support = self._review_action_support(state, candidate)
        if support:
            structured["action_support"] = support
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

    def _review_action_support(self, state: GameState, candidate: dict[str, Any]) -> dict[str, Any] | None:
        """Score the committed action against the support index, and escalate if needed.

        This is the decision point the `counterfactual` trigger exists for: the
        agent has settled on a concrete action and is about to play it. If that
        action falls outside the empirical support the audit measured, the gate is
        asked for a targeted counterfactual simulation. The gate owns
        deduplication, the per-run dispatch budget, and re-entrancy, so this call
        is safe to make on every decision.
        """

        if not self.coverage_gate or not self.coverage_gate.has_index:
            return None
        verdict = self.coverage_gate.evaluate(
            state.game_family,
            dict(state.public_parameters),
            state.role,
            candidate,
            state,
        )
        payload = verdict.to_dict()
        if not verdict.inside_support:
            request = self.coverage_gate.request_counterfactual(
                state.game_family,
                dict(state.public_parameters),
                state.role,
                candidate,
                state,
                verdict=verdict,
            )
            payload["counterfactual_request"] = request.get("status")
        return payload

    @staticmethod
    def _control_payload(control: StrategicControl) -> dict[str, Any]:
        return {
            "mode": control.mode.value,
            "submode": control.submode,
            "expected_gain": control.expected_gain,
            "posterior_regret": control.posterior_regret,
            "reason": control.reason,
            "coverage": control.coverage,
            "counterfactual_uncertainty": control.counterfactual_uncertainty,
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
