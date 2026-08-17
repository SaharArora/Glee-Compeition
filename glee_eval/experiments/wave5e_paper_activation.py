"""Outcome-blind Wave 5E paper activation arithmetic and recommendation."""

from __future__ import annotations

import json
from typing import Any

from glee_eval.experiments.receiver_itt import RECEIVER_FAILURE_ITT_RULE_SHA256
from glee_eval.experiments.wave5d_paper_design import (
    DESIGNS,
    design_envelope,
    effective_sample_size,
    minimum_detectable_effect,
)


CENTRAL_SD = 0.20
CENTRAL_ICC = 0.50
CENTRAL_INFORMATION_LOSS = 0.10
SESOI = 0.035
A300_HOLM3_MDE = 0.03410622955037141
FULL_GLEE_DILUTION = 1.0 / 6.0
WALL_CAP_HOURS = 32


def _conditional_effects(effect: float) -> dict[str, float]:
    return {
        f"{frequency:.2f}": effect / frequency
        for frequency in (0.05, 0.10, 0.20, 0.25, 0.50, 1.00)
    }


def activation_evidence() -> dict[str, Any]:
    central_mdes: dict[str, dict[str, float]] = {}
    for design in DESIGNS:
        effective_n = effective_sample_size(
            clusters=design.base_strata_per_family,
            replicates=design.receiver_replicates,
            intraclass_correlation=CENTRAL_ICC,
            information_loss=CENTRAL_INFORMATION_LOSS,
        )
        central_mdes[design.design_id] = {
            "effective_n": effective_n,
            "single_primary_mde": minimum_detectable_effect(
                contrast_sd=CENTRAL_SD, effective_n=effective_n, hypotheses=1
            ),
            "three_hypothesis_holm_first_step_mde": minimum_detectable_effect(
                contrast_sd=CENTRAL_SD, effective_n=effective_n, hypotheses=3
            ),
        }
    a300 = design_envelope(DESIGNS[0])
    retry_seconds = a300["idealized_receiver_service_time"]["seconds_by_attempt_latency"]["30"]
    retry_cap_seconds = int(retry_seconds["retry_cap_seconds"])
    wall_seconds = WALL_CAP_HOURS * 60 * 60
    return {
        "schema": "glee.research.wave5e.paper_activation.v1",
        "evidence_class": "prospective_preoutcome_contract_and_non_treatment_mechanics_only",
        "design": {
            "recommendation": "A300_reordered_language_primary_eprocess_and_interaction_secondary",
            "base_strata_per_family": 300,
            "roles_per_family": 2,
            "receiver_replicates": 2,
            "paired_rows": 3600,
            "independent_cluster": "family_x_base_stratum",
            "primary_independent_clusters_max": 300,
            "production_pins_set": False,
        },
        "estimand_order": {
            "single_confirmatory_primary": "language_main_effect_on_preoutcome_language_eligible_rows",
            "key_secondary": [
                "eprocess_main_effect_on_preoutcome_eprocess_eligible_rows",
                "interaction_on_preoutcome_joint_eligible_rows",
            ],
            "mandatory_secondary": [
                "equal_family_all_row_contrasts",
                "negative_controls",
                "family_role_configuration_cells",
                "receiver_failure_and_action_change_diagnostics",
            ],
            "reason": (
                "language is delivered on every round of every eligible 20-round episode, while "
                "e-process threshold crossing and economic action change are prospectively unknown "
                "and can be rare; three-way Holm allocation spends scarce precision on two mechanistic endpoints"
            ),
        },
        "sesoi": {
            "normalized_payoff": SESOI,
            "origin": "prospective scientific/resource judgment_not_competition_gate",
            "justification": (
                "0.035 is the smallest eligible-population mean change judged worth 48,000 "
                "confirmatory receiver requests, roughly $203 nominal primary-receiver spend, "
                "and a multi-day attended execution envelope"
            ),
            "a300_single_primary_mde": central_mdes["A300"]["single_primary_mde"],
            "a300_holm3_mde": central_mdes["A300"]["three_hypothesis_holm_first_step_mde"],
            "a200_single_primary_mde": central_mdes["A200"]["single_primary_mde"],
            "decision": "A300_can_target_SESOI;A200_and_smaller_cannot_under_central_assumptions",
            "competition_gate_0_010_reused": False,
        },
        "mde_translation": {
            "central_a300_normalized": A300_HOLM3_MDE,
            "raw_units": {
                "bargaining": (
                    "0.03410622955 * money_to_divide in undiscounted pie units; e.g. 3.4106 "
                    "units for a 100-unit pie or 341.0623 for a 10,000-unit pie, before timing discount"
                ),
                "negotiation": (
                    "0.03410622955 * product_price_order in raw price/value units; e.g. 3.4106 "
                    "at order 100; role sign and no-trade mass remain part of the estimand"
                ),
                "persuasion": (
                    "0.03410622955 * product_price * total_rounds terminal raw payoff; for the "
                    "seller in 20 rounds this equals 0.682124591 net additional sale-equivalents"
                ),
            },
            "full_glee_equal_family_role_dilution": {
                "assumption": "effect exists only in persuasion candidate-seller rows",
                "dilution_factor": FULL_GLEE_DILUTION,
                "a300_mde_equivalent": A300_HOLM3_MDE * FULL_GLEE_DILUTION,
                "sesoi_equivalent": SESOI * FULL_GLEE_DILUTION,
                "additional_text_configuration_prevalence_factor": "multiply by q_text if target GLEE includes nontext persuasion configurations",
            },
            "leaderboard_relevance": {
                "known_mapping": "rating=2000+8000*(within_configuration_role_percentile-0.5)",
                "payoff_to_percentile_mapping": "unknown_without_a_prospectively_frozen_reference_CDF_density",
                "claim": (
                    "0.00568437 full-GLEE normalized dilution may be practically modest, but no "
                    "rating-point or rank change is identified from payoff units alone"
                ),
            },
        },
        "exposure": {
            "language": {
                "structural_episode_exposure": 1.0,
                "rounds_exposed_per_eligible_episode": 20,
                "full_design_row_fraction_max": FULL_GLEE_DILUTION,
                "receiver_decision_change_frequency": "unknown_before_capability_and_factorial_outcomes",
                "capability_minimum_generic_change_frequency": 0.20,
                "capability_frequency_is_treatment_exposure_estimate": False,
                "conditional_episode_effect_required_by_affected_scenario_frequency": _conditional_effects(
                    A300_HOLM3_MDE
                ),
                "seller_purchase_rate_change_equivalent": A300_HOLM3_MDE,
            },
            "eprocess": {
                "structural_eligibility_max_rows": 600,
                "action_change_rule": "after crossing E>=20, flip a baseline no recommendation to yes",
                "crossing_or_action_change_frequency": "unknown_before_factorial_outcomes",
                "single_game_null_crossing_upper_bound_if_model_relative_null_holds": 0.05,
                "null_bound_is_alternative_exposure_forecast": False,
                "conditional_episode_effect_required_by_affected_scenario_frequency": _conditional_effects(
                    A300_HOLM3_MDE
                ),
                "at_5pct_affected_required_net_extra_sales_per_crossed_20_round_seller_episode": (
                    A300_HOLM3_MDE / 0.05 * 20
                ),
            },
        },
        "runtime": {
            "nominal_requests_including_capability": a300["whole_route_nominal_requests"],
            "maximum_attempts_including_capability": a300["whole_route_max_attempts"],
            "receiver_service_at_30s_concurrency32": retry_seconds,
            "wall_clock_cap_hours": WALL_CAP_HOURS,
            "retry_cap_service_margin_seconds": wall_seconds - retry_cap_seconds,
            "wall_cap_precedes_attempt_cap": True,
            "stop_rule": (
                "at 32h stop new submissions, cancel pending requests, checkpoint atomically, and "
                "mark an incomplete confirmatory study nonreportable; never replace missing rows"
            ),
            "full_study_authorized": False,
        },
        "receiver_failure_itt": {
            "rule_sha256": RECEIVER_FAILURE_ITT_RULE_SHA256,
            "failure_action": "buyer_pass/no_for_current_round",
            "continuation": "ordinary_fixed_horizon_environment",
            "numeric_payoff": "ordinary_finite_terminal_role_payoff",
            "post_assignment_exclusion": False,
        },
        "central_mde_table": central_mdes,
        "boundaries": {
            "treatment_outcomes_used": False,
            "receiver_capability_outputs_used": False,
            "model_a_or_b_used": False,
            "factorial_run_started": False,
            "external_call_performed": False,
            "production_pins_set": False,
        },
    }


def main() -> int:
    print(json.dumps(activation_evidence(), indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
