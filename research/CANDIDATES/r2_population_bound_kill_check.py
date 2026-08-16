"""Bounded training-only kill check for a population-valid R2 null bound."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any


TREATMENT_LABEL = "model-relative e-process against a fixed hash-locked Model-C reference"


def _load_verified(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, str(expected_sha256).lower()):
        raise ValueError(f"Model-C sha256 mismatch: expected {expected_sha256}, found {actual}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Model-C artifact must be a JSON object")
    return payload


def distribution_free_future_upper_bound(training_prefix: list[int]) -> float:
    """The sharp future conditional-probability bound with no population assumptions.

    Any finite realized prefix is compatible with a process that assigns conditional
    probability one to the next success. Consequently no function of the prefix can
    give a uniformly valid bound below one without additional exchangeability,
    stationarity, or model assumptions.
    """

    if any(value not in {0, 1} for value in training_prefix):
        raise ValueError("training prefix must be binary")
    return 1.0


def run_kill_check(path: str | Path, expected_sha256: str) -> dict[str, Any]:
    payload = _load_verified(path, expected_sha256)
    persuasion = ((payload.get("families") or {}).get("persuasion") or {}).get("buckets")
    if not isinstance(persuasion, dict):
        raise ValueError("Model-C artifact lacks persuasion buckets")
    minimum = int(payload.get("min_support", 0))
    eligible = [
        row
        for key, row in persuasion.items()
        if key != "__global__"
        and isinstance(row, dict)
        and int(row.get("trials", 0)) >= minimum
        and float(row.get("support_quality", 0.0)) >= 0.5
        and 0.01 <= float(row.get("probability", -1.0)) <= 0.99
    ]
    robust_bound = distribution_free_future_upper_bound([])
    return {
        "schema": "glee.research.r2_population_bound_kill_check.v1",
        "model_c": {
            "path": str(Path(path).resolve()),
            "sha256": str(expected_sha256).lower(),
            "split": "fixed training artifact only; no held-out/payoff outcomes inspected",
            "persuasion_bucket_count": len(persuasion),
            "controller_eligible_reference_buckets": len(eligible),
            "eligible_probability_range": [
                min(float(row["probability"]) for row in eligible),
                max(float(row["probability"]) for row in eligible),
            ] if eligible else None,
        },
        "candidate_bound": {
            "construction": "supremum over all future binary processes compatible with the finite training prefix",
            "sharp_distribution_free_upper_bound": robust_bound,
            "fixed_and_predictable": True,
            "coverage_guarantee": "uniform one-step conditional coverage 1, but only at the trivial bound",
            "informative_for_current_likelihood_ratio": False,
        },
        "dependence": {
            "arbitrary_repeated_observation_dependence_allowed": True,
            "consequence": "every nontrivial bound below one loses finite-sample conditional coverage",
        },
        "optional_stopping": {
            "valid_if_conditional_null_holds": True,
            "population_null_established": False,
            "reason": "Ville validity cannot repair an unproved conditional upper-bound premise",
        },
        "multiplicity": {
            "implemented_scope": "one within-game persuasion-seller stream",
            "across_games_or_selected_signals_controlled": False,
            "bucket_count_requiring_simultaneous_or_cross-fitted_claim_if_selected": len(eligible),
        },
        "verdict": "KILL_NONTRIVIAL_POPULATION_BOUND_EXTENSION",
        "reason": "training data alone cannot exclude a future conditional follow probability of one without extra population assumptions",
        "treatment_label": TREATMENT_LABEL,
        "holdout_inspected": False,
        "payoff_run": False,
        "live_or_rated_games": 0,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("model_c")
    parser.add_argument("sha256")
    arguments = parser.parse_args()
    print(json.dumps(run_kill_check(arguments.model_c, arguments.sha256), indent=2, sort_keys=True))
