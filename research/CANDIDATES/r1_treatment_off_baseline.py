"""R1's isolated economic core and four thin factorial wrappers.

The baseline deliberately contains no e-process or language mechanism.  The two
orthogonal flags are interface pins for later arms; toggling either flag without
an installed treatment cannot change the economic action or its rendering.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
from typing import Any

from glee_eval.data.schemas import AgentAction, GameState
from glee_eval.response_models.runtime import EmpiricalResponseModel
from glee_eval.simulate.coverage_gate import CoverageGate
from my_agents.jordan_strategic import JordanStrategicAgent, StrategicControl, StrategicMode


BOUND_COMMIT = "895ffee341cd4893373e32d5f8c1a5375549e0e6"
FACTORIAL_SLOTS = ("00", "10", "01", "11")
_FAMILIES = ("bargaining", "negotiation", "persuasion")


def _verified_json(
    path: str | Path | None,
    expected_sha256: str | None,
    filename: str,
) -> tuple[dict[str, Any] | None, dict[str, str | None]]:
    """Load external baseline state only when its exact bytes are declared."""

    if path is None:
        if expected_sha256 is not None:
            raise ValueError(f"{filename} sha256 was supplied without a path")
        return None, {"path": None, "sha256": None}
    if expected_sha256 is None:
        raise ValueError(f"{filename} requires an expected sha256")
    expected = str(expected_sha256).strip().lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError(f"{filename} expected sha256 must be 64 lowercase hex characters")

    resolved = Path(path)
    if resolved.is_dir():
        resolved = resolved / filename
    raw = resolved.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError(f"{filename} sha256 mismatch: expected {expected}, found {actual}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{filename} must contain a JSON object")
    return payload, {"path": str(resolved.resolve()), "sha256": actual}


def _validate_response_model(payload: dict[str, Any]) -> None:
    """Small runtime verifier for the response artifact surface this core uses."""

    if int(payload.get("version", -1)) != 1:
        raise ValueError("response model version must be 1")
    families = payload.get("families")
    if not isinstance(families, dict) or any(family not in families for family in _FAMILIES):
        raise ValueError("response model must contain all three families")
    for family in _FAMILIES:
        family_model = families[family]
        if not isinstance(family_model, dict) or not isinstance(family_model.get("buckets"), dict):
            raise ValueError(f"response model {family} buckets must be an object")
        global_rate = family_model.get("global_rate")
        if global_rate is not None and (not math.isfinite(float(global_rate)) or not 0.0 <= float(global_rate) <= 1.0):
            raise ValueError(f"response model {family} global_rate is invalid")
        for key, row in family_model["buckets"].items():
            if not isinstance(key, str) or not isinstance(row, dict):
                raise ValueError(f"response model {family} has an invalid bucket")
            probability = float(row.get("probability"))
            uncertainty = float(row.get("uncertainty"))
            support_quality = float(row.get("support_quality"))
            trials = int(row.get("trials"))
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ValueError(f"response model {family} bucket probability is invalid")
            if not math.isfinite(uncertainty) or uncertainty < 0.0:
                raise ValueError(f"response model {family} bucket uncertainty is invalid")
            if not math.isfinite(support_quality) or not 0.0 <= support_quality <= 1.0:
                raise ValueError(f"response model {family} bucket support_quality is invalid")
            if trials < 0:
                raise ValueError(f"response model {family} bucket trials is invalid")


def _validate_support_index(payload: dict[str, Any]) -> None:
    """Verify the frozen coverage artifact before it can influence control."""

    if int(payload.get("schema_version", -1)) != 1:
        raise ValueError("support index schema_version must be 1")
    buckets = payload.get("buckets")
    if not isinstance(buckets, dict):
        raise ValueError("support index buckets must be an object")
    if int(payload.get("bucket_count", -1)) != len(buckets):
        raise ValueError("support index bucket_count does not match buckets")
    for key, row in buckets.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            raise ValueError("support index contains an invalid bucket")
        if int(row.get("total_observations", -1)) < 0:
            raise ValueError(f"support index bucket {key} has invalid observations")
        counts = row.get("action_counts")
        if not isinstance(counts, dict) or any(int(value) < 0 for value in counts.values()):
            raise ValueError(f"support index bucket {key} has invalid action counts")
        density = float(row.get("density", -1.0))
        occupied = int(row.get("occupied_bins", -1))
        total_bins = int(row.get("total_bins", 0))
        expected_density = occupied / total_bins if total_bins > 0 else -1.0
        if (
            not math.isfinite(density)
            or density < 0.0
            or occupied < 0
            or total_bins <= 0
            or not math.isclose(density, expected_density, rel_tol=0.0, abs_tol=1e-15)
        ):
            raise ValueError(f"support index bucket {key} has invalid density")


class TreatmentOffEconomicCore(JordanStrategicAgent):
    """Theory/residual economic policy with treatment control held neutral.

    The inherited family mechanics retain the shipped bargaining SPE anchor,
    negotiation surplus/screening logic, persuasion Bayesian beliefs, response
    residual routing, support review, and schema-safe action construction.  This
    class removes only heuristic evidence-mode selection, shadow language
    generation, ambient artifact loading, and default-off experimental flags.
    """

    agent_id = "r1_treatment_off_economic_core_v1"

    def __init__(
        self,
        seed: int = 0,
        *,
        use_eprocess: bool = False,
        use_language: bool = False,
        response_model_path: str | Path | None = None,
        response_model_sha256: str | None = None,
        support_index_path: str | Path | None = None,
        support_index_sha256: str | None = None,
    ):
        # A child of this source file cannot exist because this path is a file,
        # not a directory.  Passing it prevents the parent from consulting ambient
        # GLEE_* environment variables before verified artifacts are installed.
        ambient_blocker = str(Path(__file__) / "r1_ambient_artifacts_disabled")
        super().__init__(
            seed=seed,
            response_model_path=ambient_blocker,
            support_index_path=ambient_blocker,
            use_theory_anchor=True,
            message_mode="off",
            persuasion_explore=False,
            use_persuasion_platt=False,
            use_deceptive_seller_guard=False,
            use_persuasion_text_stance=False,
            use_time_concession=False,
            guarantee_own_margin=False,
            debias_counterpart_value=False,
            use_unknown_horizon_counter_fallback=False,
            use_unknown_horizon_counter_preservation=False,
        )
        self.use_eprocess = bool(use_eprocess)
        self.use_language = bool(use_language)

        response_payload, self.response_model_provenance = _verified_json(
            response_model_path, response_model_sha256, "model.json"
        )
        if response_payload is not None:
            _validate_response_model(response_payload)
            self.response_model = EmpiricalResponseModel(response_payload)
        else:
            self.response_model = None

        support_payload, self.support_index_provenance = _verified_json(
            support_index_path, support_index_sha256, "support_index.json"
        )
        if support_payload is not None:
            _validate_support_index(support_payload)
        self.coverage_gate = CoverageGate(support_payload) if support_payload is not None else None

        # The treatment-off baseline neither generates nor stores a shadow
        # language candidate.  Required economic messages are rendered directly
        # by the inherited family templates.
        del self.message_composer

    # Heuristic E_* multipliers are absent, rather than merely assigned thresholds
    # that an adversarial value might cross.
    def _bargaining_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {}

    def _negotiation_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {}

    def _persuasion_evidence(self, state: GameState, beliefs: dict[str, float]) -> dict[str, float]:
        return {}

    def _control(
        self,
        state: GameState,
        beliefs: dict[str, float],
        evidence: dict[str, float],
        family: str,
    ) -> StrategicControl:
        coverage = self._context_coverage(state, family)
        return StrategicControl(
            mode=StrategicMode.SAFE,
            submode="treatment_off_economic_core",
            expected_gain=0.0,
            posterior_regret=0.0,
            evidence={},
            beliefs=beliefs,
            reason="neutral treatment-off control",
            coverage=coverage,
            counterfactual_uncertainty=None,
        )

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
        clean = dict(structured)
        clean["evidence"] = {}

        # A production negotiation rejection requires a counter price.  Put the
        # neutral economic core's own next offer into AgentAction before support
        # review so production consumes the agent output instead of inventing an
        # adapter fallback; the offline hidden-horizon path reads the same field.
        if (
            state.game_family == "negotiation"
            and action_type == "decision"
            and accept_reject == "RejectOffer"
            and clean.get("counter_price") is None
        ):
            order = self._float(state.public_parameters.get("product_price_order"), 1_000_000.0)
            counter = self._negotiation_offer_price(state, control)
            empirical = self._negotiation_empirical_offer_price(state, control)
            if empirical:
                counter, clean["empirical_response_model"] = empirical
            clean["counter_price"] = round(counter * order, 2)
            clean["counter_normalized_price"] = counter

        return super()._action(
            state,
            action_type,
            clean,
            numeric=numeric,
            message=message,
            accept_reject=accept_reject,
            buy_no_buy=buy_no_buy,
            control=control,
        )

    def _persuasion(self, state: GameState) -> AgentAction:
        """Parent Bayesian policy without shadow/live language generation."""

        beliefs = self._persuasion_beliefs(state)
        control = self._control(state, beliefs, {}, "persuasion")
        if state.role == "seller":
            quality = state.metadata.get("quality")
            if quality is None:
                quality = "high-quality" if beliefs.get("base_quality_prob", 0.5) >= 0.5 else "low-quality"
            decision = self._persuasion_recommendation(state, control, quality)
            message = self._persuasion_message(control, decision, quality)
            structured = {
                "decision": decision,
                "message": message,
                "strategic_mode": control.mode.value,
                "submode": control.submode,
                "evidence": {},
                "beliefs": beliefs,
            }
            return self._action(
                state,
                "recommendation",
                structured,
                buy_no_buy=decision,
                control=control,
            )

        decision = self._persuasion_buy_decision(state, control)
        structured = {
            "decision": decision,
            "exploration": getattr(self, "_last_exploration", None),
            "strategic_mode": control.mode.value,
            "submode": control.submode,
            "evidence": {},
            "beliefs": beliefs,
        }
        return self._action(
            state,
            "buy_decision",
            structured,
            buy_no_buy=decision,
            control=control,
        )


class Factorial00Wrapper(TreatmentOffEconomicCore):
    factorial_slot = "00"

    def __init__(self, seed: int = 0, **kwargs: Any):
        if "use_eprocess" in kwargs or "use_language" in kwargs:
            raise TypeError("00 wrapper fixes both treatment flags off")
        super().__init__(seed=seed, use_eprocess=False, use_language=False, **kwargs)


class Factorial10Wrapper(TreatmentOffEconomicCore):
    factorial_slot = "10"

    def __init__(self, seed: int = 0, *, use_eprocess: bool = False, **kwargs: Any):
        if "use_language" in kwargs:
            raise TypeError("10 wrapper fixes language off")
        super().__init__(seed=seed, use_eprocess=use_eprocess, use_language=False, **kwargs)


class Factorial01Wrapper(TreatmentOffEconomicCore):
    factorial_slot = "01"

    def __init__(self, seed: int = 0, *, use_language: bool = False, **kwargs: Any):
        if "use_eprocess" in kwargs:
            raise TypeError("01 wrapper fixes e-process off")
        super().__init__(seed=seed, use_eprocess=False, use_language=use_language, **kwargs)


class Factorial11Wrapper(TreatmentOffEconomicCore):
    factorial_slot = "11"


TREATMENT_OFF_WRAPPERS = {
    "00": Factorial00Wrapper,
    "10": Factorial10Wrapper,
    "01": Factorial01Wrapper,
    "11": Factorial11Wrapper,
}
