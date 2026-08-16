"""Leak-free metrics for validating a joint opponent-parameter sampler.

This module deliberately does not fit either population model.  It consumes
observed bundle rows and predictive draws prepared from a FIT-only artifact, then
scores the draws as a multivariate distribution.  Keeping fitting out of this
module makes it harder for a validation command to accidentally learn from its
holdout.
"""

from __future__ import annotations

import math
import random
import hashlib
import json
import bisect
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from glee_eval.population.opponent_fit import (
    OpponentPopulation,
    config_signature,
    extract_joint_bundle_observations,
    extract_response_observations,
    response_parameter,
    response_probability,
)
from glee_eval.population.crossfit import CrossfitRouter, fold_count
from glee_eval.population.sampler import ARCHETYPES
from glee_eval.population.splits import HOLDOUT, is_holdout_key, keeps
from glee_eval.storage.trajectories import canonical_json_sha256, iter_jsonl

try:  # Optional acceleration; the bundled workspace runtime provides NumPy.
    import numpy as _np
except ImportError:  # pragma: no cover - exercised by the system Python in CI.
    _np = None


def response_reference_errors(payload: dict[str, Any], *, require_schema: bool = False) -> list[str]:
    """Validate compact bundle references against the one canonical family fit."""
    joint = payload.get("joint_model") or {}
    fits = joint.get("response_estimators") or {}
    schema = joint.get("response_estimator_reference_schema") or {}
    if not schema:  # schema-v2 artifacts predating normalized references
        return ["missing_reference_schema"] if require_schema else []
    required=["family","channel","canonical_fit_reference","canonical_fit_sha256"]
    expected_schema_keys = {
        "version", "canonical_root", "required_fields", "canonical_fit_sha256_by_family",
        "references_by_family", "total_references", "canonical_full_fit_count",
    }
    if set(schema) != expected_schema_keys: return ["reference_schema_keys"]
    if schema.get("version")!=1: return ["reference_schema_version"]
    if schema.get("canonical_root")!="joint_model.response_estimators": return ["reference_schema_root"]
    if schema.get("required_fields")!=required: return ["reference_schema_required_fields"]
    if set(fits) != {"bargaining", "negotiation", "persuasion"}: return ["canonical_fit_families"]
    fit_hashes={family:canonical_json_sha256(fit) for family,fit in fits.items()}
    if schema.get("canonical_fit_sha256_by_family")!=fit_hashes: return ["canonical_fit_hashes"]
    allowed = {
        ("bargaining", "player_1"): {"accept_threshold": "bargaining|player_1"},
        ("bargaining", "player_2"): {"accept_threshold": "bargaining|player_2"},
        ("negotiation", "seller"): {"accept_margin": "negotiation|seller"},
        ("negotiation", "buyer"): {"accept_margin": "negotiation|buyer"},
        ("persuasion", "seller"): {"honesty": "persuasion|seller_high", "yes_on_low_rate": "persuasion|seller_low"},
        ("persuasion", "buyer"): {"trust_prior": "persuasion|buyer_yes", "buy_after_no_rate": "persuasion|buyer_no"},
    }
    errors=[]; counts=defaultdict(int)
    for family,bundles in sorted((payload.get("joint_bundles") or {}).items()):
        counts[family] += 0
        if family not in fits: errors.append(f"{family}:missing_canonical_fit")
        for bundle in bundles:
            identity=str(bundle.get("bundle_id")); role=str(bundle.get("role")); entries=bundle.get("response_estimator") or {}
            expected=allowed.get((family,role),{})
            for parameter,entry in entries.items():
                counts[family]+=1
                channel=entry.get("channel"); reference=entry.get("canonical_fit_reference")
                if entry.get("family")!=family: errors.append(f"{identity}:{parameter}:cross_family")
                if expected.get(parameter)!=channel: errors.append(f"{identity}:{parameter}:channel")
                if reference!=f"joint_model.response_estimators.{family}": errors.append(f"{identity}:{parameter}:reference")
                if entry.get("canonical_fit_sha256")!=fit_hashes.get(family): errors.append(f"{identity}:{parameter}:fit_hash")
                fit=fits.get(family)
                if not fit: continue
                value,provenance=response_parameter(fit,channel=str(channel),player_model=str(bundle.get("player_model")),signature=str(bundle.get("config_signature")))
                parameters=bundle.get("parameters") or {}; stored=parameters.get(parameter)
                if (parameter in parameters)!=(value is not None): errors.append(f"{identity}:{parameter}:parameter_presence")
                elif value is not None and (
                    not math.isfinite(float(value)) or not math.isfinite(float(stored))
                    or float(value) != float(stored)
                ): errors.append(f"{identity}:{parameter}:recompute")
                expected_entry={"family":family,"channel":channel,"canonical_fit_reference":f"joint_model.response_estimators.{family}","canonical_fit_sha256":fit_hashes[family],**{key:provenance[key] for key in ("parameter_kind","raw_threshold","fit_min","fit_max","clipped","monotone_slope","channel_support") if key in provenance}}
                if set(entry)!=set(expected_entry): errors.append(f"{identity}:{parameter}:metadata_keys")
                for key in set(entry)|set(expected_entry):
                    left=entry.get(key); right=expected_entry.get(key)
                    if isinstance(left,float) and isinstance(right,float):
                        equal=math.isfinite(left) and math.isfinite(right) and left == right
                    else: equal=left==right
                    if not equal: errors.append(f"{identity}:{parameter}:metadata:{key}")
            if set(entries)!=set(expected): errors.append(f"{identity}:reference_completeness")
    declared=schema.get("references_by_family") or {}
    if dict(counts)!={key:int(value) for key,value in declared.items()}: errors.append("reference_counts")
    if int(schema.get("total_references",-1))!=sum(counts.values()): errors.append("total_reference_count")
    if int(schema.get("canonical_full_fit_count",-1))!=len(fits): errors.append("canonical_fit_count")
    return errors


def empirical_cdf(value: float, fit_values: Sequence[float]) -> float:
    """Map a value through a FIT-only empirical CDF, including finite tails."""

    if not fit_values:
        raise ValueError("fit_values must be non-empty")
    ordered = fit_values if isinstance(fit_values, tuple) else tuple(sorted(float(item) for item in fit_values))
    below = bisect.bisect_left(ordered, value)
    equal = bisect.bisect_right(ordered, value) - below
    # Mid-ranks avoid mapping an observed endpoint exactly onto zero or one.
    return (below + 0.5 * equal + 0.5) / (len(ordered) + 1.0)


def transform_parameters(
    parameters: dict[str, float],
    fit_marginals: dict[str, Sequence[float]],
    names: Sequence[str],
) -> tuple[float, ...]:
    """Put heterogeneous parameters on comparable FIT-only rank scales."""

    missing = [name for name in names if name not in parameters or name not in fit_marginals]
    if missing:
        raise ValueError(f"parameters unavailable for validation: {missing}")
    return tuple(empirical_cdf(float(parameters[name]), fit_marginals[name]) for name in names)


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have equal dimensions")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def energy_score(observed: Sequence[float], draws: Sequence[Sequence[float]]) -> float:
    """Multivariate energy score; lower is better.

    At the declared 256 draws, the exact pairwise empirical expectation is small
    enough to compute directly.  This avoids making the score depend on draw order
    (important when archetypes are deliberately balanced in a fixed cycle).
    """

    if len(draws) < 2:
        raise ValueError("energy score requires at least two predictive draws")
    if _np is not None:
        matrix = _np.asarray(draws, dtype=float)
        target = _np.asarray(observed, dtype=float)
        first = float(_np.linalg.norm(matrix - target, axis=1).mean())
        distance_sum = 0.0
        block = 64
        for start in range(0, len(matrix), block):
            distance_sum += float(_np.linalg.norm(
                matrix[start:start + block, None, :] - matrix[None, :, :], axis=2
            ).sum())
        return first - 0.5 * distance_sum / (len(matrix) ** 2)
    first = sum(_distance(draw, observed) for draw in draws) / len(draws)
    # Diagonal distances are zero and the matrix is symmetric.
    pair_sum = sum(
        _distance(draws[left], draws[right])
        for left in range(len(draws)) for right in range(left + 1, len(draws))
    )
    return first - pair_sum / (len(draws) ** 2)


def crps(observed: float, draws: Sequence[float]) -> float:
    """Univariate empirical CRPS, invariant to predictive-draw order."""

    if len(draws) < 2:
        raise ValueError("CRPS requires at least two predictive draws")
    if _np is not None:
        values = _np.asarray(draws, dtype=float)
        first = float(_np.abs(values - observed).mean())
        return first - 0.5 * float(_np.abs(values[:, None] - values[None, :]).mean())
    first = sum(abs(draw - observed) for draw in draws) / len(draws)
    ordered = sorted(draws)
    # Sum_{i<j}(x_j-x_i) = Sum_i (2*i-n+1)*x_i.
    pair_sum = sum((2 * index - len(ordered) + 1) * value for index, value in enumerate(ordered))
    return first - pair_sum / (len(draws) ** 2)


def score_bundle(
    observed: Sequence[float],
    joint_draws: Sequence[Sequence[float]],
    independent_draws: Sequence[Sequence[float]],
) -> dict[str, Any]:
    """Paired joint-dependence and marginal scores for one observed bundle."""

    if len(observed) < 2:
        raise ValueError("joint validation requires at least two observed parameters")
    dimensions = len(observed)
    if any(len(draw) != dimensions for draw in (*joint_draws, *independent_draws)):
        raise ValueError("all predictive draws must match the observed dimensions")
    joint_energy = energy_score(observed, joint_draws)
    independent_energy = energy_score(observed, independent_draws)
    marginal_deltas = []
    for index in range(dimensions):
        joint = crps(observed[index], [draw[index] for draw in joint_draws])
        independent = crps(observed[index], [draw[index] for draw in independent_draws])
        marginal_deltas.append(joint - independent)
    return {
        "joint_energy": joint_energy,
        "independent_energy": independent_energy,
        "energy_delta": joint_energy - independent_energy,
        "marginal_crps_deltas": marginal_deltas,
    }


def cluster_bootstrap_mean(
    rows: Iterable[dict[str, Any]],
    value_key: str,
    *,
    cluster_key: str = "game_id",
    seed: int = 20260815,
    replicates: int = 2000,
) -> dict[str, float]:
    """Deterministic percentile interval, resampling whole game clusters."""

    if replicates < 1:
        raise ValueError("replicates must be positive")
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row[cluster_key])].append(float(row[value_key]))
    keys = sorted(grouped)
    if not keys:
        raise ValueError("cannot bootstrap an empty sample")
    observed = sum(sum(grouped[key]) for key in keys) / sum(len(grouped[key]) for key in keys)
    rng = random.Random(seed)
    samples = []
    for _ in range(replicates):
        chosen = [keys[rng.randrange(len(keys))] for _ in keys]
        values = [value for key in chosen for value in grouped[key]]
        samples.append(sum(values) / len(values))
    samples.sort()

    def percentile(point: float) -> float:
        index = min(len(samples) - 1, max(0, int(round(point * (len(samples) - 1)))))
        return samples[index]

    return {"mean": observed, "ci_low": percentile(0.025), "ci_high": percentile(0.975)}


def binary_log_loss(outcome: int | bool, probability: float) -> float:
    """Clipped Bernoulli log loss used by the declared OOF decision endpoints."""

    probability = float(probability)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("decision probability must be finite and in [0, 1]")
    clipped = min(1.0 - 1e-15, max(1e-15, probability))
    return -math.log(clipped if bool(outcome) else 1.0 - clipped)


def brier_score(outcome: int | bool, probability: float) -> float:
    """Bernoulli Brier score with strict probability-domain validation."""

    probability = float(probability)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError("decision probability must be finite and in [0, 1]")
    return (probability - int(bool(outcome))) ** 2


def score_oof_decision(
    *,
    outcome: int | bool,
    model_b_probability: float,
    neutral_probability: float,
    v1_probability: float,
) -> dict[str, float]:
    """Return paired per-decision losses without fitting or selecting anything."""

    model_log = binary_log_loss(outcome, model_b_probability)
    neutral_log = binary_log_loss(outcome, neutral_probability)
    v1_log = binary_log_loss(outcome, v1_probability)
    model_brier = brier_score(outcome, model_b_probability)
    neutral_brier = brier_score(outcome, neutral_probability)
    v1_brier = brier_score(outcome, v1_probability)
    return {
        "model_b_log_loss": model_log,
        "neutral_log_loss_delta": model_log - neutral_log,
        "v1_log_loss_delta": model_log - v1_log,
        "model_b_brier": model_brier,
        "neutral_brier_delta": model_brier - neutral_brier,
        "v1_brier_delta": model_brier - v1_brier,
    }


_PCG_SHIFTS = [0.0, 1e-12, 1e-10, 1e-8, 1e-6, 1e-4]
_PCG_RESIDUAL_RULE = "max(1e-12,min(.5,sqrt(current_projected_kkt))*current_projected_kkt)"
_PCG_CAP_RULE = "min(2000,max(50,4*free_parameter_count))"
_PCG_PRECONDITIONER = "exact_intercept_slope_block_plus_diagonal_contrasts"


def _newton_pcg_solver_audit_errors(payload: dict[str, Any], prefix: str) -> list[str]:
    """Validate frozen Newton-PCG constants and per-channel numerical audit."""

    errors: list[str] = []
    def fail(reason: str) -> None:
        errors.append(f"{prefix}:{reason}")

    if payload.get("optimizer") != "zero_sum_sparse_newton_pcg_with_armijo":
        fail("optimizer")
    if payload.get("pcg_residual_rule") != _PCG_RESIDUAL_RULE:
        fail("pcg_residual_rule")
    if payload.get("pcg_iteration_cap_rule") != _PCG_CAP_RULE:
        fail("pcg_iteration_cap_rule")
    if payload.get("pcg_shift_schedule") != _PCG_SHIFTS:
        fail("pcg_shift_schedule")
    if payload.get("pcg_preconditioner") != _PCG_PRECONDITIONER:
        fail("pcg_preconditioner")
    if payload.get("armijo_c1") != 1e-4:
        fail("armijo_c1")
    audits = payload.get("contrast_audit")
    if not isinstance(audits, list) or not audits:
        fail("missing_contrast_audit")
        return errors
    seen_channels: set[str] = set()
    for audit_index, audit in enumerate(audits):
        label = f"{prefix}:channel[{audit_index}]"
        if not isinstance(audit, dict):
            errors.append(f"{label}:schema")
            continue
        channel = str(audit.get("channel") or "")
        if not channel or channel in seen_channels:
            errors.append(f"{label}:channel_identity")
        seen_channels.add(channel)
        try:
            dimension = int(audit["dimension"])
            models = int(audit["models"])
            configs = int(audit["configs"])
            if min(dimension, models, configs) <= 0:
                errors.append(f"{label}:dimension")
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append(f"{label}:dimension")
            continue
        order = audit.get("free_vector_coefficient_order")
        digest = audit.get("coefficient_order_sha256")
        try:
            parsed_order = json.loads(order) if isinstance(order, str) else None
        except (TypeError, ValueError):
            parsed_order = None
        order_valid = (
            isinstance(parsed_order, list)
            and len(parsed_order) == dimension
            and len(set(parsed_order)) == dimension
            and sum(str(value).startswith("model:") for value in parsed_order) == models - 1
            and sum(str(value).startswith("config:") for value in parsed_order) == configs - 1
            and parsed_order[-1] in {"intercept", "slope"}
            and "intercept" in parsed_order
        )
        if (
            not isinstance(order, str) or not order or not order_valid
            or digest != hashlib.sha256(order.encode()).hexdigest()
        ):
            errors.append(f"{label}:coefficient_order_hash")
        for name in ("zero_sum_model", "zero_sum_config"):
            try:
                value = float(audit[name])
                if not math.isfinite(value) or abs(value) > 1e-10:
                    errors.append(f"{label}:{name}")
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append(f"{label}:{name}")
        objective_history = audit.get("objective_history")
        raw_history = audit.get("raw_kkt_history")
        active_history = audit.get("active_slope_history")
        try:
            objectives = [float(value) for value in objective_history]
            raw_values = [float(value) for value in raw_history]
            if not objectives or any(not math.isfinite(value) for value in objectives):
                errors.append(f"{label}:objective_history")
            if any(right > left + 1e-9 * max(1.0, abs(left)) for left, right in zip(objectives, objectives[1:])):
                errors.append(f"{label}:objective_nonmonotone")
            if not raw_values or any(not math.isfinite(value) or value < 0 for value in raw_values):
                errors.append(f"{label}:raw_kkt_history")
            if not isinstance(active_history, list) or not all(isinstance(value, bool) for value in active_history):
                errors.append(f"{label}:active_slope_history")
            elif len(raw_values) != len(active_history) + 1:
                errors.append(f"{label}:active_raw_history_alignment")
            raw_final = float(audit["raw_kkt_final"])
            raw_worst = float(audit["raw_kkt_worst_value"])
            if (
                not math.isclose(raw_final, raw_values[-1], rel_tol=1e-12, abs_tol=1e-12)
                or not math.isclose(abs(raw_worst), raw_final, rel_tol=1e-12, abs_tol=1e-12)
                or not str(audit.get("raw_kkt_worst_key") or "")
                or audit.get("projected_kkt") != audit.get("raw_kkt_final")
            ):
                errors.append(f"{label}:raw_kkt_final_or_worst")
            if raw_final > 1e-7 or audit.get("stop_reason") != "projected_kkt":
                errors.append(f"{label}:raw_kkt_convergence")
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append(f"{label}:history_values")
            objectives, raw_values = [], []
        preconditioner = audit.get("preconditioner")
        has_slope = bool(order_valid and parsed_order[-1] == "slope")
        expected_block = "intercept_slope_2x2" if has_slope else "intercept_1x1"
        if preconditioner != {"block": expected_block, "contrast_diagonal": True, "pivot_floor": 1e-18}:
            errors.append(f"{label}:preconditioner")
        if not isinstance(audit.get("active_slope"), bool) or (not has_slope and audit.get("active_slope")):
            errors.append(f"{label}:active_slope")
        try:
            if (
                not 1 <= int(audit["iterations"]) <= 300
                or not math.isfinite(float(audit["max_change"])) or float(audit["max_change"]) < 0
                or not math.isfinite(float(audit["last_damping"]))
                or not 0 < float(audit["last_damping"]) <= 1
                or int(audit["total_backtracks"]) < 0
            ):
                errors.append(f"{label}:terminal_diagnostics")
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append(f"{label}:terminal_diagnostics")
        pcg = audit.get("pcg")
        armijo = audit.get("armijo")
        if not isinstance(pcg, list) or not isinstance(armijo, list) or len(pcg) != len(armijo):
            errors.append(f"{label}:pcg_armijo_alignment")
            continue
        if objectives and len(objectives) != len(armijo) + 1:
            errors.append(f"{label}:objective_armijo_alignment")
        for record_index, (record, armijo_record) in enumerate(zip(pcg, armijo), start=1):
            record_label = f"{label}:iteration[{record_index}]"
            try:
                current_kkt = float(record["current_projected_kkt"])
                target = max(1e-12, min(0.5, math.sqrt(current_kkt)) * current_kkt)
                cap = min(2000, max(50, 4 * dimension))
                if record["iteration"] != record_index or not math.isclose(
                    float(record["absolute_residual_target"]), target, rel_tol=1e-15, abs_tol=0.0
                ) or record["iteration_cap"] != cap:
                    errors.append(f"{record_label}:target_or_cap")
                if raw_values and not math.isclose(current_kkt, raw_values[record_index - 1], rel_tol=1e-12, abs_tol=1e-12):
                    errors.append(f"{record_label}:kkt_history")
                attempts = record["shift_attempts"]
                if not isinstance(attempts, list) or not attempts or len(attempts) > len(_PCG_SHIFTS):
                    errors.append(f"{record_label}:shift_attempts")
                    attempts = []
                for attempt_index, attempt in enumerate(attempts):
                    if attempt.get("shift") != _PCG_SHIFTS[attempt_index]:
                        errors.append(f"{record_label}:shift_order")
                    residual = float(attempt["residual"])
                    attempt_target = float(attempt["target"])
                    iterations = int(attempt["iterations"])
                    if (
                        not math.isfinite(residual) or residual < 0 or attempt_target != target
                        or not 0 <= iterations <= cap or not isinstance(attempt.get("solved"), bool)
                    ):
                        errors.append(f"{record_label}:shift_values")
                    if attempt["solved"]:
                        if (
                            attempt.get("curvature_failure") is not None or residual > target
                            or not math.isfinite(float(attempt["curvature_product"]))
                            or float(attempt["curvature_product"]) <= 0
                            or not math.isfinite(float(attempt["descent_product"]))
                            or float(attempt["descent_product"]) >= 0
                        ):
                            errors.append(f"{record_label}:solved_shift_contract")
                    elif attempt.get("curvature_failure") is None:
                        errors.append(f"{record_label}:failed_shift_reason")
                    if (
                        attempt_index < len(attempts) - 1
                        and attempt.get("curvature_failure") not in {"nonpositive_curvature", "nondescent"}
                    ):
                        errors.append(f"{record_label}:undeclared_shift_retry")
                if any(attempt.get("solved") is True for attempt in attempts[:-1]):
                    errors.append(f"{record_label}:continued_after_solved_shift")
                if (
                    not attempts or record.get("solved") is not True or attempts[-1].get("solved") is not True
                    or record.get("shift") != attempts[-1].get("shift")
                    or record.get("pcg_iterations") != attempts[-1].get("iterations")
                    or not math.isclose(float(record["final_residual"]), float(attempts[-1]["residual"]), rel_tol=1e-12, abs_tol=1e-12)
                    or float(record["final_residual"]) > target
                    or not math.isfinite(float(record["curvature_product"])) or float(record["curvature_product"]) <= 0
                    or not math.isfinite(float(record["descent_product"])) or float(record["descent_product"]) >= 0
                    or not math.isclose(float(record["curvature_product"]), float(attempts[-1]["curvature_product"]), rel_tol=1e-12, abs_tol=1e-12)
                    or not math.isclose(float(record["descent_product"]), float(attempts[-1]["descent_product"]), rel_tol=1e-12, abs_tol=1e-12)
                ):
                    errors.append(f"{record_label}:pcg_final_contract")
                backtracks = int(armijo_record["backtracks"])
                alpha = float(armijo_record["alpha"])
                if (
                    armijo_record.get("iteration") != record_index or armijo_record.get("passed") is not True
                    or backtracks < 0 or not math.isfinite(alpha) or alpha <= 0 or alpha > 1
                    or not math.isclose(alpha, 2.0 ** (-backtracks), rel_tol=1e-15, abs_tol=0.0)
                ):
                    errors.append(f"{record_label}:armijo")
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append(f"{record_label}:schema_or_values")
        try:
            if int(audit["total_backtracks"]) != sum(int(record["backtracks"]) for record in armijo):
                errors.append(f"{label}:armijo_backtrack_sum")
            if armijo and not math.isclose(
                float(audit["last_damping"]), float(armijo[-1]["alpha"]), rel_tol=1e-12, abs_tol=1e-12
            ):
                errors.append(f"{label}:last_damping")
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append(f"{label}:armijo_summary")
    try:
        histories = [[float(value) for value in audit["objective_history"]] for audit in audits]
        aggregate = [
            math.fsum(history[min(index, len(history) - 1)] for history in histories)
            for index in range(max(len(history) for history in histories))
        ]
        top_history = [float(value) for value in payload.get("objective_history", aggregate)]
        if "objective_history" in payload and (
            len(top_history) != len(aggregate)
            or any(not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
                   for left, right in zip(top_history, aggregate))
        ):
            fail("aggregate_objective_history")
        if "final_objective" in payload and not math.isclose(
            float(payload["final_objective"]), math.fsum(history[-1] for history in histories),
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            fail("aggregate_final_objective")
        if "final_max_gradient" in payload and not math.isclose(
            float(payload["final_max_gradient"]), max(float(audit["raw_kkt_final"]) for audit in audits),
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            fail("aggregate_raw_kkt")
        if "final_max_change" in payload and not math.isclose(
            float(payload["final_max_change"]), max(float(audit["max_change"]) for audit in audits),
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            fail("aggregate_max_change")
        if "total_backtracks" in payload and int(payload["total_backtracks"]) != sum(
            int(audit["total_backtracks"]) for audit in audits
        ):
            fail("aggregate_backtracks")
        if "last_damping" in payload and not math.isclose(
            float(payload["last_damping"]), min(float(audit["last_damping"]) for audit in audits),
            rel_tol=1e-12, abs_tol=1e-12,
        ):
            fail("aggregate_damping")
    except (KeyError, TypeError, ValueError, OverflowError):
        fail("aggregate_solver_audit")
    return errors


def response_fit_provenance_errors(fit: dict[str, Any]) -> list[str]:
    """Return violations of the frozen projected-KKT response-fit contract."""

    errors: list[str] = []
    expected_grid = [0.1, 1.0, 10.0, 100.0]
    expected_keys = {str(value) for value in expected_grid}
    if fit.get("status") != "ok" or fit.get("reason") is not None:
        errors.append("fit_status_not_ok")
    if fit.get("optimizer") != "zero_sum_sparse_newton_pcg_with_armijo":
        errors.append("optimizer_mismatch")
    errors.extend(_newton_pcg_solver_audit_errors(fit, "final"))
    if fit.get("converged") is not True or fit.get("projected_kkt_pass") is not True:
        errors.append("projected_kkt_not_passed")
    if fit.get("stop_reason") != "projected_kkt":
        errors.append("invalid_stop_reason")
    if fit.get("max_iterations") != 300 or fit.get("tolerance") != 1e-7:
        errors.append("iteration_or_tolerance_mismatch")
    if fit.get("projected_kkt_tolerance") != 1e-7:
        errors.append("projected_kkt_tolerance_mismatch")
    try:
        iterations = int(fit["iterations"])
        gradient = float(fit["final_max_gradient"])
        change = float(fit["final_max_change"])
        objective = float(fit["final_objective"])
        damping = float(fit["last_damping"])
        backtracks = int(fit["total_backtracks"])
        if not 1 <= iterations <= 300:
            errors.append("invalid_iteration_count")
        if not math.isfinite(gradient) or gradient < 0.0 or gradient > 1e-7:
            errors.append("projected_kkt_residual_exceeds_tolerance")
        if not math.isfinite(change) or change < 0.0:
            errors.append("invalid_final_change")
        if not math.isfinite(objective):
            errors.append("nonfinite_final_objective")
        if not math.isfinite(damping) or not 0.0 < damping <= 1.0:
            errors.append("invalid_damping")
        if backtracks < 0 or isinstance(fit.get("total_backtracks"), bool):
            errors.append("invalid_backtrack_count")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("missing_or_invalid_solver_diagnostics")

    coefficients = fit.get("coefficients")
    if not isinstance(coefficients, dict) or not coefficients:
        errors.append("missing_coefficients")
    else:
        for name, value in coefficients.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError):
                errors.append("nonfinite_coefficient")
                break
            if not math.isfinite(numeric):
                errors.append("nonfinite_coefficient")
                break
            if str(name).startswith("slope|") and numeric < 1e-8:
                errors.append("slope_below_lower_bound")
                break
    scales = fit.get("x_scale")
    if not isinstance(scales, dict) or not scales:
        errors.append("missing_x_scale")
    else:
        for scale in scales.values():
            if not isinstance(scale, dict):
                errors.append("invalid_x_scale")
                break
            try:
                mean_value, sd = float(scale["mean"]), float(scale["sd"])
                endpoints = [scale.get("min"), scale.get("max")]
                if not math.isfinite(mean_value) or not math.isfinite(sd) or sd <= 0.0:
                    errors.append("invalid_x_scale")
                    break
                if any(value is not None and not math.isfinite(float(value)) for value in endpoints):
                    errors.append("invalid_x_scale")
                    break
                if endpoints[0] is not None and endpoints[1] is not None and float(endpoints[0]) > float(endpoints[1]):
                    errors.append("invalid_x_scale")
                    break
            except (KeyError, TypeError, ValueError, OverflowError):
                errors.append("invalid_x_scale")
                break
    try:
        raw_rows = int(fit["raw_rows"])
        aggregated_rows = int(fit["aggregated_rows"])
        statistic_rows = int(fit["numerical_sufficient_statistic_rows"])
        if (
            fit.get("aggregation_enabled") is not True
            or min(raw_rows, aggregated_rows, statistic_rows) <= 0
            or aggregated_rows != statistic_rows or statistic_rows > raw_rows
            or raw_rows != int(fit["training_rows"])
        ):
            errors.append("invalid_aggregation_provenance")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("invalid_aggregation_provenance")

    history = fit.get("objective_history")
    if not isinstance(history, list) or len(history) < 2:
        errors.append("missing_objective_history")
    else:
        try:
            values = [float(value) for value in history]
            if any(not math.isfinite(value) for value in values):
                errors.append("nonfinite_objective_history")
            if any(right > left + 1e-9 * max(1.0, abs(left)) for left, right in zip(values, values[1:])):
                errors.append("nonmonotone_objective_history")
            if math.isfinite(float(fit.get("final_objective", float("nan")))) and not math.isclose(
                values[-1], float(fit["final_objective"]), rel_tol=1e-12, abs_tol=1e-12
            ):
                errors.append("final_objective_history_mismatch")
        except (TypeError, ValueError, OverflowError):
            errors.append("invalid_objective_history")

    ridge_grid = fit.get("ridge_grid")
    cv = fit.get("cv_log_loss")
    inner = fit.get("inner_cv_convergence")
    if list(ridge_grid or []) != expected_grid:
        errors.append("ridge_grid_mismatch")
    if not isinstance(cv, dict) or set(cv) != expected_keys:
        errors.append("cv_loss_schema_mismatch")
    if not isinstance(inner, dict) or set(inner) != expected_keys:
        errors.append("inner_cv_schema_mismatch")
    eligible: list[float] = []
    if isinstance(cv, dict) and isinstance(inner, dict) and set(cv) == expected_keys and set(inner) == expected_keys:
        for ridge in expected_grid:
            key = str(ridge)
            records = inner[key]
            if not isinstance(records, list) or len(records) != 3:
                errors.append(f"invalid_inner_cv_records:{key}")
                continue
            record_passes = []
            fold_losses = []
            validation_rows = []
            for fold, record in enumerate(records):
                if not isinstance(record, dict) or set(record) != {
                    "fold", "training_rows", "validation_rows", "training_games", "validation_games",
                    "converged", "stop_reason", "projected_kkt_norm", "projected_kkt_tolerance",
                    "projected_kkt_pass", "iterations", "finite_validation_probability",
                    "finite_validation_loss", "fold_logloss", "solver_audit",
                }:
                    errors.append(f"invalid_inner_cv_record_schema:{key}:{fold}")
                    record_passes.append(False)
                    fold_losses.append(float("inf"))
                    validation_rows.append(0)
                    continue
                try:
                    norm = float(record["projected_kkt_norm"])
                    loss = float(record["fold_logloss"])
                    counts_ok = all(
                        isinstance(record[name], int) and not isinstance(record[name], bool) and record[name] > 0
                        for name in ("training_rows", "validation_rows", "training_games", "validation_games")
                    )
                    iterations_ok = (
                        isinstance(record["iterations"], int) and not isinstance(record["iterations"], bool)
                        and 1 <= record["iterations"] <= 300
                    )
                    kkt_consistent = (
                        math.isfinite(norm) and norm >= 0.0
                        and record["projected_kkt_tolerance"] == 1e-7
                        and isinstance(record["projected_kkt_pass"], bool)
                        and record["projected_kkt_pass"] == (norm <= 1e-7)
                    )
                    finite_flags = all(isinstance(record[name], bool) for name in (
                        "converged", "finite_validation_probability", "finite_validation_loss",
                    ))
                    passed = (
                        counts_ok and iterations_ok and kkt_consistent and finite_flags
                        and record["converged"] is True
                        and record["stop_reason"] == "projected_kkt"
                        and record["projected_kkt_pass"] is True
                        and record["finite_validation_probability"] is True
                        and record["finite_validation_loss"] is True
                        and math.isfinite(loss)
                    )
                    solver_audit = record.get("solver_audit")
                    if solver_audit is None:
                        errors.append(f"missing_inner_solver_audit:{key}:{fold}")
                        passed = False
                    else:
                        if set(solver_audit) != {
                            "optimizer", "pcg_residual_rule", "pcg_iteration_cap_rule",
                            "pcg_shift_schedule", "pcg_preconditioner", "armijo_c1",
                            "last_damping", "total_backtracks", "contrast_audit",
                        }:
                            errors.append(f"inner_solver_audit_schema:{key}:{fold}")
                        solver_errors = _newton_pcg_solver_audit_errors(
                            solver_audit, f"inner:{key}:{fold}"
                        )
                        errors.extend(solver_errors)
                        passed = passed and not solver_errors
                        try:
                            audits = solver_audit["contrast_audit"]
                            audit_kkt = max(float(audit["raw_kkt_final"]) for audit in audits)
                            audit_iterations = max(len(audit["objective_history"]) - 1 for audit in audits)
                            if not math.isclose(norm, audit_kkt, rel_tol=1e-12, abs_tol=1e-12):
                                errors.append(f"inner_solver_kkt_mismatch:{key}:{fold}")
                                passed = False
                            if int(record["iterations"]) != audit_iterations:
                                errors.append(f"inner_solver_iteration_mismatch:{key}:{fold}")
                                passed = False
                        except (KeyError, TypeError, ValueError, OverflowError):
                            errors.append(f"inner_solver_summary_mismatch:{key}:{fold}")
                            passed = False
                    if record["converged"] is True and (
                        record["stop_reason"] != "projected_kkt" or record["projected_kkt_pass"] is not True
                    ):
                        errors.append(f"inner_cv_false_convergence:{key}:{fold}")
                    if record["finite_validation_loss"] != math.isfinite(loss):
                        errors.append(f"inner_cv_loss_flag_mismatch:{key}:{fold}")
                    record_passes.append(passed)
                    fold_losses.append(loss)
                    validation_rows.append(int(record["validation_rows"]))
                except (KeyError, TypeError, ValueError, OverflowError):
                    errors.append(f"invalid_inner_cv_record_values:{key}:{fold}")
                    record_passes.append(False)
                    fold_losses.append(float("inf"))
                    validation_rows.append(0)
            try:
                loss = float(cv[key])
            except (TypeError, ValueError, OverflowError):
                errors.append(f"invalid_cv_loss:{key}")
                continue
            if all(record_passes):
                if not math.isfinite(loss):
                    errors.append(f"eligible_ridge_nonfinite:{key}")
                else:
                    eligible.append(float(ridge))
                    pooled_loss = sum(
                        fold_loss * count for fold_loss, count in zip(fold_losses, validation_rows)
                    ) / sum(validation_rows)
                    if not math.isclose(loss, pooled_loss, rel_tol=1e-12, abs_tol=1e-12):
                        errors.append(f"cv_pooled_loss_mismatch:{key}")
            elif not (math.isinf(loss) and loss > 0):
                errors.append(f"ineligible_ridge_has_finite_loss:{key}")
    serialized_eligible = fit.get("eligible_ridges")
    if not isinstance(serialized_eligible, list) or serialized_eligible != eligible:
        errors.append("eligible_ridges_mismatch")
    try:
        selected = float(fit["selected_ridge"])
        final_ridge = float(fit["ridge"])
        if not eligible or selected not in eligible:
            errors.append("selected_ridge_ineligible")
        else:
            ridge_keys = {float(ridge): str(ridge) for ridge in expected_grid}
            expected_selected = min(eligible, key=lambda ridge: (float(cv[ridge_keys[ridge]]), -ridge))
            if selected != expected_selected:
                errors.append("selected_ridge_not_cv_minimum")
        if final_ridge != selected:
            errors.append("final_ridge_selection_mismatch")
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append("missing_or_invalid_selected_ridge")
    if fit.get("selection") != (
        "three_fold_sha256_game_id; minimum pooled validation-decision logloss; "
        "exact ties choose larger ridge"
    ):
        errors.append("selection_rule_mismatch")
    if fit.get("ridge_tie_rule") != "minimum pooled validation-decision logloss; exact ties choose larger ridge":
        errors.append("ridge_tie_rule_mismatch")
    return errors


def decision_comparator_probabilities(
    payload: dict[str, Any],
    observation: dict[str, Any],
    *,
    master_seed: int = 20260815,
    draws: int = 256,
    population: OpponentPopulation | None = None,
) -> tuple[float, float]:
    """Mirror neutral and operational-v1 decision behavior without refitting."""

    if draws != 256:
        raise ValueError("prospective Model-B decision validation fixes draws at 256")
    family, role = str(observation["family"]), str(observation["role"])
    channel = str(observation["channel"])
    x = observation.get("x")
    population = population or OpponentPopulation(payload)
    identity = str(observation.get("decision_id") or observation.get("game_id"))
    rng = random.Random(_subseed(master_seed, identity, family, channel, "decision_v1"))
    neutral_config: dict[str, Any] = {}
    if family == "bargaining":
        if x is None:
            raise ValueError("bargaining decision requires responder-share x")
        neutral_threshold = _policy_value(
            family, role, "accept_threshold", {}, neutral_config, "historical_imitator", sampler_kind="joint"
        )
        neutral = float(float(x) >= neutral_threshold)
        accepted = 0
        for index in range(draws):
            archetype = ARCHETYPES[index % len(ARCHETYPES)]
            params = population.parameters(family, archetype, rng, role=role)
            threshold = _policy_value(
                family, role, "accept_threshold", params, neutral_config, archetype, sampler_kind="v1"
            )
            accepted += int(float(x) >= threshold)
        return neutral, accepted / draws
    if family == "negotiation":
        if x is None:
            raise ValueError("negotiation decision requires normalized-own-gain x")
        neutral = float(float(x) >= 0.02)
        accepted = 0
        for index in range(draws):
            archetype = ARCHETYPES[index % len(ARCHETYPES)]
            params = population.parameters(family, archetype, rng, role=role)
            threshold = _policy_value(
                family, role, "accept_margin", params, neutral_config, archetype, sampler_kind="v1"
            )
            accepted += int(float(x) >= threshold)
        return neutral, accepted / draws
    if family == "persuasion":
        parameter = {
            "persuasion|seller_high": "honesty", "persuasion|seller_low": "yes_on_low_rate",
            "persuasion|buyer_yes": "trust_prior", "persuasion|buyer_no": "buy_after_no_rate",
        }.get(channel)
        if parameter is None:
            raise ValueError(f"unknown persuasion response channel {channel!r}")
        neutral = _policy_value(
            family, role, parameter, {}, neutral_config, "historical_imitator", sampler_kind="joint"
        )
        total = 0.0
        for index in range(draws):
            archetype = ARCHETYPES[index % len(ARCHETYPES)]
            params = population.parameters(family, archetype, rng, role=role)
            total += _policy_value(
                family, role, parameter, params, neutral_config, archetype, sampler_kind="v1"
            )
        return neutral, total / draws
    raise ValueError(f"unknown decision family {family!r}")


def score_crossfit_decisions(
    observations: Iterable[dict[str, Any]],
    router: CrossfitRouter,
    *,
    master_seed: int = 20260815,
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Route OOF decisions once and generate paired predictive-loss rows."""

    materialized = [dict(row) for row in observations]
    identities = [str(row.get("decision_id") or "") for row in materialized]
    if any(not identity for identity in identities):
        raise ValueError("every OOF decision requires a stable decision_id")
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate OOF decision row")
    populations: dict[str, OpponentPopulation] = {}
    provenance_cache: dict[tuple[str, str], list[str]] = {}
    folds = range(fold_count(getattr(router, "axis", "config")))
    per_fold: dict[int, list[dict[str, Any]]] = {fold: [] for fold in folds}
    eligible: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"decisions": 0, "game_ids": set()})
    for observation in materialized:
        routed = router.route(observation)
        family, channel = str(observation["family"]), str(observation["channel"])
        cell = eligible[(family, channel)]
        cell["decisions"] += 1
        cell["game_ids"].add(str(observation["game_id"]))
        fit = ((routed.payload.get("joint_model") or {}).get("response_estimators") or {}).get(family)
        if not fit:
            cell.setdefault("provenance_errors", set()).add("missing_response_fit")
            continue
        provenance_key = (routed.sha256, family)
        fit_errors = provenance_cache.get(provenance_key)
        if fit_errors is None:
            fit_errors = response_fit_provenance_errors(fit)
            provenance_cache[provenance_key] = fit_errors
        if fit_errors:
            cell.setdefault("provenance_errors", set()).update(fit_errors)
            continue
        try:
            probability = response_probability(
                fit, channel=channel, player_model=str(observation["player_model"]),
                signature=str(observation["config_signature"]), x=observation.get("x"),
            )
        except ValueError:
            continue
        population = populations.get(routed.sha256)
        if population is None:
            population = OpponentPopulation(routed.payload)
            populations[routed.sha256] = population
        neutral, v1 = decision_comparator_probabilities(
            routed.payload, observation, master_seed=master_seed, population=population,
        )
        scored = score_oof_decision(
            outcome=observation["outcome"], model_b_probability=probability,
            neutral_probability=neutral, v1_probability=v1,
        )
        support = (fit.get("channel_support") or {}).get(channel) or {}
        try:
            support_complete = all(int(support.get(name, 0)) > 0 for name in (
                "rows", "games", "models", "config_signatures",
            ))
        except (TypeError, ValueError, OverflowError):
            support_complete = False
        if not support_complete:
            cell.setdefault("provenance_errors", set()).add("invalid_channel_support")
        provenance_complete = support_complete
        threshold_in_domain = True
        if family in {"bargaining", "negotiation"}:
            threshold, threshold_provenance = response_parameter(
                fit, channel=channel, player_model=str(observation["player_model"]),
                signature=str(observation["config_signature"]),
            )
            threshold_in_domain = (
                threshold is not None and math.isfinite(float(threshold))
                and threshold_provenance.get("parameter_kind") == "p50_threshold"
                and math.isfinite(float(threshold_provenance.get("raw_threshold", float("nan"))))
                and float(threshold_provenance["fit_min"]) <= float(threshold) <= float(threshold_provenance["fit_max"])
            )
        per_fold[routed.fold].append({
            **observation, **scored, "model_b_probability": probability,
            "neutral_probability": neutral, "v1_probability": v1,
            "outer_fold": routed.fold, "crossfit_artifact_sha256": routed.sha256,
            "crossfit_manifest_sha256": router.manifest["manifest_sha256"],
            "provenance_complete": provenance_complete,
            "response_provenance_errors": ([] if support_complete else ["invalid_channel_support"]),
            "converged": bool(fit.get("converged")),
            "in_domain": (
                math.isfinite(probability) and 0.0 <= probability <= 1.0 and threshold_in_domain
            ),
        })
    pooled = [row for fold in folds for row in per_fold[fold]]
    serialized_eligible = {}
    for key, cell in eligible.items():
        serialized_eligible[key] = dict(cell)
        serialized_eligible[key]["provenance_errors"] = sorted(cell.get("provenance_errors", set()))
    return pooled, serialized_eligible


_REQUIRED_DECISION_CHANNELS = {
    "bargaining": ("bargaining|player_1", "bargaining|player_2"),
    "negotiation": ("negotiation|seller", "negotiation|buyer"),
    "persuasion": ("persuasion|seller_high", "persuasion|seller_low",
                    "persuasion|buyer_yes", "persuasion|buyer_no"),
}


def _calibration_intercept_slope(rows: Sequence[dict[str, Any]]) -> dict[str, float] | None:
    """Unpenalized logistic recalibration diagnostic; never used for selection."""

    if not rows or len({int(bool(row["outcome"])) for row in rows}) < 2:
        return None
    xs = [math.log(min(1 - 1e-15, max(1e-15, float(row["model_b_probability"]))) /
                   (1 - min(1 - 1e-15, max(1e-15, float(row["model_b_probability"]))))) for row in rows]
    ys = [int(bool(row["outcome"])) for row in rows]
    intercept, slope = 0.0, 1.0
    for _ in range(50):
        probabilities = [1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, intercept + slope * x)))) for x in xs]
        g0 = sum(y - p for y, p in zip(ys, probabilities))
        g1 = sum((y - p) * x for y, p, x in zip(ys, probabilities, xs))
        w = [p * (1.0 - p) for p in probabilities]
        h00 = sum(w)
        h01 = sum(weight * x for weight, x in zip(w, xs))
        h11 = sum(weight * x * x for weight, x in zip(w, xs))
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-15:
            return {"intercept": intercept, "slope": slope}
        delta0 = (h11 * g0 - h01 * g1) / determinant
        delta1 = (-h01 * g0 + h00 * g1) / determinant
        intercept += delta0
        slope += delta1
        if max(abs(delta0), abs(delta1)) < 1e-10:
            break
    return {"intercept": intercept, "slope": slope}


def summarize_oof_decisions(
    rows: Sequence[dict[str, Any]],
    *,
    axis: str,
    eligible: dict[tuple[str, str], dict[str, Any]],
    bootstrap_seed: int = 20260815,
    replicates: int = 2000,
) -> dict[str, Any]:
    """Apply every preregistered OOF binary-decision requirement by channel."""

    if axis not in {"model", "config"}:
        raise ValueError("axis must be model or config")
    cluster_key = "player_model" if axis == "model" else "config_signature"
    output: dict[str, Any] = {"axis": axis, "cluster_key": cluster_key, "cells": {}}
    for family, channels in _REQUIRED_DECISION_CHANNELS.items():
        for channel in channels:
            key = (family, channel)
            cell_rows = [dict(row) for row in rows if (row.get("family"), row.get("channel")) == key]
            cell_name = channel
            eligible_cell = eligible.get(key) or {}
            eligible_decisions = int(eligible_cell.get("decisions", 0))
            eligible_games = {str(item) for item in eligible_cell.get("game_ids", [])}
            fit_provenance_errors = sorted(str(item) for item in eligible_cell.get("provenance_errors", []))
            reached_games = {str(row["game_id"]) for row in cell_rows}
            decision_reach = len(cell_rows) / eligible_decisions if eligible_decisions else 0.0
            game_reach = len(reached_games) / len(eligible_games) if eligible_games else 0.0
            clusters = len({str(row[cluster_key]) for row in cell_rows})
            folds = fold_count("actor" if axis == "model" else "config")
            fold_cluster_counts = {
                str(fold): len({
                    str(row[cluster_key]) for row in cell_rows
                    if int(row.get("outer_fold", -1)) == fold
                })
                for fold in range(folds)
            }
            required_clusters = 12 if axis == "model" else 20
            provenance_ok = not fit_provenance_errors and bool(cell_rows) and all(
                bool(row.get("provenance_complete")) and bool(row.get("converged"))
                and bool(row.get("in_domain", True)) for row in cell_rows
            )
            cell: dict[str, Any] = {
                "decisions": len(cell_rows), "games": len(reached_games), "clusters": clusters,
                "eligible_decisions": eligible_decisions, "eligible_games": len(eligible_games),
                "decision_reach": decision_reach, "game_reach": game_reach,
                "outer_fold_cluster_counts": fold_cluster_counts,
                "required_overall_clusters": required_clusters,
                "required_clusters_per_fold": 3,
                "provenance_complete": provenance_ok,
                "fit_provenance_errors": fit_provenance_errors,
                "calibration": _calibration_intercept_slope(cell_rows),
            }
            support_ok = (
                len(reached_games) >= 25 and clusters >= required_clusters
                and all(count >= 3 for count in fold_cluster_counts.values())
                and decision_reach >= 0.50 and game_reach >= 0.50 and provenance_ok
            )
            if not support_ok:
                cell.update({"reportable": False, "passed": False, "reason": "decision_support_or_reach_failed"})
                output["cells"][cell_name] = cell
                continue
            metrics = {}
            passed = True
            for comparator in ("neutral", "v1"):
                logloss = cluster_bootstrap_mean(
                    cell_rows, f"{comparator}_log_loss_delta", cluster_key=cluster_key,
                    seed=_subseed(bootstrap_seed, axis, family, channel, comparator, "logloss"),
                    replicates=replicates,
                )
                brier = cluster_bootstrap_mean(
                    cell_rows, f"{comparator}_brier_delta", cluster_key=cluster_key,
                    seed=_subseed(bootstrap_seed, axis, family, channel, comparator, "brier"),
                    replicates=replicates,
                )
                metrics[comparator] = {"log_loss_delta": logloss, "brier_delta": brier}
                passed = passed and (
                    logloss["mean"] < 0.0 and logloss["ci_high"] < 0.0
                    and brier["mean"] < 0.0 and brier["ci_high"] <= 0.0
                )
            cell.update({"reportable": True, "passed": passed, "comparators": metrics})
            output["cells"][cell_name] = cell
    output["all_cells_passed"] = all(cell["passed"] for cell in output["cells"].values())
    return output


def _subseed(master_seed: int, *parts: Any) -> int:
    material = "|".join([str(master_seed), *(str(part) for part in parts)])
    return int(hashlib.sha256(material.encode("utf-8")).hexdigest()[:16], 16)


def _policy_value(
    family: str,
    role: str,
    name: str,
    parameters: dict[str, Any],
    config: dict[str, Any],
    archetype: str,
    *,
    sampler_kind: str,
) -> float:
    """The value the current opponent policy consumes, including its defaults."""

    if name in parameters:
        return float(parameters[name])
    joint = sampler_kind in {"joint", "conditional_shuffle"}
    if family == "bargaining":
        target_defaults = {
            "aggressive_extractor": 0.75,
            "fairness_sensitive": 0.52,
            "reciprocal": 0.52,
            "conceding": 0.48,
            "random": 0.60,
        }
        target = float(parameters.get("target_share", 0.58 if joint else target_defaults.get(archetype, 0.58)))
        return {
            "target_share": target,
            "concession_rate": 0.04,
            "accept_threshold": max(0.35, 1.0 - target - 0.05),
            "action_noise": 0.0,
        }[name]
    if family == "negotiation":
        if name == "concession_rate":
            return 0.04
        if name == "accept_margin":
            return 0.02
        if name == "action_noise":
            return 0.0
        if name == "aspiration_price":
            return float(config.get("buyer_value" if role == "seller" else "seller_value", 1.1 if role == "seller" else 0.7))
    if family == "persuasion":
        if name == "buy_after_no_rate":
            return 0.022
        if name == "honesty":
            return 0.6 if joint else 0.2 if archetype == "deceptive" else 0.9 if archetype in {"rational"} else 0.6
        if name == "yes_on_low_rate":
            return 1.0 - _policy_value(
                family, role, "honesty", parameters, config, archetype, sampler_kind=sampler_kind
            )
        if name == "trust_prior":
            return 0.55 if joint else 0.8 if archetype == "conceding" else 0.25 if archetype == "adaptive" else 0.55
    raise KeyError(f"no policy value for {family}.{role}.{name}")


def predictive_draws(
    payload: dict[str, Any],
    observed_bundle: dict[str, Any],
    names: Sequence[str],
    *,
    master_seed: int = 20260815,
    draws: int = 256,
    population: OpponentPopulation | None = None,
    pool_cache: dict[tuple[str, str, str, str], tuple[list[dict[str, Any]], list[int], int, str]] | None = None,
) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]], list[tuple[float, ...]], list[str], int]:
    """Draw Model B and the v1 comparator through their production semantics."""

    if draws != 256:
        raise ValueError("prospective Model-B validation fixes draws at 256")
    population = population or OpponentPopulation(payload)
    pool_cache = pool_cache if pool_cache is not None else {}
    family = str(observed_bundle["family"])
    role = str(observed_bundle["role"])
    config = dict(observed_bundle.get("configuration") or {})
    bundle_id = str(observed_bundle["bundle_id"])
    joint_rng = random.Random(_subseed(master_seed, bundle_id, "joint"))
    shuffled_rng = random.Random(_subseed(master_seed, bundle_id, "conditional_shuffle"))
    independent_rng = random.Random(_subseed(master_seed, bundle_id, "independent"))
    joint: list[tuple[float, ...]] = []
    shuffled: list[tuple[float, ...]] = []
    independent: list[tuple[float, ...]] = []
    fallback_levels: list[str] = []
    neutral_defaults = 0

    exact = config_signature(family, config)
    coarse = config_signature(family, config, coarse=True)
    cache_key = (family, role, exact, coarse)
    cached = pool_cache.get(cache_key)
    if cached is None:
        role_bundles = [
            bundle for bundle in (population.joint_bundles.get(family) or [])
            if bundle.get("role") == role
        ]
        eligible = [bundle for bundle in role_bundles if bundle.get("config_signature") == exact]
        fallback_level = "exact"
        if not eligible:
            eligible = [bundle for bundle in role_bundles if bundle.get("coarse_config_signature") == coarse]
            fallback_level = "coarse"
        if not eligible:
            eligible = role_bundles
            fallback_level = "role"
        if not eligible:
            raise ValueError(f"no joint bundle available for {family}/{role}")
        cumulative = []
        total = 0
        for bundle in eligible:
            total += max(1, int(bundle.get("weight", 1)))
            cumulative.append(total)
        cached = (eligible, cumulative, total, fallback_level)
        pool_cache[cache_key] = cached
    eligible, cumulative, total, fallback_level = cached

    def cached_bundle(rng: random.Random) -> dict[str, Any]:
        # Equivalent to random.choices(..., weights=..., k=1), without rebuilding
        # the same eligible pool and cumulative weights for every parameter draw.
        selected = dict(eligible[bisect.bisect(cumulative, rng.random() * total)])
        selected["draw_fallback_level"] = fallback_level
        percentile = float(selected.get("latent_percentile", 0.5))
        selected["derived_archetype"] = min(
            population.bands or {"historical_imitator": (0.25, 0.75)},
            key=lambda name: abs(percentile - sum(population.band(name)) / 2),
        )
        return selected
    for index in range(draws):
        selected = cached_bundle(joint_rng)
        joint_params = dict(selected.get("parameters") or {})
        neutral_defaults += sum(name not in joint_params for name in names)
        joint_archetype = str(selected["derived_archetype"])
        joint.append(tuple(_policy_value(
            family, role, name, joint_params, config, joint_archetype, sampler_kind="joint"
        ) for name in names))
        fallback_levels.append(str(selected["draw_fallback_level"]))

        # Same conditional pool, fallback ladder, empirical weights, and policy
        # defaults as Model B, but a separate bundle draw for each parameter.
        shuffled_values = []
        for name in names:
            marginal_bundle = cached_bundle(shuffled_rng)
            fallback_levels.append(str(marginal_bundle["draw_fallback_level"]))
            marginal_params = dict(marginal_bundle.get("parameters") or {})
            neutral_defaults += int(name not in marginal_params)
            marginal_archetype = str(marginal_bundle["derived_archetype"])
            shuffled_values.append(_policy_value(
                family, role, name, marginal_params, config, marginal_archetype,
                sampler_kind="conditional_shuffle",
            ))
        shuffled.append(tuple(shuffled_values))

        # Exactly sixteen draws per production v1 archetype label.
        archetype = ARCHETYPES[index % len(ARCHETYPES)]
        marginal = population.parameters(family, archetype, independent_rng, role=role)
        independent.append(tuple(_policy_value(
            family, role, name, marginal, config, archetype, sampler_kind="v1"
        ) for name in names))
    return joint, shuffled, independent, fallback_levels, neutral_defaults


def fit_marginals(payload: dict[str, Any]) -> dict[tuple[str, str, str], tuple[float, ...]]:
    """Raw FIT-bundle marginals used only to put validation metrics on rank scale."""

    values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for family, bundles in (payload.get("joint_bundles") or {}).items():
        for bundle in bundles:
            for name, value in (bundle.get("parameters") or {}).items():
                values[(str(family), str(bundle.get("role")), str(name))].append(float(value))
    return {key: tuple(sorted(items)) for key, items in values.items()}


def score_observed_bundle(
    payload: dict[str, Any],
    observed_bundle: dict[str, Any],
    *,
    master_seed: int = 20260815,
    population: OpponentPopulation | None = None,
    pool_cache: dict[tuple[str, str, str, str], tuple[list[dict[str, Any]], list[int], int, str]] | None = None,
    references: dict[tuple[str, str, str], tuple[float, ...]] | None = None,
) -> dict[str, Any] | None:
    """Score one supported raw holdout bundle without learning from it."""

    if int(observed_bundle.get("game_count", 0)) < 2:
        return None
    family = str(observed_bundle["family"])
    role = str(observed_bundle["role"])
    game_counts = observed_bundle.get("parameter_game_counts") or {}
    references = references or fit_marginals(payload)
    names = sorted(
        name for name in (observed_bundle.get("parameters") or {})
        if (family, role, name) in references and int(game_counts.get(name, 0)) >= 2
    )
    if len(names) < 2:
        return None
    marginal_map = {name: references[(family, role, name)] for name in names}
    observed = transform_parameters(observed_bundle["parameters"], marginal_map, names)
    joint_raw, shuffled_raw, independent_raw, levels, neutral_defaults = predictive_draws(
        payload, observed_bundle, names, master_seed=master_seed,
        population=population, pool_cache=pool_cache,
    )
    support_counts = {"v2": 0, "v1": 0}
    nonfinite_counts = {"v2": 0, "v1": 0}
    for sampler, collection in (("v2", joint_raw), ("v2", shuffled_raw), ("v1", independent_raw)):
        for draw in collection:
            for name, value in zip(names, draw):
                if not math.isfinite(value):
                    nonfinite_counts[sampler] += 1
                reference = marginal_map[name]
                if value < min(reference) or value > max(reference):
                    support_counts[sampler] += 1
    joint = [tuple(empirical_cdf(value, marginal_map[name]) for name, value in zip(names, draw)) for draw in joint_raw]
    shuffled = [tuple(empirical_cdf(value, marginal_map[name]) for name, value in zip(names, draw)) for draw in shuffled_raw]
    independent = [tuple(empirical_cdf(value, marginal_map[name]) for name, value in zip(names, draw)) for draw in independent_raw]
    joint_energy = energy_score(observed, joint)
    shuffled_energy = energy_score(observed, shuffled)
    independent_energy = energy_score(observed, independent)
    joint_crps = [crps(observed[index], [draw[index] for draw in joint]) for index in range(len(names))]
    shuffled_crps = [crps(observed[index], [draw[index] for draw in shuffled]) for index in range(len(names))]
    independent_crps = [crps(observed[index], [draw[index] for draw in independent]) for index in range(len(names))]
    scored: dict[str, Any] = {
        "joint_energy": joint_energy,
        "independent_energy": shuffled_energy,
        "energy_delta": joint_energy - shuffled_energy,
        "marginal_crps_deltas": [left - right for left, right in zip(joint_crps, shuffled_crps)],
        "operational_v1_energy_delta": joint_energy - independent_energy,
        "operational_v1_marginal_crps_deltas": [
            left - right for left, right in zip(joint_crps, independent_crps)
        ],
    }
    def moments(draws: Sequence[Sequence[float]]) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        for left in range(len(names)):
            for right in range(left + 1, len(names)):
                key = f"{names[left]}|{names[right]}"
                xs = [draw[left] for draw in draws]
                ys = [draw[right] for draw in draws]
                result[key] = {
                    "mean_x": sum(xs) / len(xs), "mean_y": sum(ys) / len(ys),
                    "mean_x2": sum(x * x for x in xs) / len(xs),
                    "mean_y2": sum(y * y for y in ys) / len(ys),
                    "mean_xy": sum(x * y for x, y in zip(xs, ys)) / len(xs),
                }
        return result
    scored.update({
        "bundle_id": observed_bundle["bundle_id"],
        "family": family,
        "role": role,
        "player_model": observed_bundle["player_model"],
        "config_id": observed_bundle["config_id"],
        "config_signature": observed_bundle["config_signature"],
        "game_ids": list(observed_bundle.get("game_ids") or []),
        "parameter_names": names,
        "observed_rank_values": dict(zip(names, observed)),
        "predictive_moments": {
            "whole_bundle": moments(joint),
            "conditional_shuffle": moments(shuffled),
            "operational_v1": moments(independent),
        },
        "fallback_levels": dict((level, levels.count(level)) for level in sorted(set(levels))),
        "v2_neutral_default_values": neutral_defaults,
        "v2_requested_parameter_values": 2 * 256 * len(names),
        "mean_marginal_crps_delta": sum(scored["marginal_crps_deltas"]) / len(names),
        "mean_operational_v1_marginal_crps_delta": (
            sum(scored["operational_v1_marginal_crps_deltas"]) / len(names)
        ),
        "support_violations": support_counts["v2"],
        "nonfinite_draws": nonfinite_counts["v2"],
        "operational_v1_support_violations": support_counts["v1"],
        "operational_v1_nonfinite_draws": nonfinite_counts["v1"],
    })
    return scored


def summarize_validation(
    scored_rows: Sequence[dict[str, Any]],
    *,
    axis: str,
    bootstrap_seed: int = 20260815,
    replicates: int = 2000,
    eligible_game_ids_by_family: dict[str, set[str]] | None = None,
    crossfit: bool = False,
) -> dict[str, Any]:
    """Apply the prospectively declared six-cell verdict rules."""

    if axis not in {"model", "config"}:
        raise ValueError("axis must be model or config")
    cluster_key = "player_model" if axis == "model" else "config_signature"
    report: dict[str, Any] = {"axis": axis, "cluster_key": cluster_key, "families": {}}

    def dependence_diagnostics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for role in sorted({row["role"] for row in rows}):
            role_rows = [row for row in rows if row["role"] == role]
            pairs = sorted({pair for row in role_rows for pair in row["predictive_moments"]["whole_bundle"]})
            output[role] = {}
            for pair in pairs:
                left, right = pair.split("|", 1)
                usable = [row for row in role_rows if left in row["observed_rank_values"] and right in row["observed_rank_values"]]
                if len(usable) < 2:
                    continue
                ox = [row["observed_rank_values"][left] for row in usable]
                oy = [row["observed_rank_values"][right] for row in usable]

                def from_raw(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
                    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
                    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
                    vx = sum((x - mx) ** 2 for x in xs) / len(xs)
                    vy = sum((y - my) ** 2 for y in ys) / len(ys)
                    corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0
                    return cov, corr

                observed_cov, observed_corr = from_raw(ox, oy)
                item: dict[str, Any] = {"bundles": len(usable), "observed_covariance": observed_cov,
                                        "observed_correlation": observed_corr, "samplers": {}}
                for sampler in ("whole_bundle", "conditional_shuffle", "operational_v1"):
                    ms = [row["predictive_moments"][sampler][pair] for row in usable]
                    mx = sum(m["mean_x"] for m in ms) / len(ms)
                    my = sum(m["mean_y"] for m in ms) / len(ms)
                    cov = sum(m["mean_xy"] for m in ms) / len(ms) - mx * my
                    vx = sum(m["mean_x2"] for m in ms) / len(ms) - mx * mx
                    vy = sum(m["mean_y2"] for m in ms) / len(ms) - my * my
                    corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else 0.0
                    item["samplers"][sampler] = {
                        "covariance": cov, "correlation": corr,
                        "absolute_covariance_error": abs(cov - observed_cov),
                        "absolute_correlation_error": abs(corr - observed_corr),
                    }
                output[role][pair] = item
        return output
    for family in ("bargaining", "negotiation", "persuasion"):
        rows = [dict(row) for row in scored_rows if row["family"] == family]
        clusters = len({row[cluster_key] for row in rows})
        fold_cluster_counts = {
            str(fold): len({row[cluster_key] for row in rows if int(row.get("outer_fold", -1)) == fold})
            for fold in range(fold_count("actor" if axis == "model" else "config"))
        } if crossfit else {}
        scored_games = {str(game_id) for row in rows for game_id in row.get("game_ids", [])}
        eligible_games = set((eligible_game_ids_by_family or {}).get(family, set()))
        retention = len(scored_games) / len(eligible_games) if eligible_games else 0.0
        expected_roles = {
            "bargaining": ("player_1", "player_2"),
            "negotiation": ("seller", "buyer"),
            "persuasion": ("seller", "buyer"),
        }[family]
        role_counts = {role: sum(row["role"] == role for row in rows) for role in expected_roles}
        fallback_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            for level, count in row.get("fallback_levels", {}).items():
                fallback_counts[level] += int(count)
        fallback_total = sum(fallback_counts.values())
        role_fallback_rate = fallback_counts.get("role", 0) / fallback_total if fallback_total else 1.0
        default_values = sum(int(row.get("v2_neutral_default_values", 0)) for row in rows)
        requested_values = sum(int(row.get("v2_requested_parameter_values", 0)) for row in rows)
        default_rate = default_values / requested_values if requested_values else 1.0
        coverage_ok = (
            retention >= 0.50
            and role_counts and all(count >= 25 for count in role_counts.values())
            and role_fallback_rate <= (0.25 if axis == "model" else 0.50)
            and default_rate <= 0.25
            and (axis != "config" or fallback_counts.get("exact", 0) == 0)
        )
        cell: dict[str, Any] = {
            "bundles": len(rows), "clusters": clusters, "role_bundle_counts": role_counts,
            "scored_games": len(scored_games), "eligible_games": len(eligible_games),
            "game_retention": retention, "fallback_counts": dict(fallback_counts),
            "role_fallback_rate": role_fallback_rate, "neutral_default_rate": default_rate,
            "dependence_diagnostics": dependence_diagnostics(rows),
        }
        if crossfit:
            required_clusters = 12 if axis == "model" else 20
            cluster_ok = clusters >= required_clusters and all(count >= 3 for count in fold_cluster_counts.values())
            cell.update({
                "outer_fold_cluster_counts": fold_cluster_counts,
                "required_overall_clusters": required_clusters,
                "required_clusters_per_fold": 3,
            })
        else:
            cluster_ok = clusters >= 5
        if not cluster_ok or not coverage_ok:
            reason = "crossfit_cluster_floor_failed" if crossfit and not cluster_ok else (
                "fewer_than_5_split_unit_clusters" if not cluster_ok else "prospective_coverage_rule_failed"
            )
            cell.update({"reportable": False, "passed": False, "reason": reason})
            report["families"][family] = cell
            continue
        energy = cluster_bootstrap_mean(rows, "energy_delta", cluster_key=cluster_key,
                                        seed=_subseed(bootstrap_seed, axis, family, "energy"), replicates=replicates)
        marginal = cluster_bootstrap_mean(rows, "mean_marginal_crps_delta", cluster_key=cluster_key,
                                          seed=_subseed(bootstrap_seed, axis, family, "marginal"), replicates=replicates)
        operational_energy = cluster_bootstrap_mean(
            rows, "operational_v1_energy_delta", cluster_key=cluster_key,
            seed=_subseed(bootstrap_seed, axis, family, "operational_energy"), replicates=replicates,
        )
        operational_marginal = cluster_bootstrap_mean(
            rows, "mean_operational_v1_marginal_crps_delta", cluster_key=cluster_key,
            seed=_subseed(bootstrap_seed, axis, family, "operational_marginal"), replicates=replicates,
        )
        parameter_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        operational_parameter_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            for name, value in zip(row["parameter_names"], row["marginal_crps_deltas"]):
                parameter_rows[name].append({cluster_key: row[cluster_key], "value": value})
            for name, value in zip(row["parameter_names"], row["operational_v1_marginal_crps_deltas"]):
                operational_parameter_rows[name].append({cluster_key: row[cluster_key], "value": value})
        parameters = {
            name: cluster_bootstrap_mean(values, "value", cluster_key=cluster_key,
                                         seed=_subseed(bootstrap_seed, axis, family, name), replicates=replicates)
            for name, values in sorted(parameter_rows.items())
        }
        operational_parameters = {
            name: cluster_bootstrap_mean(values, "value", cluster_key=cluster_key,
                                         seed=_subseed(bootstrap_seed, axis, family, "v1", name),
                                         replicates=replicates)
            for name, values in sorted(operational_parameter_rows.items())
        }
        violations = sum(int(row["support_violations"]) + int(row["nonfinite_draws"]) for row in rows)
        passed = (
            energy["mean"] < 0.0 and energy["ci_high"] < 0.0
            and operational_energy["mean"] < 0.0 and operational_energy["ci_high"] < 0.0
            and marginal["ci_high"] <= 0.005
            and operational_marginal["ci_high"] <= 0.005
            and all(value["mean"] <= 0.010 for value in parameters.values())
            and all(value["mean"] <= 0.010 for value in operational_parameters.values())
            and violations == 0
            and coverage_ok
        )
        cell.update({"reportable": True, "passed": passed, "energy_delta": energy,
                     "mean_marginal_crps_delta": marginal, "parameter_crps_deltas": parameters,
                     "operational_v1_energy_delta": operational_energy,
                     "mean_operational_v1_marginal_crps_delta": operational_marginal,
                     "operational_v1_parameter_crps_deltas": operational_parameters,
                     "support_or_nonfinite_violations": violations})
        report["families"][family] = cell
    report["all_families_passed"] = all(cell.get("passed") is True for cell in report["families"].values())
    return report


def score_crossfit_bundles(
    observed_bundles: Iterable[dict[str, Any]],
    router: CrossfitRouter,
    *,
    master_seed: int = 20260815,
) -> tuple[list[dict[str, Any]], dict[str, set[str]], int]:
    """Route and score each OOF bundle once, pooling only frozen predictions.

    ``CrossfitRouter`` has already verified every artifact hash for its axis and its
    training/evaluation isolation.  This function deliberately completes every
    per-fold score before returning a pooled collection.
    """

    materialized = [dict(row) for row in observed_bundles]
    identities = [str(row.get("oof_row_id") or row.get("bundle_id") or "") for row in materialized]
    if any(not identity for identity in identities):
        raise ValueError("every OOF bundle requires a stable oof_row_id or bundle_id")
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate OOF bundle row")
    contexts: dict[str, tuple[OpponentPopulation, dict[tuple[str, str, str], tuple[float, ...]], dict[Any, Any]]] = {}
    folds = range(fold_count(getattr(router, "axis", "config")))
    per_fold: dict[int, list[dict[str, Any]]] = {fold: [] for fold in folds}
    eligible_games: dict[str, set[str]] = defaultdict(set)
    unsupported = 0
    for row in materialized:
        routing_row = dict(row)
        routing_row.setdefault("game_family", row.get("family"))
        # Bundle extraction stores the acting model directly; reconstruct only
        # the role-specific routing envelope expected by CrossfitRouter.
        routing_row.setdefault("player_1_model", row.get("player_model"))
        routing_row.setdefault("player_2_model", row.get("player_model"))
        routed = router.route(routing_row)
        context = contexts.get(routed.sha256)
        if context is None:
            context = (OpponentPopulation(routed.payload), fit_marginals(routed.payload), {})
            contexts[routed.sha256] = context
        population, references, pool_cache = context
        result = score_observed_bundle(
            routed.payload, row, master_seed=master_seed, population=population,
            pool_cache=pool_cache, references=references,
        )
        family = str(row["family"])
        eligible_games[family].update(str(game_id) for game_id in row.get("game_ids", []))
        if result is None:
            unsupported += 1
            continue
        result.update({
            "outer_fold": routed.fold,
            "crossfit_artifact_sha256": routed.sha256,
            "crossfit_artifact_path": str(routed.path),
            "crossfit_manifest_sha256": router.manifest["manifest_sha256"],
        })
        per_fold[routed.fold].append(result)
    # Concatenation occurs only after all independently-routed fold lists
    # are complete, making the post-freeze pooling boundary explicit.
    pooled = [row for fold in folds for row in per_fold[fold]]
    return pooled, dict(eligible_games), unsupported


def run_validation(
    *,
    data_dir: str | Path,
    artifact_path: str | Path,
    split_mode: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Extract the declared holdout, score it once, and persist an auditable report."""

    if split_mode not in {"model", "config_signature"}:
        raise ValueError("validation split_mode must be model or config_signature")
    artifact_path = Path(artifact_path)
    raw_artifact = artifact_path.read_bytes()
    payload = json.loads(raw_artifact)
    if reference_errors := response_reference_errors(payload):
        raise ValueError(f"response estimator references rejected: {json.dumps(reference_errors, sort_keys=True)}")
    provenance = payload.get("provenance") or {}
    if provenance.get("split_mode") != split_mode or provenance.get("split") != "fit":
        raise ValueError(
            f"artifact provenance mismatch: expected {split_mode}/fit, got "
            f"{provenance.get('split_mode')}/{provenance.get('split')}"
        )
    holdout_fraction = float(provenance.get("holdout_fraction", -1.0))
    if holdout_fraction != 0.25:
        raise ValueError(f"artifact holdout_fraction must be 0.25, got {holdout_fraction}")
    if payload.get("schema_version") != 2 or not (payload.get("joint_model") or {}).get("fit_partition_only"):
        raise ValueError("validation requires a schema-v2 FIT-only joint artifact")
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    holdout_count = 0

    def holdout_events() -> Iterable[dict[str, Any]]:
        nonlocal holdout_count
        for event in iter_jsonl(events_path):
            if keeps(event, mode=split_mode, split=HOLDOUT, holdout_fraction=holdout_fraction):
                holdout_count += 1
                yield event

    raw_bundles = extract_joint_bundle_observations(holdout_events())
    actor_excluded = 0
    if split_mode == "model":
        actor_excluded = sum(not bool(row.get("actor_model_is_holdout")) for row in raw_bundles)
        raw_bundles = [row for row in raw_bundles if row.get("actor_model_is_holdout")]
        if any(not is_holdout_key(str(row["player_model"]), holdout_fraction) for row in raw_bundles):
            raise AssertionError("model validation retained a FIT actor model")
    eligible_games: dict[str, set[str]] = defaultdict(set)
    for row in raw_bundles:
        eligible_games[str(row["family"])].update(str(game_id) for game_id in row.get("game_ids", []))
    scored = []
    unsupported = 0
    population = OpponentPopulation(payload)
    references = fit_marginals(payload)
    pool_cache: dict[tuple[str, str, str, str], tuple[list[dict[str, Any]], list[int], int, str]] = {}
    print(f"phase=scoring raw_bundles={len(raw_bundles)} split={split_mode}", file=sys.stderr, flush=True)
    for index, row in enumerate(raw_bundles, start=1):
        result = score_observed_bundle(
            payload, row, population=population, pool_cache=pool_cache, references=references,
        )
        if result is None:
            unsupported += 1
        else:
            scored.append(result)
        if index % 250 == 0 or index == len(raw_bundles):
            print(
                f"phase=scoring processed={index}/{len(raw_bundles)} scored={len(scored)} "
                f"excluded={unsupported} cached_pools={len(pool_cache)}",
                file=sys.stderr, flush=True,
            )
    print("phase=bootstrap", file=sys.stderr, flush=True)
    axis = "model" if split_mode == "model" else "config"
    verdict = summarize_validation(
        scored, axis=axis, eligible_game_ids_by_family=dict(eligible_games),
    )
    report = {
        "schema_version": 1,
        "declaration": "docs/REGISTRY.md model_b_joint_opponents prospective validation endpoints",
        "data_events_path": str(events_path),
        "artifact_path": str(artifact_path),
        "artifact_sha256": hashlib.sha256(raw_artifact).hexdigest(),
        "artifact_provenance": provenance,
        "split_mode": split_mode,
        "master_seed": 20260815,
        "draws_per_sampler_per_bundle": 256,
        "bootstrap_replicates": 2000,
        "holdout_events": holdout_count,
        "raw_holdout_bundles": len(raw_bundles),
        "excluded_fit_actor_bundles": actor_excluded,
        "excluded_unsupported_bundles": unsupported,
        "scored_bundles": len(scored),
        "verdict": verdict,
        "scored_rows": scored,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# Model B validation — {split_mode}", "",
        f"- Artifact SHA-256: `{report['artifact_sha256']}`",
        f"- Holdout events: {holdout_count}",
        f"- Raw/scored bundles: {len(raw_bundles)}/{len(scored)}",
        f"- All families passed: **{verdict['all_families_passed']}**", "",
        "| Family | Bundles | Clusters | Retention | Primary energy upper | v1 energy upper | Passed |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for family, cell in verdict["families"].items():
        energy = cell.get("energy_delta", {}).get("ci_high")
        operational = cell.get("operational_v1_energy_delta", {}).get("ci_high")
        lines.append(
            f"| {family} | {cell['bundles']} | {cell['clusters']} | {cell['game_retention']:.3f} | "
            f"{energy if energy is not None else 'NA'} | {operational if operational is not None else 'NA'} | "
            f"{cell['passed']} |"
        )
    (out / "validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def run_crossfit_validation(
    *,
    data_dir: str | Path,
    manifest_path: str | Path,
    actor_artifacts: Sequence[dict[str, Any]],
    config_artifacts: Sequence[dict[str, Any]],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Route exhaustive OOF rows through every frozen artifact on both axes."""

    manifest_path = Path(manifest_path)
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    events = list(iter_jsonl(events_path))
    bundles = extract_joint_bundle_observations(events)
    decisions = extract_response_observations(events)
    axes = {
        "model": ("actor", actor_artifacts),
        "config": ("config", config_artifacts),
    }
    axis_reports: dict[str, Any] = {}
    for axis, (router_axis, specs) in axes.items():
        router = CrossfitRouter(manifest, router_axis, specs)
        reference_failures = {
            str(fold): errors for fold, artifact in sorted(router.artifacts.items())
            if (errors := response_reference_errors(artifact.payload, require_schema=True))
        }
        if reference_failures:
            raise ValueError(f"cross-fit response references rejected on {axis}: {json.dumps(reference_failures, sort_keys=True)}")
        artifact_fit_errors = {
            f"fold={fold},family={family}": errors
            for fold, artifact in sorted(router.artifacts.items())
            for family, fit in sorted(
                (((artifact.payload.get("joint_model") or {}).get("response_estimators") or {}).items())
            )
            if (errors := response_fit_provenance_errors(fit))
        }
        expected_families = {"bargaining", "negotiation", "persuasion"}
        for fold, artifact in sorted(router.artifacts.items()):
            present = set(((artifact.payload.get("joint_model") or {}).get("response_estimators") or {}))
            for missing in sorted(expected_families - present):
                artifact_fit_errors[f"fold={fold},family={missing}"] = ["missing_response_fit"]
        if artifact_fit_errors:
            raise ValueError(
                f"cross-fit response provenance rejected before scoring on {axis}: "
                f"{json.dumps(artifact_fit_errors, sort_keys=True)}"
            )
        scored_bundles, eligible_games, unsupported = score_crossfit_bundles(bundles, router)
        bundle_verdict = summarize_validation(
            scored_bundles, axis=axis, crossfit=True,
            eligible_game_ids_by_family=eligible_games,
        )
        scored_decisions, eligible_decisions = score_crossfit_decisions(decisions, router)
        decision_verdict = summarize_oof_decisions(
            scored_decisions, axis=axis, eligible=eligible_decisions,
        )
        artifacts = [router.artifacts[fold] for fold in sorted(router.artifacts)]
        axis_reports[axis] = {
            "router_axis": router_axis,
            "artifact_sha256s": {str(item.fold): item.sha256 for item in artifacts},
            "artifact_paths": {str(item.fold): str(item.path) for item in artifacts},
            "raw_oof_bundles": len(bundles),
            "scored_oof_bundles": len(scored_bundles),
            "unsupported_oof_bundles": unsupported,
            "raw_oof_decisions": len(decisions),
            "scored_oof_decisions": len(scored_decisions),
            "bundle_verdict": bundle_verdict,
            "decision_verdict": decision_verdict,
            "passed": bundle_verdict["all_families_passed"] and decision_verdict["all_cells_passed"],
            "scored_bundle_rows": scored_bundles,
            "scored_decision_rows": scored_decisions,
        }
    report = {
        "schema_version": 2,
        "declaration": (
            "docs/REGISTRY.md model_b_mixed_fold_crossfit; "
            "model_b_response_newton_pcg numerical instrument"
        ),
        "data_events_path": str(events_path),
        "manifest_path": str(manifest_path),
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "declared_manifest_sha256": manifest.get("manifest_sha256"),
        "master_seed": 20260815,
        "draws_per_sampler_per_bundle_or_decision": 256,
        "bootstrap_replicates": 2000,
        "axes": axis_reports,
        "passed": all(item["passed"] for item in axis_reports.values()),
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "crossfit_validation.json"
    temporary = out / ".crossfit_validation.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    lines = [
        "# Model B exhaustive cross-fit validation", "",
        f"- Manifest SHA-256: `{report['manifest_sha256']}`",
        f"- Overall pass: **{report['passed']}**", "",
        "| Axis | Bundle pass | Decision pass | Overall |",
        "|---|---|---|---|",
    ]
    for axis, item in axis_reports.items():
        lines.append(
            f"| {axis} | {item['bundle_verdict']['all_families_passed']} | "
            f"{item['decision_verdict']['all_cells_passed']} | {item['passed']} |"
        )
    markdown_target = out / "crossfit_validation.md"
    markdown_temporary = out / ".crossfit_validation.md.tmp"
    markdown_temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    markdown_temporary.replace(markdown_target)
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Validate Model B on frozen structural predictions.")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--artifact")
    parser.add_argument("--split-mode", choices=["model", "config_signature"])
    parser.add_argument(
        "--crossfit-spec",
        help="JSON containing manifest_path plus actor_artifacts/config_artifacts {path,sha256} lists",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    if args.crossfit_spec:
        if args.artifact or args.split_mode:
            parser.error("--crossfit-spec cannot be combined with --artifact/--split-mode")
        spec = json.loads(Path(args.crossfit_spec).read_text(encoding="utf-8"))
        report = run_crossfit_validation(
            data_dir=args.data_dir, manifest_path=spec["manifest_path"],
            actor_artifacts=spec["actor_artifacts"], config_artifacts=spec["config_artifacts"],
            output_dir=args.output_dir,
        )
        print(json.dumps({
            "manifest_sha256": report["manifest_sha256"], "passed": report["passed"],
            "axis_passes": {axis: item["passed"] for axis, item in report["axes"].items()},
        }, indent=2, sort_keys=True))
        return
    if not args.artifact or not args.split_mode:
        parser.error("one-shot validation requires --artifact and --split-mode")
    report = run_validation(data_dir=args.data_dir, artifact_path=args.artifact,
                            split_mode=args.split_mode, output_dir=args.output_dir)
    print(json.dumps({"split_mode": args.split_mode, "verdict": report["verdict"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
