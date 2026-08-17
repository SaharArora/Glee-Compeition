"""Frozen OOF scoring for the bargaining-only Model-A campaign."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from statistics import mean
from typing import Any, Iterable, Sequence

from glee_eval.diagnostics.model_a_necessity import OperationalV1Predictor
from glee_eval.population.bargaining_model_a import (
    ACTION_CLASSES,
    EPSILON,
    ROLES,
    _clip_probability,
    _quantile,
    fold_for_row,
    predict_role_model,
)
from glee_eval.response_models.runtime import EmpiricalResponseModel


BOOTSTRAP_REPLICATES = 1000
BOOTSTRAP_SEED = 20260816
CALIBRATION_BINS = 10


def empirical_crps(samples: Sequence[float], observation: float) -> float:
    ordered = sorted(float(value) for value in samples)
    if not ordered:
        raise ValueError("CRPS requires samples")
    n = len(ordered)
    first = math.fsum(abs(value - observation) for value in ordered) / n
    pair_half = math.fsum((2 * index - n + 1) * value for index, value in enumerate(ordered)) / (n * n)
    return first - pair_half


def energy_score(samples: Sequence[float], observation: float) -> float:
    return empirical_crps(samples, observation)


def categorical_log_loss(probabilities: dict[str, float], outcome: str) -> float:
    return -math.log(_clip_probability(probabilities[outcome]))


def categorical_brier(probabilities: dict[str, float], outcome: str) -> float:
    return math.fsum((float(probabilities[label]) - float(label == outcome)) ** 2 for label in ACTION_CLASSES)


def binary_log_loss(probability: float, outcome: int) -> float:
    p = _clip_probability(probability)
    return -math.log(p if outcome else 1.0 - p)


def _calibration_fit(probabilities: Sequence[float], outcomes: Sequence[int]) -> dict[str, float | None]:
    if len(probabilities) < 20 or len(set(outcomes)) < 2:
        return {"intercept": None, "slope": None}
    intercept, slope = 0.0, 1.0
    logits = [math.log(_clip_probability(p) / (1.0 - _clip_probability(p))) for p in probabilities]
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, outcome in zip(logits, outcomes):
            eta = max(-35.0, min(35.0, intercept + slope * x))
            fitted = 1.0 / (1.0 + math.exp(-eta))
            residual = fitted - outcome
            weight = max(fitted * (1.0 - fitted), 1e-12)
            g0 += residual
            g1 += residual * x
            h00 += weight
            h01 += weight * x
            h11 += weight * x * x
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-15:
            return {"intercept": None, "slope": None}
        step0 = (h11 * g0 - h01 * g1) / determinant
        step1 = (-h01 * g0 + h00 * g1) / determinant
        intercept -= step0
        slope -= step1
        if max(abs(step0), abs(step1)) < 1e-9:
            break
    if not all(math.isfinite(value) for value in (intercept, slope)):
        return {"intercept": None, "slope": None}
    return {"intercept": intercept, "slope": slope}


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[int], bins: int = CALIBRATION_BINS) -> float | None:
    if not probabilities:
        return None
    groups: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for probability, outcome in zip(probabilities, outcomes):
        index = min(bins - 1, max(0, int(float(probability) * bins)))
        groups[index].append((float(probability), int(outcome)))
    total = len(probabilities)
    return math.fsum(
        len(group) / total * abs(mean(item[0] for item in group) - mean(item[1] for item in group))
        for group in groups if group
    )


def _nested_cluster_bootstrap(rows: Sequence[dict[str, Any]], field: str, axis: str, seed: int) -> list[float] | None:
    cluster_field = "actor_hash" if axis == "actor" else "config_hash"
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        value = row.get(field)
        if value is None or not math.isfinite(float(value)):
            continue
        grouped[str(row[cluster_field])][str(row["game_id"])].append(float(value))
    clusters = sorted(grouped)
    if len(clusters) < 2:
        return None
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        values: list[float] = []
        for cluster in (rng.choice(clusters) for _ in clusters):
            games = sorted(grouped[cluster])
            for game in (rng.choice(games) for _ in games):
                values.extend(grouped[cluster][game])
        if values:
            estimates.append(mean(values))
    estimates.sort()
    return [_quantile(estimates, 0.025), _quantile(estimates, 0.975)] if estimates else None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _v1_prediction(predictor: OperationalV1Predictor, row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    context = row["v1_context"]
    fallback = False
    if context["valid_kind"] == "offer":
        action = {"offer": 1.0 - 3 * EPSILON, "accept": EPSILON, "reject": EPSILON, "walkaway": EPSILON}
    else:
        share = context.get("offered_share")
        if share is None:
            accept = 0.5
            fallback = True
        else:
            accept = predictor.discrete_probability("bargaining", row["role"], "accept", {"offered_share": share})
            if accept is None:
                accept = 0.5
                fallback = True
        remaining = 1.0 - 2 * EPSILON
        action = {
            "offer": EPSILON,
            "accept": remaining * float(accept),
            "reject": remaining * (1.0 - float(accept)),
            "walkaway": EPSILON,
        }
    if int(row["round"]) >= int(row["max_rounds"]):
        stop = 1.0 - EPSILON
    elif context["valid_kind"] == "decision":
        stop = action["accept"] + action["walkaway"]
    else:
        stop = EPSILON
    offer_samples = None
    if row.get("offer_share") is not None:
        distribution = predictor.offer_distribution(
            "bargaining",
            row["role"],
            int(context.get("own_offer_index") or 0),
            row["config"],
        )
        offer_samples = distribution["samples"]
    return {"action": action, "stop": stop, "offer_samples": offer_samples}, fallback


def _simple_prediction(simple: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": dict(simple["action"]),
        "stop": simple["stop"],
        "offer_samples": simple["offer_samples"] if row.get("offer_share") is not None else None,
    }


def _model_c_probability(model_c: EmpiricalResponseModel, row: dict[str, Any]) -> dict[str, Any] | None:
    share = row["v1_context"].get("offered_share")
    if share is None or row["v1_context"].get("valid_kind") != "decision":
        return None
    state = {
        "configuration": row["config"],
        "round": row["round"],
        "source": row.get("source", "unknown"),
    }
    estimate = model_c.bargaining_acceptance(state, row["role"], float(share))
    return estimate.to_dict() if estimate is not None else None


def score_oof_rows(
    rows: Sequence[dict[str, Any]],
    *,
    axis: str,
    manifest: dict[str, Any],
    artifacts: dict[int, dict[str, Any]],
    operational_population_path: str,
    model_c_path: str,
    v1_draws: int = 4096,
) -> list[dict[str, Any]]:
    predictor = OperationalV1Predictor(operational_population_path, draws=v1_draws, seed=BOOTSTRAP_SEED)
    model_c = EmpiricalResponseModel.load(model_c_path)
    if model_c is None:
        raise ValueError("fixed Model-C comparator is unavailable")
    certificates: list[dict[str, Any]] = []
    for row in rows:
        fold = fold_for_row(row, axis, manifest)
        artifact = artifacts[fold]
        candidate = predict_role_model(artifact["models"][row["role"]], row)
        simple = _simple_prediction(artifact["simple_role_baselines"][row["role"]], row)
        v1, v1_fallback = _v1_prediction(predictor, row)
        if candidate["action"] is None:
            raise ValueError("candidate action prediction unavailable on OOF row")
        action = str(row["action_class"])
        certificate: dict[str, Any] = {
            "axis": axis,
            "fold": fold,
            "event_id": row["event_id"],
            "game_id": row["game_id"],
            "role": row["role"],
            "round": row["round"],
            "actor_hash": _hash(str(row["actor_model"])),
            "config_hash": _hash(str(row["config_key"])),
            "action_outcome": action,
            "candidate_action": candidate["action"],
            "v1_action": v1["action"],
            "simple_action": simple["action"],
            "candidate_action_log_loss": categorical_log_loss(candidate["action"], action),
            "v1_action_log_loss": categorical_log_loss(v1["action"], action),
            "simple_action_log_loss": categorical_log_loss(simple["action"], action),
            "candidate_action_brier": categorical_brier(candidate["action"], action),
            "v1_action_brier": categorical_brier(v1["action"], action),
            "simple_action_brier": categorical_brier(simple["action"], action),
            "v1_default_fallback": int(v1_fallback),
            "candidate_nonfinite_or_support_violation": 0,
        }
        certificate["action_log_loss_diff_v1"] = certificate["candidate_action_log_loss"] - certificate["v1_action_log_loss"]
        certificate["action_brier_diff_v1"] = certificate["candidate_action_brier"] - certificate["v1_action_brier"]
        if row.get("stop") is not None:
            outcome = int(row["stop"])
            for name, prediction in (("candidate", candidate), ("v1", v1), ("simple", simple)):
                probability = prediction["stop"]
                certificate[f"{name}_stop"] = probability
                certificate[f"{name}_stop_log_loss"] = binary_log_loss(float(probability), outcome)
                certificate[f"{name}_stop_brier"] = (float(probability) - outcome) ** 2
            certificate["stop_outcome"] = outcome
            certificate["stop_log_loss_diff_v1"] = certificate["candidate_stop_log_loss"] - certificate["v1_stop_log_loss"]
            certificate["stop_brier_diff_v1"] = certificate["candidate_stop_brier"] - certificate["v1_stop_brier"]
        if row.get("offer_share") is not None:
            actual = float(row["offer_share"])
            certificate["offer_outcome"] = actual
            for name, prediction in (("candidate", candidate), ("v1", v1), ("simple", simple)):
                samples = prediction["offer_samples"]
                if not samples or any(not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0 for value in samples):
                    certificate["candidate_nonfinite_or_support_violation"] = int(name == "candidate")
                    continue
                point = mean(float(value) for value in samples)
                certificate[f"{name}_offer_crps"] = empirical_crps(samples, actual)
                certificate[f"{name}_offer_mae"] = abs(point - actual)
                certificate[f"{name}_offer_covered_80"] = int(_quantile(samples, 0.10) <= actual <= _quantile(samples, 0.90))
            if all(f"{name}_offer_crps" in certificate for name in ("candidate", "v1")):
                certificate["offer_crps_diff_v1"] = certificate["candidate_offer_crps"] - certificate["v1_offer_crps"]
                certificate["offer_mae_diff_v1"] = certificate["candidate_offer_mae"] - certificate["v1_offer_mae"]
        model_c_result = _model_c_probability(model_c, row)
        if model_c_result is not None:
            decision_outcome = int(action == "accept")
            probability = float(model_c_result["probability"])
            certificate["model_c_accept"] = probability
            certificate["model_c_accept_outcome"] = decision_outcome
            certificate["model_c_accept_log_loss"] = binary_log_loss(probability, decision_outcome)
            certificate["model_c_accept_brier"] = (probability - decision_outcome) ** 2
            certificate["model_c_support"] = int(model_c_result["support"])
            certificate["model_c_fallback_level"] = int(model_c_result["fallback_level"])
            certificate["model_c_global_fallback"] = int(bool(model_c_result["is_global_fallback"]))
        certificates.append(certificate)
    return certificates


def _support(rows: Sequence[dict[str, Any]], axis: str, field: str | None = None) -> dict[str, Any]:
    eligible = [row for row in rows if field is None or row.get(field) is not None]
    cluster_field = "actor_hash" if axis == "actor" else "config_hash"
    all_games = {row["game_id"] for row in rows}
    games = {row["game_id"] for row in eligible}
    return {
        "rows": len(eligible),
        "games": len(games),
        "primary_clusters": len({row[cluster_field] for row in eligible}),
        "nested_game_clusters": len(games),
        "eligible_game_fraction": len(games) / len(all_games) if all_games else 0.0,
    }


def _binary_calibration(rows: Sequence[dict[str, Any]], prefix: str, outcome_field: str) -> dict[str, Any]:
    probabilities = [float(row[prefix]) for row in rows if row.get(prefix) is not None and row.get(outcome_field) is not None]
    outcomes = [int(row[outcome_field]) for row in rows if row.get(prefix) is not None and row.get(outcome_field) is not None]
    return {
        **_calibration_fit(probabilities, outcomes),
        "ece": expected_calibration_error(probabilities, outcomes),
        "predicted_mean": mean(probabilities) if probabilities else None,
        "observed_mean": mean(outcomes) if outcomes else None,
        "positives": sum(outcomes),
        "negatives": len(outcomes) - sum(outcomes),
    }


def _trajectory_rows(rows: Sequence[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["role"] == role and row.get("stop_outcome") is not None:
            grouped[str(row["game_id"])].append(row)
    output: list[dict[str, Any]] = []
    for game_id, game_rows in sorted(grouped.items()):
        ordered = sorted(game_rows, key=lambda row: (int(row["round"]), str(row["event_id"])))
        actual_count = len(ordered)
        actual_round = max(int(row["round"]) for row in ordered)
        record = {
            "game_id": game_id,
            "actor_hash": ordered[0]["actor_hash"],
            "config_hash": ordered[0]["config_hash"],
        }
        for name in ("candidate", "v1", "simple"):
            survival = 1.0
            count_samples: list[float] = []
            round_samples: list[float] = []
            masses: list[tuple[float, int, int]] = []
            for index, row in enumerate(ordered, 1):
                hazard = _clip_probability(float(row[f"{name}_stop"]))
                mass = survival * hazard
                masses.append((mass, index, int(row["round"])))
                survival *= 1.0 - hazard
            if masses:
                last_mass, last_count, last_round = masses[-1]
                masses[-1] = (last_mass + survival, last_count, last_round)
            # A deterministic 256-point inverse-CDF representation keeps the
            # energy score and artifact size bounded.
            cumulative = []
            running = 0.0
            for mass, count, round_number in masses:
                running += mass
                cumulative.append((running, count, round_number))
            for sample_index in range(256):
                target = (sample_index + 0.5) / 256
                _, count, round_number = next(item for item in cumulative if item[0] + 1e-12 >= target)
                count_samples.append(float(count))
                round_samples.append(float(round_number))
            record[f"{name}_terminal_round_mae"] = abs(mean(round_samples) - actual_round)
            record[f"{name}_action_count_energy"] = energy_score(count_samples, actual_count)
        record["terminal_round_mae_diff_v1"] = record["candidate_terminal_round_mae"] - record["v1_terminal_round_mae"]
        record["action_count_energy_diff_v1"] = record["candidate_action_count_energy"] - record["v1_action_count_energy"]
        output.append(record)
    return output


def summarize_oof(certificates: Sequence[dict[str, Any]], *, axis: str) -> dict[str, Any]:
    role_cells: list[dict[str, Any]] = []
    trajectory_cells: list[dict[str, Any]] = []
    failures: list[str] = []
    for role in ROLES:
        rows = [row for row in certificates if row["role"] == role]
        action_support = _support(rows, axis)
        action_calibration = {}
        v1_action_calibration = {}
        for label in ACTION_CLASSES:
            candidate_probabilities = [float(row["candidate_action"][label]) for row in rows]
            v1_probabilities = [float(row["v1_action"][label]) for row in rows]
            outcomes = [int(row["action_outcome"] == label) for row in rows]
            action_calibration[label] = {
                **_calibration_fit(candidate_probabilities, outcomes),
                "ece": expected_calibration_error(candidate_probabilities, outcomes),
                "positives": sum(outcomes),
                "negatives": len(outcomes) - sum(outcomes),
            }
            v1_action_calibration[label] = {
                "ece": expected_calibration_error(v1_probabilities, outcomes),
            }
        action_cell = {
            "axis": axis,
            "role": role,
            "channel": "next_action",
            "support": action_support,
            "candidate_log_loss": mean(float(row["candidate_action_log_loss"]) for row in rows),
            "v1_log_loss": mean(float(row["v1_action_log_loss"]) for row in rows),
            "simple_log_loss": mean(float(row["simple_action_log_loss"]) for row in rows),
            "candidate_brier": mean(float(row["candidate_action_brier"]) for row in rows),
            "v1_brier": mean(float(row["v1_action_brier"]) for row in rows),
            "simple_brier": mean(float(row["simple_action_brier"]) for row in rows),
            "candidate_minus_v1_log_loss": mean(float(row["action_log_loss_diff_v1"]) for row in rows),
            "candidate_minus_v1_log_loss_ci95": _nested_cluster_bootstrap(rows, "action_log_loss_diff_v1", axis, BOOTSTRAP_SEED + len(role_cells)),
            "candidate_minus_v1_brier": mean(float(row["action_brier_diff_v1"]) for row in rows),
            "candidate_minus_v1_brier_ci95": _nested_cluster_bootstrap(rows, "action_brier_diff_v1", axis, BOOTSTRAP_SEED + 10 + len(role_cells)),
            "candidate_calibration_one_vs_rest": action_calibration,
            "v1_ece_one_vs_rest": v1_action_calibration,
        }
        role_cells.append(action_cell)

        stop_rows = [row for row in rows if row.get("stop_outcome") is not None]
        stop_cell = {
            "axis": axis,
            "role": role,
            "channel": "stop",
            "support": _support(rows, axis, "stop_outcome"),
            "candidate_log_loss": mean(float(row["candidate_stop_log_loss"]) for row in stop_rows) if stop_rows else None,
            "v1_log_loss": mean(float(row["v1_stop_log_loss"]) for row in stop_rows) if stop_rows else None,
            "simple_log_loss": mean(float(row["simple_stop_log_loss"]) for row in stop_rows) if stop_rows else None,
            "candidate_brier": mean(float(row["candidate_stop_brier"]) for row in stop_rows) if stop_rows else None,
            "v1_brier": mean(float(row["v1_stop_brier"]) for row in stop_rows) if stop_rows else None,
            "candidate_minus_v1_log_loss": mean(float(row["stop_log_loss_diff_v1"]) for row in stop_rows) if stop_rows else None,
            "candidate_minus_v1_log_loss_ci95": _nested_cluster_bootstrap(stop_rows, "stop_log_loss_diff_v1", axis, BOOTSTRAP_SEED + 20 + len(role_cells)),
            "candidate_minus_v1_brier": mean(float(row["stop_brier_diff_v1"]) for row in stop_rows) if stop_rows else None,
            "candidate_minus_v1_brier_ci95": _nested_cluster_bootstrap(stop_rows, "stop_brier_diff_v1", axis, BOOTSTRAP_SEED + 30 + len(role_cells)),
            "candidate_calibration": _binary_calibration(stop_rows, "candidate_stop", "stop_outcome"),
            "v1_calibration": _binary_calibration(stop_rows, "v1_stop", "stop_outcome"),
        }
        role_cells.append(stop_cell)

        offer_rows = [row for row in rows if row.get("offer_outcome") is not None]
        offer_cell = {
            "axis": axis,
            "role": role,
            "channel": "offer",
            "support": _support(rows, axis, "offer_outcome"),
            "candidate_crps": mean(float(row["candidate_offer_crps"]) for row in offer_rows) if offer_rows else None,
            "v1_crps": mean(float(row["v1_offer_crps"]) for row in offer_rows) if offer_rows else None,
            "simple_crps": mean(float(row["simple_offer_crps"]) for row in offer_rows) if offer_rows else None,
            "candidate_minus_v1_crps": mean(float(row["offer_crps_diff_v1"]) for row in offer_rows) if offer_rows else None,
            "candidate_minus_v1_crps_ci95": _nested_cluster_bootstrap(offer_rows, "offer_crps_diff_v1", axis, BOOTSTRAP_SEED + 40 + len(role_cells)),
            "candidate_normalized_mae": mean(float(row["candidate_offer_mae"]) for row in offer_rows) if offer_rows else None,
            "v1_normalized_mae": mean(float(row["v1_offer_mae"]) for row in offer_rows) if offer_rows else None,
            "candidate_minus_v1_mae": mean(float(row["offer_mae_diff_v1"]) for row in offer_rows) if offer_rows else None,
            "candidate_central_80_coverage": mean(float(row["candidate_offer_covered_80"]) for row in offer_rows) if offer_rows else None,
            "v1_central_80_coverage": mean(float(row["v1_offer_covered_80"]) for row in offer_rows) if offer_rows else None,
            "nonfinite_or_support_violations": sum(int(row["candidate_nonfinite_or_support_violation"]) for row in offer_rows),
        }
        role_cells.append(offer_cell)

        model_c_rows = [row for row in rows if row.get("model_c_accept") is not None]
        role_cells.append({
            "axis": axis,
            "role": role,
            "channel": "model_c_acceptance_comparator_diagnostic",
            "support": _support(rows, axis, "model_c_accept"),
            "model_c_log_loss": mean(float(row["model_c_accept_log_loss"]) for row in model_c_rows) if model_c_rows else None,
            "model_c_brier": mean(float(row["model_c_accept_brier"]) for row in model_c_rows) if model_c_rows else None,
            "model_c_calibration": _binary_calibration(model_c_rows, "model_c_accept", "model_c_accept_outcome"),
            "global_fallback_rate": mean(float(row["model_c_global_fallback"]) for row in model_c_rows) if model_c_rows else None,
            "gate_role": "diagnostic_only_estimand_match; not a substitute for v1 endpoint",
        })

        trajectories = _trajectory_rows(rows, role)
        trajectory_cell = {
            "axis": axis,
            "role": role,
            "channel": "trajectory",
            "support": _support(trajectories, axis),
            "candidate_terminal_round_mae": mean(float(row["candidate_terminal_round_mae"]) for row in trajectories) if trajectories else None,
            "v1_terminal_round_mae": mean(float(row["v1_terminal_round_mae"]) for row in trajectories) if trajectories else None,
            "terminal_round_mae_diff_v1": mean(float(row["terminal_round_mae_diff_v1"]) for row in trajectories) if trajectories else None,
            "terminal_round_mae_diff_v1_ci95": _nested_cluster_bootstrap(trajectories, "terminal_round_mae_diff_v1", axis, BOOTSTRAP_SEED + 50 + len(trajectory_cells)),
            "candidate_action_count_energy": mean(float(row["candidate_action_count_energy"]) for row in trajectories) if trajectories else None,
            "v1_action_count_energy": mean(float(row["v1_action_count_energy"]) for row in trajectories) if trajectories else None,
            "action_count_energy_diff_v1": mean(float(row["action_count_energy_diff_v1"]) for row in trajectories) if trajectories else None,
            "action_count_energy_diff_v1_ci95": _nested_cluster_bootstrap(trajectories, "action_count_energy_diff_v1", axis, BOOTSTRAP_SEED + 60 + len(trajectory_cells)),
            "definition": "teacher-forced observed-prefix dynamic hazard reconstruction; future state is never an input to a row prediction",
        }
        trajectory_cells.append(trajectory_cell)

    fallback_rate = mean(float(row["v1_default_fallback"]) for row in certificates) if certificates else 1.0
    all_cells = role_cells + trajectory_cells
    for cell in all_cells:
        if cell["channel"] == "model_c_acceptance_comparator_diagnostic":
            continue
        support = cell["support"]
        if (
            support["eligible_game_fraction"] < 0.50
            or support["rows"] < 200
            or support["nested_game_clusters"] < 20
        ):
            failures.append(f"{axis}/{cell['role']}/{cell['channel']}:insufficient_support")
    for cell in role_cells:
        if cell["channel"] == "next_action":
            for metric in ("candidate_minus_v1_log_loss_ci95", "candidate_minus_v1_brier_ci95"):
                ci = cell[metric]
                if ci is None or ci[1] >= 0:
                    failures.append(f"{axis}/{cell['role']}/next_action:{metric}_not_below_zero")
            for label, calibration in cell["candidate_calibration_one_vs_rest"].items():
                if calibration["intercept"] is None or abs(float(calibration["intercept"])) > 0.10:
                    failures.append(f"{axis}/{cell['role']}/next_action:{label}_calibration_intercept")
                if calibration["slope"] is None or not 0.8 <= float(calibration["slope"]) <= 1.2:
                    failures.append(f"{axis}/{cell['role']}/next_action:{label}_calibration_slope")
                v1_ece = cell["v1_ece_one_vs_rest"][label]["ece"]
                if calibration["ece"] is None or v1_ece is None or float(calibration["ece"]) - float(v1_ece) > 0.01:
                    failures.append(f"{axis}/{cell['role']}/next_action:{label}_ece_regression")
        elif cell["channel"] == "stop":
            for metric in ("candidate_minus_v1_log_loss_ci95", "candidate_minus_v1_brier_ci95"):
                ci = cell[metric]
                if ci is None or ci[1] >= 0:
                    failures.append(f"{axis}/{cell['role']}/stop:{metric}_not_below_zero")
            calibration = cell["candidate_calibration"]
            if calibration["intercept"] is None or abs(float(calibration["intercept"])) > 0.10:
                failures.append(f"{axis}/{cell['role']}/stop:calibration_intercept")
            if calibration["slope"] is None or not 0.8 <= float(calibration["slope"]) <= 1.2:
                failures.append(f"{axis}/{cell['role']}/stop:calibration_slope")
            if calibration["ece"] is None or cell["v1_calibration"]["ece"] is None or float(calibration["ece"]) - float(cell["v1_calibration"]["ece"]) > 0.01:
                failures.append(f"{axis}/{cell['role']}/stop:ece_regression")
        elif cell["channel"] == "offer":
            ci = cell["candidate_minus_v1_crps_ci95"]
            if ci is None or ci[1] >= 0:
                failures.append(f"{axis}/{cell['role']}/offer:crps_ci_not_below_zero")
            if cell["candidate_minus_v1_mae"] is None or cell["candidate_minus_v1_mae"] >= 0:
                failures.append(f"{axis}/{cell['role']}/offer:mae_not_improved")
            coverage = cell["candidate_central_80_coverage"]
            if coverage is None or not 0.75 <= coverage <= 0.85:
                failures.append(f"{axis}/{cell['role']}/offer:coverage_outside_75_85")
            if cell["nonfinite_or_support_violations"]:
                failures.append(f"{axis}/{cell['role']}/offer:support_violation")
    for cell in trajectory_cells:
        for metric in ("terminal_round_mae_diff_v1_ci95", "action_count_energy_diff_v1_ci95"):
            ci = cell[metric]
            if ci is None or ci[1] >= 0:
                failures.append(f"{axis}/{cell['role']}/trajectory:{metric}_not_below_zero")
    if fallback_rate > 0.05:
        failures.append(f"{axis}:v1_default_fallback_rate_above_5pct")
    return {
        "axis": axis,
        "role_channel_cells": role_cells,
        "trajectory_cells": trajectory_cells,
        "v1_default_fallback_rate": fallback_rate,
        "failures": sorted(set(failures)),
        "pass": not failures,
    }


def final_verdict(axis_summaries: Sequence[dict[str, Any]], artifact_statuses: Iterable[str]) -> dict[str, Any]:
    failures = [failure for summary in axis_summaries for failure in summary["failures"]]
    bad_artifacts = [status for status in artifact_statuses if status != "ok"]
    if bad_artifacts:
        failures.append("one_or_more_fold_artifacts_failed_solver_or_component_status")
    status = "development_pass" if not failures else "development_fail"
    return {
        "status": status,
        "passes_all_frozen_endpoints": not failures,
        "failures": sorted(set(failures)),
        "evidence_maturity": (
            "candidate_pending_independent_structural_validation"
            if status == "development_pass"
            else "negative_development_result_pending_postfit_audit"
        ),
        "evidence_distinctions": {
            "model_a_needed": "established only by prior Wave-5B candidate/self-audited necessity evidence",
            "fitted_candidate_predicts_better": bool(status == "development_pass"),
            "structural_validation": False,
            "untouched_confirmation": False,
            "agent_payoff_improvement": False,
        },
        "prohibited_integration": True,
    }
