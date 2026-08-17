"""Censor-aware OOF evaluator for Wave 5D bargaining Model-A v2."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from statistics import mean
from typing import Any, Iterable, Sequence

from glee_eval.diagnostics.bargaining_model_a_evaluator import (
    BOOTSTRAP_SEED,
    _model_c_probability,
    _nested_cluster_bootstrap,
    _quantile,
    _simple_prediction,
    _support,
    binary_log_loss,
    categorical_brier,
    categorical_log_loss,
    empirical_crps,
    energy_score,
    summarize_oof as summarize_oof_v1,
)
from glee_eval.diagnostics.operational_v1_bargaining import OperationalV1BargainingComparator
from glee_eval.population.bargaining_model_a import predict_role_model
from glee_eval.population.bargaining_model_a_v2 import ACTION_CLASSES, ROLES, fold_for_row_v2
from glee_eval.response_models.runtime import EmpiricalResponseModel


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def score_oof_rows_v2(
    rows: Sequence[dict[str, Any]],
    *, axis: str, manifest: dict[str, Any], artifacts: dict[int, dict[str, Any]],
    operational_population_path: str, model_c_path: str, v1_draws: int = 4096,
) -> list[dict[str, Any]]:
    comparator = OperationalV1BargainingComparator(
        operational_population_path, draws=v1_draws, seed=BOOTSTRAP_SEED,
    )
    model_c = EmpiricalResponseModel.load(model_c_path)
    if model_c is None:
        raise ValueError("fixed Model-C diagnostic comparator is unavailable")
    certificates: list[dict[str, Any]] = []
    seen_row_ids: set[str] = set()
    for row in rows:
        row_id = str(row.get("row_id") or "")
        if len(row_id) != 64 or row_id in seen_row_ids:
            raise ValueError("OOF scoring requires unique SHA256 content row identities")
        seen_row_ids.add(row_id)
        fold = fold_for_row_v2(row, axis, manifest)
        artifact = artifacts[fold]
        candidate = predict_role_model(artifact["models"][row["role"]], row)
        simple = _simple_prediction(artifact["simple_role_baselines"][row["role"]], row)
        operational = comparator.predict(row)
        if candidate["action"] is None:
            raise ValueError("candidate action prediction unavailable on OOF row")
        action = str(row["action_class"])
        certificate: dict[str, Any] = {
            "axis": axis,
            "fold": fold,
            "row_id": row_id,
            "event_id": row_id,
            "game_id": row["game_id"],
            "role": row["role"],
            "round": row["round"],
            "actor_hash": _hash(str(row["actor_model"])),
            "config_hash": _hash(str(row["config_key"])),
            "trajectory_observed": bool(row["trajectory_observed"]),
            "trajectory_censor_reason": row["trajectory_censor_reason"],
            "action_outcome": action,
            "candidate_action": candidate["action"],
            "v1_action": operational["action"],
            "simple_action": simple["action"],
            "candidate_action_log_loss": categorical_log_loss(candidate["action"], action),
            "v1_action_log_loss": categorical_log_loss(operational["action"], action),
            "simple_action_log_loss": categorical_log_loss(simple["action"], action),
            "candidate_action_brier": categorical_brier(candidate["action"], action),
            "v1_action_brier": categorical_brier(operational["action"], action),
            "simple_action_brier": categorical_brier(simple["action"], action),
            "v1_default_fallback": 0,
            "candidate_nonfinite_or_support_violation": 0,
        }
        certificate["action_log_loss_diff_v1"] = certificate["candidate_action_log_loss"] - certificate["v1_action_log_loss"]
        certificate["action_brier_diff_v1"] = certificate["candidate_action_brier"] - certificate["v1_action_brier"]
        if row.get("stop") is not None:
            outcome = int(row["stop"])
            for name, prediction in (("candidate", candidate), ("v1", operational), ("simple", simple)):
                probability = prediction["stop"]
                if probability is None:
                    raise ValueError(f"{name} stop prediction unavailable")
                certificate[f"{name}_stop"] = probability
                certificate[f"{name}_stop_log_loss"] = binary_log_loss(float(probability), outcome)
                certificate[f"{name}_stop_brier"] = (float(probability) - outcome) ** 2
            certificate["stop_outcome"] = outcome
            certificate["stop_log_loss_diff_v1"] = certificate["candidate_stop_log_loss"] - certificate["v1_stop_log_loss"]
            certificate["stop_brier_diff_v1"] = certificate["candidate_stop_brier"] - certificate["v1_stop_brier"]
        if row.get("offer_share") is not None:
            actual = float(row["offer_share"])
            certificate["offer_outcome"] = actual
            for name, prediction in (("candidate", candidate), ("v1", operational), ("simple", simple)):
                samples = prediction["offer_samples"]
                if not samples or any(not math.isfinite(float(value)) or not 0 <= float(value) <= 1 for value in samples):
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
            probability = float(model_c_result["probability"])
            outcome = int(action == "accept")
            certificate.update({
                "model_c_accept": probability,
                "model_c_accept_outcome": outcome,
                "model_c_accept_log_loss": binary_log_loss(probability, outcome),
                "model_c_accept_brier": (probability - outcome) ** 2,
                "model_c_support": int(model_c_result["support"]),
                "model_c_fallback_level": int(model_c_result["fallback_level"]),
                "model_c_global_fallback": int(bool(model_c_result["is_global_fallback"])),
            })
        certificates.append(certificate)
    if len(seen_row_ids) != len(rows):
        raise ValueError("OOF row identity reconciliation failed")
    return certificates


def _complete_trajectory_rows(
    rows: Sequence[dict[str, Any]], role: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["role"] == role:
            grouped[str(row["game_id"])].append(row)
    output: list[dict[str, Any]] = []
    diagnostics = {"complete_games": 0, "right_censored_games": 0, "invalid_games": 0}
    for game_id, game_rows in sorted(grouped.items()):
        ordered = sorted(game_rows, key=lambda row: (int(row["round"]), str(row["row_id"])))
        if not all(bool(row.get("trajectory_observed")) for row in ordered):
            diagnostics["right_censored_games"] += 1
            continue
        terminal = [row for row in ordered if row.get("stop_outcome") == 1]
        if len(terminal) != 1 or terminal[0] is not ordered[-1]:
            diagnostics["invalid_games"] += 1
            continue
        diagnostics["complete_games"] += 1
        actual_count = len(ordered)
        actual_round = int(ordered[-1]["round"])
        record = {
            "game_id": game_id,
            "actor_hash": ordered[0]["actor_hash"],
            "config_hash": ordered[0]["config_hash"],
        }
        for name in ("candidate", "v1", "simple"):
            survival = 1.0
            masses: list[tuple[float, int, int]] = []
            for index, row in enumerate(ordered, 1):
                probability = min(1 - 1e-12, max(1e-12, float(row[f"{name}_stop"])))
                masses.append((survival * probability, index, int(row["round"])))
                survival *= 1.0 - probability
            mass, count, round_number = masses[-1]
            masses[-1] = (mass + survival, count, round_number)
            cumulative: list[tuple[float, int, int]] = []
            running = 0.0
            for mass, count, round_number in masses:
                running += mass
                cumulative.append((running, count, round_number))
            count_samples, round_samples = [], []
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
    return output, diagnostics


def summarize_oof_v2(certificates: Sequence[dict[str, Any]], *, axis: str) -> dict[str, Any]:
    # Reuse the already-audited proper-score/calibration implementation for the
    # row channels, then replace its Wave-5C trajectory computation entirely.
    summary = summarize_oof_v1(certificates, axis=axis)
    failures = [failure for failure in summary["failures"] if "/trajectory:" not in failure]
    trajectories: list[dict[str, Any]] = []
    for role in ROLES:
        role_rows = [row for row in certificates if row["role"] == role]
        complete, censoring = _complete_trajectory_rows(role_rows, role)
        cell = {
            "axis": axis,
            "role": role,
            "channel": "trajectory",
            "support": _support(complete, axis),
            "censoring": censoring,
            "candidate_terminal_round_mae": mean(row["candidate_terminal_round_mae"] for row in complete) if complete else None,
            "v1_terminal_round_mae": mean(row["v1_terminal_round_mae"] for row in complete) if complete else None,
            "terminal_round_mae_diff_v1": mean(row["terminal_round_mae_diff_v1"] for row in complete) if complete else None,
            "terminal_round_mae_diff_v1_ci95": _nested_cluster_bootstrap(complete, "terminal_round_mae_diff_v1", axis, BOOTSTRAP_SEED + 70 + len(trajectories)),
            "candidate_action_count_energy": mean(row["candidate_action_count_energy"] for row in complete) if complete else None,
            "v1_action_count_energy": mean(row["v1_action_count_energy"] for row in complete) if complete else None,
            "action_count_energy_diff_v1": mean(row["action_count_energy_diff_v1"] for row in complete) if complete else None,
            "action_count_energy_diff_v1_ci95": _nested_cluster_bootstrap(complete, "action_count_energy_diff_v1", axis, BOOTSTRAP_SEED + 80 + len(trajectories)),
            "definition": "complete-case terminal trajectory score; right-censored games retained for row hazard scoring but never assigned a terminal endpoint",
        }
        support = cell["support"]
        all_games = {row["game_id"] for row in role_rows}
        complete_games = {row["game_id"] for row in complete}
        support["eligible_game_fraction"] = len(complete_games) / len(all_games) if all_games else 0.0
        if censoring["invalid_games"]:
            failures.append(f"{axis}/{role}/trajectory:invalid_terminal_encoding")
        if support["eligible_game_fraction"] < 0.50 or support["rows"] < 200 or support["nested_game_clusters"] < 20:
            failures.append(f"{axis}/{role}/trajectory:insufficient_support")
        for metric in ("terminal_round_mae_diff_v1_ci95", "action_count_energy_diff_v1_ci95"):
            ci = cell[metric]
            if ci is None or ci[1] >= 0:
                failures.append(f"{axis}/{role}/trajectory:{metric}_not_below_zero")
        trajectories.append(cell)
    summary["trajectory_cells"] = trajectories
    summary["failures"] = sorted(set(failures))
    summary["pass"] = not summary["failures"]
    return summary


JORDAN_BRANCHES = (
    ("bargaining/player_1/offer/coverage_low", "player_1", "coverage"),
    ("bargaining/player_2/offer/coverage_low", "player_2", "coverage"),
    ("bargaining/player_2/offer/mae_high", "player_2", "mae"),
)


def jordan_reached_diagnostics(axis_summaries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for label, role, endpoint in JORDAN_BRANCHES:
        axis_records = []
        for summary in axis_summaries:
            matches = [cell for cell in summary["role_channel_cells"] if cell["role"] == role and cell["channel"] == "offer"]
            if len(matches) != 1:
                raise ValueError(f"missing unique offer cell for {summary['axis']}/{role}")
            cell = matches[0]
            if endpoint == "coverage":
                value = cell["candidate_central_80_coverage"]
                passed = value is not None and 0.75 <= float(value) <= 0.85
                rule = "candidate central-80 coverage in [0.75,0.85]"
            else:
                value = cell["candidate_minus_v1_mae"]
                passed = value is not None and float(value) < 0
                rule = "candidate normalized MAE minus exact operational-v1 MAE < 0"
            axis_records.append({"axis": summary["axis"], "value": value, "pass": passed, "rule": rule})
        records.append({
            "immutable_label": label,
            "selection_role": "diagnostic_only_never_hyperparameter_selection",
            "axis_results": axis_records,
            "pass": bool(axis_records) and all(record["pass"] for record in axis_records),
        })
    return {
        "schema": "glee.wave5d.model_a_jordan_reached_diagnostics.v1",
        "records": records,
        "all_pass": all(record["pass"] for record in records),
        "live_evidence_claimed": False,
    }


def final_verdict_v2(axis_summaries: Sequence[dict[str, Any]], artifact_statuses: Iterable[str]) -> dict[str, Any]:
    failures = [failure for summary in axis_summaries for failure in summary["failures"]]
    if any(status != "ok" for status in artifact_statuses):
        failures.append("one_or_more_fold_artifacts_failed_solver_or_component_status")
    status = "development_pass" if not failures else "development_fail"
    return {
        "status": status,
        "passes_all_frozen_endpoints": not failures,
        "failures": sorted(set(failures)),
        "evidence_maturity": "candidate_pending_postfit_audit" if not failures else "negative_development_result_pending_postfit_audit",
        "evidence_distinctions": {
            "model_a_needed": "prior Wave-5B candidate/self-audited necessity evidence only",
            "fitted_candidate_predicts_better_on_prespecified_development_oof": not failures,
            "untouched_confirmation": False,
            "agent_payoff_improvement": False,
        },
        "prohibited_integration": True,
    }
