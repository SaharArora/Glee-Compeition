"""Wave 3's four real 2x2 research agents.

The implementation composes one economic core with two orthogonal treatment
objects.  It is research-only and does not authorize a payoff or live run.
"""

from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any

from glee_eval.data.schemas import AgentAction, GameState, compact_id
from glee_eval.experiments.factorial import (
    ArmContext,
    CandidateRandomness,
    RandomStreamCapability,
)
from glee_eval.response_models.runtime import EmpiricalResponseModel, ResponseEstimate
from research.CANDIDATES.r1_treatment_off_baseline import TreatmentOffEconomicCore


WAVE3_BASE_COMMIT = "fd05023de6ef87bb9d9e8f0f20044052569041b6"
EPROCESS_THRESHOLD = 20.0
EPROCESS_ALPHA = 0.05
EPROCESS_ALTERNATIVE_WEIGHT = 0.5
EPROCESS_REFERENCE_EPSILON = 0.01
EPROCESS_MIN_SUPPORT_QUALITY = 0.5
FACTORIAL_BASELINE_CONFIGURATION = {
    "economic_core": "TreatmentOffEconomicCore",
    "strategic_mode": "SAFE",
    "use_theory_anchor": True,
    "message_mode": "off",
    "persuasion_explore": False,
    "use_persuasion_platt": False,
    "use_deceptive_seller_guard": False,
    "use_persuasion_text_stance": False,
    "use_time_concession": False,
    "guarantee_own_margin": False,
    "debias_counterpart_value": False,
    "use_unknown_horizon_counter_fallback": False,
    "use_unknown_horizon_counter_preservation": False,
    "historical_evidence_controller": False,
}
FACTORIAL_RECEIVER_CONTRACT = {
    "schema": "glee.research.receiver_capability.v1",
    "environment_id": "glee.offline.rule_based_text_blind.v1",
    "candidate_text_delivered": True,
    "receiver_consumes_candidate_text": False,
}


def _derived_seed(seed: int, stream: str) -> int:
    raw = f"glee.wave3.standalone.v1|{int(seed)}|{stream}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") & ((1 << 63) - 1)


def _standalone_randomness(seed: int, *, use_eprocess: bool, use_language: bool) -> CandidateRandomness:
    return CandidateRandomness(
        scenario_id=f"standalone:{int(seed)}",
        economic_seed=_derived_seed(seed, "economic"),
        eprocess_seed=_derived_seed(seed, "eprocess"),
        language_seed=_derived_seed(seed, "language"),
        use_eprocess=use_eprocess,
        use_language=use_language,
    )


@dataclass(frozen=True)
class EProcessUpdate:
    event_id: str
    game_id: str
    round: int
    observed: int
    recommendation: str
    buyer_decision: str
    reference_buy_probability: float
    null_follow_probability: float
    alternative_follow_probability: float
    factor: float
    evalue_before: float
    evalue_after: float
    reference_key: str
    reference_support: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class EProcessController:
    """Reference-relative persuasion-seller obedience e-process.

    This is a formal e-process only under the declared fixed Model-C null:
    at every included opportunity the conditional probability that the buyer
    follows the seller's recommendation is no greater than the hash-locked
    reference probability.  It is not a distribution-free claim that this null
    describes real opponents.

    Bargaining and negotiation acceptances are terminal-censored at the next
    candidate callback, and a persuasion buyer would be monitoring its own
    action.  Those family/role cells are explicitly unsupported rather than
    filled with historical ``E_*`` heuristics.
    """

    schema = "glee.eprocess.reference_obedience.v1"

    def __init__(
        self,
        stream: RandomStreamCapability,
        *,
        threshold: float = EPROCESS_THRESHOLD,
    ) -> None:
        if stream.owner != "eprocess_treatment" or stream.name != "eprocess":
            raise ValueError("EProcessController requires the eprocess treatment capability")
        if not math.isfinite(float(threshold)) or float(threshold) <= 1.0:
            raise ValueError("e-process threshold must be finite and greater than one")
        self._stream = stream
        self.threshold = float(threshold)
        self.game_id: str | None = None
        self.evalue = 1.0
        self.processed: set[str] = set()
        self.trace: list[EProcessUpdate] = []
        self.crossing: dict[str, Any] | None = None
        self.status = "not_updated"

    def reset(self, game_id: str) -> None:
        self.game_id = str(game_id)
        self.evalue = 1.0
        self.processed = set()
        self.trace = []
        self.crossing = None
        self.status = "reset"

    @staticmethod
    def supported_scope(state: GameState) -> tuple[bool, str]:
        if state.game_family in {"bargaining", "negotiation"}:
            return False, "terminal_acceptance_not_visible_before_next_acting_callback"
        if state.game_family != "persuasion":
            return False, "unknown_family"
        if state.role != "seller":
            return False, "buyer_role_would_monitor_its_own_purchase_action"
        return True, "persuasion_seller_buyer_obedience"

    @staticmethod
    def _decision(item: dict[str, Any]) -> str | None:
        value = item.get("buy_no_buy")
        if value is None:
            value = (item.get("structured") or {}).get("decision")
        text = str(value or "").strip().lower()
        return text if text in {"yes", "no"} else None

    @staticmethod
    def _quality(item: dict[str, Any] | None) -> str | None:
        if not item:
            return None
        value = item.get("quality") or (item.get("structured") or {}).get("quality")
        text = str(value or "").strip().lower()
        if text in {"high-quality", "low-quality"}:
            return text
        return None

    @staticmethod
    def _eligible_estimate(estimate: ResponseEstimate | None, model: EmpiricalResponseModel) -> bool:
        return bool(
            estimate is not None
            and not estimate.is_global_fallback
            and estimate.support >= model.min_support
            and estimate.support_quality >= EPROCESS_MIN_SUPPORT_QUALITY
            and EPROCESS_REFERENCE_EPSILON
            <= estimate.probability
            <= 1.0 - EPROCESS_REFERENCE_EPSILON
        )

    def update_from_state(
        self,
        state: GameState,
        response_model: EmpiricalResponseModel | None,
    ) -> dict[str, Any]:
        if self.game_id != state.game_id:
            self.reset(state.game_id)

        supported, scope = self.supported_scope(state)
        if not supported:
            self.status = f"unsupported:{scope}"
            return self.snapshot()
        if response_model is None:
            self.status = "unsupported:missing_hash_locked_model_c_reference"
            return self.snapshot()

        transcript = [item for item in state.visible_transcript if isinstance(item, dict)]
        nature = {
            int(item.get("round", 0)): item
            for item in transcript
            if item.get("action_type") == "nature_quality"
        }
        sellers = {
            int(item.get("round", 0)): item
            for item in transcript
            if item.get("role") == "seller"
        }
        buyers = {
            int(item.get("round", 0)): item
            for item in transcript
            if item.get("role") == "buyer"
        }

        updates = 0
        for round_number in sorted(set(sellers) & set(buyers)):
            if round_number >= int(state.round):
                continue
            seller = sellers[round_number]
            buyer = buyers[round_number]
            recommendation = self._decision(seller)
            buyer_decision = self._decision(buyer)
            quality = self._quality(nature.get(round_number))
            if recommendation is None or buyer_decision is None:
                continue
            event_id = f"{state.game_id}:persuasion_seller_obedience:{round_number}"
            if event_id in self.processed:
                continue

            prefix = [
                copy.deepcopy(item)
                for item in transcript
                if int(item.get("round", 0) or 0) <= round_number
                and item is not buyer
            ]
            historical_state = replace(
                state,
                round=round_number,
                visible_transcript=prefix,
            )
            message = seller.get("message") or seller.get("free_text_message")
            if message is None:
                message = (seller.get("structured") or {}).get("message")
            estimate = response_model.persuasion_buy(
                historical_state,
                recommendation,
                quality,
                str(message) if message is not None else None,
            )
            self.processed.add(event_id)
            if not self._eligible_estimate(estimate, response_model):
                self.status = "supported:no_eligible_reference_bucket"
                continue
            assert estimate is not None
            p_buy = float(estimate.probability)
            p0 = p_buy if recommendation == "yes" else 1.0 - p_buy
            observed = int(buyer_decision == recommendation)
            q = p0 + EPROCESS_ALTERNATIVE_WEIGHT * (1.0 - p0)
            factor = q / p0 if observed else (1.0 - q) / (1.0 - p0)
            before = self.evalue
            self.evalue *= factor
            update = EProcessUpdate(
                event_id=event_id,
                game_id=state.game_id,
                round=round_number,
                observed=observed,
                recommendation=recommendation,
                buyer_decision=buyer_decision,
                reference_buy_probability=p_buy,
                null_follow_probability=p0,
                alternative_follow_probability=q,
                factor=factor,
                evalue_before=before,
                evalue_after=self.evalue,
                reference_key=estimate.key,
                reference_support=estimate.support,
            )
            self.trace.append(update)
            updates += 1
            if self.crossing is None and self.evalue >= self.threshold:
                self.crossing = {
                    "event_id": event_id,
                    "round": round_number,
                    "evalue": self.evalue,
                    "threshold": self.threshold,
                }

        self.status = "supported:updated" if updates else "supported:no_new_event"
        return self.snapshot()

    @property
    def crossed(self) -> bool:
        return self.crossing is not None

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "game_id": self.game_id,
            "status": self.status,
            "scope": "persuasion seller; buyer follows prior recommendation",
            "null": "P(follow_t=1 | F_{t-1}) <= fixed hash-locked Model-C reference p0_t",
            "alternative": "q_t = p0_t + 0.5 * (1 - p0_t)",
            "threshold": self.threshold,
            "alpha_if_null_holds_for_this_single_game_stream": 1.0 / self.threshold,
            "evalue": self.evalue,
            "crossed": self.crossed,
            "crossing": copy.deepcopy(self.crossing),
            "updates": len(self.trace),
            "trace": [item.to_dict() for item in self.trace],
            "multiplicity": "one persuasion-seller stream per game; no across-game guarantee",
            "unsupported": {
                "bargaining": "terminal acceptance not observed before another acting callback",
                "negotiation": "terminal acceptance not observed before another acting callback",
                "persuasion_buyer": "would monitor the candidate's own buy decision",
                "continuous_offers": "no formal channel; historical E_* scores prohibited",
            },
        }


class FrozenPersuasionLanguagePolicy:
    """Fixed template policy for text-enabled persuasion seller turns only."""

    schema = "glee.language.persuasion_templates.v1"
    _YES = (
        ("confident", "yes_confident_v1", "I am confident this product is worth buying."),
        (
            "social_proof",
            "yes_social_proof_v1",
            "Buyers often value products like this; I recommend buying.",
        ),
    )
    _NO = (
        (
            "counter_interest_credibility",
            "no_counter_interest_v1",
            "Even though I benefit from a sale, I recommend passing on this product.",
        ),
        ("neutral_control", "no_neutral_v1", "My recommendation is to pass on this product."),
    )

    def __init__(self, stream: RandomStreamCapability) -> None:
        if stream.owner != "language_treatment" or stream.name != "language":
            raise ValueError("language policy requires the language treatment capability")
        self._stream = stream

    @staticmethod
    def eligible(state: GameState, action: AgentAction) -> bool:
        return bool(
            state.game_family == "persuasion"
            and state.role == "seller"
            and str(state.public_parameters.get("seller_message_type") or "") == "text"
            and action.buy_no_buy in {"yes", "no"}
        )

    def apply(self, state: GameState, action: AgentAction) -> AgentAction:
        if not self.eligible(state, action):
            return action
        candidates = self._YES if action.buy_no_buy == "yes" else self._NO
        mechanism, template_id, text = self._stream.choice(candidates)
        structured = copy.deepcopy(action.structured)
        structured["message"] = text
        structured["language_treatment"] = {
            "schema": self.schema,
            "eligible": True,
            "mechanism": mechanism,
            "template_id": template_id,
            "historical_association_is_causal_claim": False,
        }
        return replace(action, raw_text=text, message=text, structured=structured)


class Wave3FactorialAgent(TreatmentOffEconomicCore):
    """Shared economic core composed with the two Wave 3 treatments."""

    agent_id = "wave3_factorial_shared_core"
    forced_eprocess: bool
    forced_language: bool

    def __init__(
        self,
        seed: int = 0,
        *,
        arm_context: ArmContext | None = None,
        _forced_eprocess: bool,
        _forced_language: bool,
        **kwargs: Any,
    ) -> None:
        if arm_context is not None and (
            arm_context.use_eprocess != _forced_eprocess
            or arm_context.use_language != _forced_language
        ):
            raise ValueError("arm context treatment flags do not match forced entrypoint")
        randomness = (
            arm_context.randomness
            if arm_context is not None
            else _standalone_randomness(
                seed,
                use_eprocess=_forced_eprocess,
                use_language=_forced_language,
            )
        )
        economic_stream = randomness.claim("economic_policy")
        self._economic_stream = economic_stream
        super().__init__(
            seed=economic_stream.seed,
            use_eprocess=_forced_eprocess,
            use_language=_forced_language,
            **kwargs,
        )
        if self.response_model_provenance.get("sha256") is None:
            raise ValueError("factorial arms require a frozen hash-verified Model-C artifact")
        if self.support_index_provenance.get("sha256") is None:
            raise ValueError("factorial arms require a frozen hash-verified support index")
        self._factorial_artifact_provenance = {
            "schema": "glee.research.factorial_baseline_artifacts.v1",
            "response_model": copy.deepcopy(self.response_model_provenance),
            "support_index": copy.deepcopy(self.support_index_provenance),
            "baseline_configuration": copy.deepcopy(FACTORIAL_BASELINE_CONFIGURATION),
            "receiver_contract": copy.deepcopy(FACTORIAL_RECEIVER_CONTRACT),
        }
        self.forced_eprocess = bool(_forced_eprocess)
        self.forced_language = bool(_forced_language)
        self.randomness = randomness
        self.eprocess_controller = (
            EProcessController(randomness.claim("eprocess_treatment"))
            if self.forced_eprocess
            else None
        )
        self.language_policy = (
            FrozenPersuasionLanguagePolicy(randomness.claim("language_treatment"))
            if self.forced_language
            else None
        )

    def _apply_eprocess(self, state: GameState, action: AgentAction) -> AgentAction:
        if self.eprocess_controller is None:
            return action
        report = self.eprocess_controller.update_from_state(state, self.response_model)
        structured = copy.deepcopy(action.structured)
        structured["eprocess_treatment"] = report
        changed = False
        if (
            self.eprocess_controller.crossed
            and state.game_family == "persuasion"
            and state.role == "seller"
            and action.buy_no_buy == "no"
        ):
            changed = True
            text = self._persuasion_message(
                self._control(state, dict(structured.get("beliefs") or {}), {}, "persuasion"),
                "yes",
                str(state.metadata.get("quality") or "unknown"),
            )
            structured["decision"] = "yes"
            structured["message"] = text
            structured["eprocess_treatment"]["economic_override"] = "recommend_yes_after_crossing"
            action = replace(
                action,
                action_id=compact_id(state.game_id, state.round, state.role, "eprocess_yes"),
                raw_text=text,
                message=text,
                buy_no_buy="yes",
                structured=structured,
            )
        if not changed:
            structured["eprocess_treatment"]["economic_override"] = None
            action = replace(action, structured=structured)
        return action

    def decide(self, state: GameState) -> AgentAction:
        baseline = super().decide(state)
        economic = self._apply_eprocess(state, baseline)
        if self.language_policy is None:
            return economic
        return self.language_policy.apply(state, economic)

    def factorial_randomness_audit(self) -> dict[str, Any]:
        return self.randomness.audit()

    def factorial_artifact_provenance(self) -> dict[str, Any]:
        return copy.deepcopy(self._factorial_artifact_provenance)

    def factorial_capability_bindings(self) -> dict[str, RandomStreamCapability]:
        bindings = {"economic_policy": self._economic_stream}
        if self.eprocess_controller is not None:
            bindings["eprocess_treatment"] = self.eprocess_controller._stream
        if self.language_policy is not None:
            bindings["language_treatment"] = self.language_policy._stream
        return bindings


class Factorial00Agent(Wave3FactorialAgent):
    def __init__(self, seed: int = 0, **kwargs: Any) -> None:
        if "use_eprocess" in kwargs or "use_language" in kwargs:
            raise TypeError("Factorial00Agent fixes e-process=false, language=false")
        super().__init__(
            seed,
            _forced_eprocess=False,
            _forced_language=False,
            **kwargs,
        )


class Factorial10Agent(Wave3FactorialAgent):
    def __init__(self, seed: int = 0, **kwargs: Any) -> None:
        if "use_eprocess" in kwargs or "use_language" in kwargs:
            raise TypeError("Factorial10Agent fixes e-process=true, language=false")
        super().__init__(
            seed,
            _forced_eprocess=True,
            _forced_language=False,
            **kwargs,
        )


class Factorial01Agent(Wave3FactorialAgent):
    def __init__(self, seed: int = 0, **kwargs: Any) -> None:
        if "use_eprocess" in kwargs or "use_language" in kwargs:
            raise TypeError("Factorial01Agent fixes e-process=false, language=true")
        super().__init__(
            seed,
            _forced_eprocess=False,
            _forced_language=True,
            **kwargs,
        )


class Factorial11Agent(Wave3FactorialAgent):
    def __init__(self, seed: int = 0, **kwargs: Any) -> None:
        if "use_eprocess" in kwargs or "use_language" in kwargs:
            raise TypeError("Factorial11Agent fixes e-process=true, language=true")
        super().__init__(
            seed,
            _forced_eprocess=True,
            _forced_language=True,
            **kwargs,
        )


FACTORIAL_AGENTS = {
    "e0_l0": Factorial00Agent,
    "e0_l1": Factorial01Agent,
    "e1_l0": Factorial10Agent,
    "e1_l1": Factorial11Agent,
}
