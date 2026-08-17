"""Prospective, outcome-blind design arithmetic for Wave 5D Route 1.

This module is deliberately independent of treatment outcomes and receiver-capability
results.  It turns a prespecified Design-A factorization into workload, cost, idealized
receiver-service-time, clustered effective-N, and MDE envelopes.  It does not set either
production authorization pin and it does not execute an episode or receiver request.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from statistics import NormalDist
from typing import Any, Iterable


FAMILIES = 3
ROLES_PER_FAMILY = 2
FACTORIAL_ARMS = 4
PERSUASION_ROUNDS = 20
CAPABILITY_NOMINAL_REQUESTS = 100
ATTEMPTS_PER_REQUEST = 2
MAX_CONCURRENCY = 32
PER_ATTEMPT_TIMEOUT_SECONDS = 30
HOLM_HYPOTHESES = 3
FAMILYWISE_ALPHA = 0.05
TARGET_POWER = 0.80
PRIMARY_INPUT_USD_PER_MILLION = Decimal("2.0")
PRIMARY_OUTPUT_USD_PER_MILLION = Decimal("8.0")
FALLBACK_INPUT_USD_PER_MILLION = Decimal("0.4")
FALLBACK_OUTPUT_USD_PER_MILLION = Decimal("1.6")
MAX_INPUT_TOKENS = 2048
MAX_OUTPUT_TOKENS = 16


@dataclass(frozen=True)
class Design:
    """One prospective paired 2x2 Design-A-shaped factorization."""

    design_id: str
    base_strata_per_family: int
    receiver_replicates: int = 2

    def validate(self) -> None:
        if self.base_strata_per_family < 2:
            raise ValueError("base_strata_per_family must be at least two")
        if self.receiver_replicates < 1:
            raise ValueError("receiver_replicates must be positive")


DESIGNS = (
    Design("A300", 300),
    Design("A200", 200),
    Design("A140", 140),
    Design("A100", 100),
)


def worst_case_holm_critical_value(
    *, alpha: float = FAMILYWISE_ALPHA, hypotheses: int = HOLM_HYPOTHESES
) -> float:
    """Two-sided critical value at Holm's most stringent first step."""

    if not 0.0 < alpha < 1.0 or hypotheses < 1:
        raise ValueError("invalid alpha or hypothesis count")
    return NormalDist().inv_cdf(1.0 - alpha / (2.0 * hypotheses))


def effective_sample_size(
    *, clusters: int, replicates: int, intraclass_correlation: float, information_loss: float
) -> float:
    """Planning effective N for a balanced exchangeable cluster.

    ``information_loss`` is a conservative information-retention sensitivity parameter, not
    permission to delete assigned rows.  The confirmatory estimator remains intent-to-treat.
    """

    if clusters < 1 or replicates < 1:
        raise ValueError("clusters and replicates must be positive")
    if not 0.0 <= intraclass_correlation <= 1.0:
        raise ValueError("intraclass_correlation must be in [0, 1]")
    if not 0.0 <= information_loss < 1.0:
        raise ValueError("information_loss must be in [0, 1)")
    rows = clusters * replicates
    design_effect = 1.0 + (replicates - 1) * intraclass_correlation
    return rows * (1.0 - information_loss) / design_effect


def minimum_detectable_effect(
    *,
    contrast_sd: float,
    effective_n: float,
    power: float = TARGET_POWER,
    alpha: float = FAMILYWISE_ALPHA,
    hypotheses: int = HOLM_HYPOTHESES,
) -> float:
    """Normal-approximation two-sided MDE under the worst Holm step."""

    if contrast_sd <= 0.0 or effective_n <= 0.0 or not 0.0 < power < 1.0:
        raise ValueError("contrast_sd/effective_n/power are invalid")
    critical = worst_case_holm_critical_value(alpha=alpha, hypotheses=hypotheses)
    power_quantile = NormalDist().inv_cdf(power)
    return (critical + power_quantile) * contrast_sd / math.sqrt(effective_n)


def required_clusters(
    *,
    target_effect: float,
    contrast_sd: float,
    replicates: int,
    intraclass_correlation: float,
    information_loss: float,
    power: float = TARGET_POWER,
) -> int:
    """Smallest balanced cluster count meeting the planning MDE target."""

    if target_effect <= 0.0:
        raise ValueError("target_effect must be positive")
    critical = worst_case_holm_critical_value()
    power_quantile = NormalDist().inv_cdf(power)
    needed_effective_n = ((critical + power_quantile) * contrast_sd / target_effect) ** 2
    information_per_cluster = (
        replicates
        * (1.0 - information_loss)
        / (1.0 + (replicates - 1) * intraclass_correlation)
    )
    return math.ceil(needed_effective_n / information_per_cluster)


def _attempt_cost(
    *, input_price: Decimal, output_price: Decimal
) -> Decimal:
    return (
        Decimal(MAX_INPUT_TOKENS) * input_price
        + Decimal(MAX_OUTPUT_TOKENS) * output_price
    ) / Decimal(1_000_000)


def _service_seconds(attempts: int, *, latency_seconds: int) -> int:
    """Idealized saturated-concurrency service time, excluding all overhead."""

    return math.ceil(attempts / MAX_CONCURRENCY) * latency_seconds


def design_envelope(design: Design) -> dict[str, Any]:
    """Return exact accounting for one design under the Wave 5C receiver contract."""

    design.validate()
    paired_rows = (
        design.base_strata_per_family
        * ROLES_PER_FAMILY
        * design.receiver_replicates
        * FAMILIES
    )
    eligible_rows = design.base_strata_per_family * design.receiver_replicates
    confirmatory_requests = eligible_rows * FACTORIAL_ARMS * PERSUASION_ROUNDS
    nominal_requests = confirmatory_requests + CAPABILITY_NOMINAL_REQUESTS
    max_attempts = nominal_requests * ATTEMPTS_PER_REQUEST
    primary_attempt_cost = _attempt_cost(
        input_price=PRIMARY_INPUT_USD_PER_MILLION,
        output_price=PRIMARY_OUTPUT_USD_PER_MILLION,
    )
    fallback_attempt_cost = _attempt_cost(
        input_price=FALLBACK_INPUT_USD_PER_MILLION,
        output_price=FALLBACK_OUTPUT_USD_PER_MILLION,
    )
    service = {
        str(latency): {
            "nominal_seconds": _service_seconds(nominal_requests, latency_seconds=latency),
            "retry_cap_seconds": _service_seconds(max_attempts, latency_seconds=latency),
        }
        for latency in (1, 5, PER_ATTEMPT_TIMEOUT_SECONDS)
    }
    return {
        "design": asdict(design),
        "paired_scenario_rows": paired_rows,
        "agent_episodes": paired_rows * FACTORIAL_ARMS,
        "primary_eligible_paired_rows": eligible_rows,
        "primary_independent_clusters": design.base_strata_per_family,
        "confirmatory_nominal_requests": confirmatory_requests,
        "whole_route_nominal_requests": nominal_requests,
        "whole_route_max_attempts": max_attempts,
        "primary_cost_usd": {
            "nominal": str(primary_attempt_cost * nominal_requests),
            "retry_cap": str(primary_attempt_cost * max_attempts),
        },
        "fallback_cost_usd": {
            "nominal": str(fallback_attempt_cost * nominal_requests),
            "retry_cap": str(fallback_attempt_cost * max_attempts),
        },
        "idealized_receiver_service_time": {
            "assumptions": "saturated concurrency 32; fixed per-attempt latency; excludes episode, scheduler, cache, and report overhead",
            "seconds_by_attempt_latency": service,
        },
        "retry_cap_completes_within_12h_at_30s": service["30"]["retry_cap_seconds"]
        <= 12 * 60 * 60,
    }


def mde_grid(
    design: Design,
    *,
    standard_deviations: Iterable[float] = (0.10, 0.20, 0.30, 0.50, 0.75, 1.00),
    intraclass_correlations: Iterable[float] = (0.0, 0.25, 0.50, 0.75),
    information_losses: Iterable[float] = (0.0, 0.05, 0.10, 0.20),
) -> list[dict[str, float]]:
    """Prospective primary-cell grid; no observed outcome enters the calculation."""

    design.validate()
    output: list[dict[str, float]] = []
    for sd in standard_deviations:
        for rho in intraclass_correlations:
            for loss in information_losses:
                n_eff = effective_sample_size(
                    clusters=design.base_strata_per_family,
                    replicates=design.receiver_replicates,
                    intraclass_correlation=rho,
                    information_loss=loss,
                )
                output.append(
                    {
                        "contrast_sd": sd,
                        "intraclass_correlation": rho,
                        "information_loss": loss,
                        "effective_n": n_eff,
                        "mde": minimum_detectable_effect(
                            contrast_sd=sd, effective_n=n_eff
                        ),
                    }
                )
    return output


def planning_evidence() -> dict[str, Any]:
    """Canonical outcome-blind calculation payload used by tests and documentation."""

    central = {
        "contrast_sd": 0.20,
        "intraclass_correlation": 0.50,
        "information_loss": 0.10,
    }
    summaries = []
    for design in DESIGNS:
        n_eff = effective_sample_size(
            clusters=design.base_strata_per_family,
            replicates=design.receiver_replicates,
            intraclass_correlation=central["intraclass_correlation"],
            information_loss=central["information_loss"],
        )
        summaries.append(
            {
                **design_envelope(design),
                "central_planning_case": {
                    **central,
                    "effective_n": n_eff,
                    "mde": minimum_detectable_effect(
                        contrast_sd=central["contrast_sd"], effective_n=n_eff
                    ),
                },
            }
        )
    return {
        "schema": "glee.research.wave5d.paper_design.v1",
        "evidence_class": "prospective_design_arithmetic_only_no_outcomes",
        "alpha": FAMILYWISE_ALPHA,
        "power": TARGET_POWER,
        "holm_hypotheses": HOLM_HYPOTHESES,
        "worst_case_holm_critical_value": worst_case_holm_critical_value(),
        "designs": summaries,
        "a300_mde_grid": mde_grid(DESIGNS[0]),
        "required_a_clusters_for_0_01_central_case": required_clusters(
            target_effect=0.01,
            contrast_sd=central["contrast_sd"],
            replicates=2,
            intraclass_correlation=central["intraclass_correlation"],
            information_loss=central["information_loss"],
        ),
        "boundaries": {
            "treatment_outcomes_used": False,
            "receiver_capability_outputs_used": False,
            "external_calls": False,
            "production_pins_set": False,
            "synthetic_or_planning_output_is_scientific_evidence": False,
        },
    }


def main() -> int:
    """Print the complete deterministic planning payload for independent reconstruction."""

    print(json.dumps(planning_evidence(), sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
