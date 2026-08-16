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
from glee_eval.storage.trajectories import iter_jsonl

try:  # Optional acceleration; the bundled workspace runtime provides NumPy.
    import numpy as _np
except ImportError:  # pragma: no cover - exercised by the system Python in CI.
    _np = None


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
        provenance_complete = (
            fit.get("status") == "ok"
            and list(fit.get("ridge_grid") or []) == [0.1, 1, 10, 100]
            and all(fit.get(name) is not None for name in (
                "selected_ridge", "cv_log_loss", "selection", "converged", "iterations",
                "max_iterations", "tolerance",
            ))
            and all(int(support.get(name, 0)) > 0 for name in (
                "rows", "games", "models", "config_signatures",
            ))
        )
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
            "converged": bool(fit.get("converged")),
            "in_domain": (
                math.isfinite(probability) and 0.0 <= probability <= 1.0 and threshold_in_domain
            ),
        })
    pooled = [row for fold in folds for row in per_fold[fold]]
    return pooled, dict(eligible)


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
            provenance_ok = bool(cell_rows) and all(
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
        "declaration": "docs/REGISTRY.md model_b_crossfit_joint_opponents",
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
