"""Frozen bargaining-only sequential Model-A primitives.

The module is intentionally independent of the simulator.  It extracts only
pre-action, role-visible state from released bargaining events, fits a
factorized sequence kernel, and serializes enough provenance to make exclusion
of an outer actor or configuration fold mechanically auditable.

Nothing here is a production integration point.  Artifacts produced by this
module remain research candidates even when every development endpoint passes.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Iterator, Sequence

from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import as_dict, bargaining_share_to_responder, transcript_items
from glee_eval.population.config_keys import canonical_config_key
from glee_eval.population.crossfit import acting_model, build_manifest, row_fold
from glee_eval.storage.trajectories import canonical_json_sha256, iter_jsonl, write_json_atomic


SCHEMA = "glee.bargaining_model_a.v1"
FEATURE_VERSION = "bargaining_role_visible_v1"
ROLES = ("player_1", "player_2")
ACTION_CLASSES = ("offer", "accept", "reject", "walkaway")
HEADS = ("offer", "accept_given_response", "walkaway_given_nonaccept", "stop")
RIDGE_GRID = (0.1, 1.0, 10.0, 100.0)
HISTORY_GRID = (1, 3, 5)
RESIDUAL_BIN_GRID = (32, 64)
INNER_FOLDS = 3
MAX_ITERATIONS = 300
KKT_TOLERANCE = 1e-6
EPSILON = 1e-12

BASE_FEATURES = (
    "round_fraction",
    "remaining_fraction",
    "own_offer_index_fraction",
    "transcript_length_fraction",
    "pot_log_scale",
    "complete_information",
    "messages_allowed",
    "delta_1",
    "delta_1_missing",
    "delta_2",
    "delta_2_missing",
    "valid_kind_offer",
    "prior_action_offer",
    "prior_action_reject",
    "prior_action_accept",
    "last_received_share",
    "last_received_share_missing",
)
WINDOW_FEATURES = (
    "prior_own_offer",
    "prior_own_offer_missing",
    "prior_counterpart_offer",
    "prior_counterpart_offer_missing",
    "own_offer_mean",
    "own_offer_mean_missing",
    "counterpart_offer_mean",
    "counterpart_offer_mean_missing",
    "own_offer_change",
    "own_offer_change_missing",
    "counterpart_offer_change",
    "counterpart_offer_change_missing",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clip_probability(value: float) -> float:
    return min(1.0 - EPSILON, max(EPSILON, float(value)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        term = math.exp(-min(value, 40.0))
        return 1.0 / (1.0 + term)
    term = math.exp(max(value, -40.0))
    return term / (1.0 + term)


def _logit(value: float) -> float:
    clipped = min(1.0 - 1e-6, max(1e-6, float(value)))
    return math.log(clipped / (1.0 - clipped))


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    ordered = sorted(float(value) for value in values)
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _configuration(event: dict[str, Any]) -> dict[str, Any]:
    config = as_dict(event.get("public_parameters") or event.get("configuration"))
    return as_dict(config.get("game_args")) or config


def _canonical_key(event: dict[str, Any]) -> str:
    return canonical_config_key("bargaining", _configuration(event))


def _decision_value(item: dict[str, Any]) -> str:
    raw = as_dict(item.get("raw") or item.get("raw_record"))
    value = str(raw.get("decision") or item.get("decision") or "").strip().lower()
    return value.replace("_", "").replace(" ", "")


def _action_class(event: dict[str, Any]) -> str | None:
    action_type = str(event.get("action_type") or "")
    if action_type == "offer":
        return "offer"
    if action_type != "decision":
        return None
    if bool(event.get("accepted")):
        return "accept"
    if bool(event.get("rejected")):
        return "reject"
    raw = as_dict(event.get("raw_record"))
    decision = str(raw.get("decision") or "").strip().lower().replace("_", "").replace(" ", "")
    if decision in {"accept", "accepted", "acceptoffer"}:
        return "accept"
    if decision in {"reject", "rejected", "rejectoffer"}:
        return "reject"
    if decision in {"walkaway", "exit", "quit", "nodeal"}:
        return "walkaway"
    return None


def _offer_self_share(item: dict[str, Any], money: float) -> float | None:
    if money <= 0:
        return None
    numeric = as_float(item.get("numeric_action"))
    if numeric is not None:
        return numeric / money
    raw = as_dict(item.get("raw") or item.get("raw_record"))
    player = str(raw.get("player") or item.get("player") or "").strip().lower().replace(" ", "_")
    direct = as_float(raw.get(f"{player}_gain")) if player else None
    if direct is not None:
        return direct / money
    gains = [as_float(value) for key, value in raw.items() if str(key).endswith("_gain")]
    finite = [float(value) for value in gains if value is not None]
    return finite[0] / money if len(finite) == 1 else None


def _prior_offers(event: dict[str, Any], role: str, money: float) -> tuple[list[float], list[float]]:
    own: list[float] = []
    counterpart: list[float] = []
    for item in transcript_items(event):
        if str(item.get("action_type") or "") != "offer":
            continue
        share = _offer_self_share(item, money)
        if share is None or not math.isfinite(share):
            continue
        (own if str(item.get("role") or "") == role else counterpart).append(float(share))
    return own, counterpart


def _missing_pair(value: float | None, name: str) -> dict[str, float]:
    return {name: 0.0 if value is None else float(value), f"{name}_missing": float(value is None)}


def _window_features(values: list[float], counterpart: list[float], window: int) -> dict[str, float]:
    own_window = values[-window:]
    counterpart_window = counterpart[-window:]
    own_last = own_window[-1] if own_window else None
    other_last = counterpart_window[-1] if counterpart_window else None
    own_mean = mean(own_window) if own_window else None
    other_mean = mean(counterpart_window) if counterpart_window else None
    own_change = own_window[-1] - own_window[-2] if len(own_window) >= 2 else None
    other_change = counterpart_window[-1] - counterpart_window[-2] if len(counterpart_window) >= 2 else None
    result: dict[str, float] = {}
    for value, name in (
        (own_last, "prior_own_offer"),
        (other_last, "prior_counterpart_offer"),
        (own_mean, "own_offer_mean"),
        (other_mean, "counterpart_offer_mean"),
        (own_change, "own_offer_change"),
        (other_change, "counterpart_offer_change"),
    ):
        result.update(_missing_pair(value, name))
    return result


def extract_event_row(event: dict[str, Any]) -> dict[str, Any] | None:
    """Extract one target row without reading terminal outcome or payoff fields."""

    if str(event.get("game_family") or "") != "bargaining":
        return None
    role = str(event.get("role") or "")
    if role not in ROLES:
        return None
    action_class = _action_class(event)
    if action_class is None:
        return None
    config = _configuration(event)
    money = as_float(config.get("money_to_divide")) or 100.0
    if money <= 0:
        return None
    round_number = max(1, int(as_float(event.get("round")) or 1))
    max_rounds = max(1, int(as_float(config.get("max_rounds")) or round_number))
    transcript = transcript_items(event)
    own_offers, counterpart_offers = _prior_offers(event, role, money)
    last = transcript[-1] if transcript else {}
    prior_action = str(last.get("action_type") or "")
    prior_decision = _decision_value(last)
    last_offer = next((item for item in reversed(transcript) if item.get("action_type") == "offer"), None)
    received_share = bargaining_share_to_responder(last_offer or {}, role, money)
    last_offer_role = str((last_offer or {}).get("role") or "")
    valid_kind_offer = float(last_offer is None or last_offer_role == role or prior_action == "decision")
    complete = bool(config.get("complete_information", False))
    delta_1 = as_float(config.get("delta_1")) if complete else None
    delta_2 = as_float(config.get("delta_2")) if complete else None
    base: dict[str, float] = {
        "round_fraction": round_number / max_rounds,
        "remaining_fraction": max(0, max_rounds - round_number) / max_rounds,
        "own_offer_index_fraction": len(own_offers) / max_rounds,
        "transcript_length_fraction": len(transcript) / max(1, 2 * max_rounds),
        "pot_log_scale": math.log1p(money) / math.log(101.0),
        "complete_information": float(complete),
        "messages_allowed": float(bool(config.get("messages_allowed", False))),
        "delta_1": 0.0 if delta_1 is None else delta_1,
        "delta_1_missing": float(delta_1 is None),
        "delta_2": 0.0 if delta_2 is None else delta_2,
        "delta_2_missing": float(delta_2 is None),
        "valid_kind_offer": valid_kind_offer,
        "prior_action_offer": float(prior_action == "offer"),
        "prior_action_reject": float(prior_decision in {"reject", "rejected", "rejectoffer"}),
        "prior_action_accept": float(prior_decision in {"accept", "accepted", "acceptoffer"}),
        "last_received_share": 0.0 if received_share is None else float(received_share),
        "last_received_share_missing": float(received_share is None),
    }
    windows = {str(window): _window_features(own_offers, counterpart_offers, window) for window in HISTORY_GRID}
    offer_share = as_float(event.get("numeric_action")) / money if action_class == "offer" and as_float(event.get("numeric_action")) is not None else None
    if offer_share is not None and not (0.0 <= offer_share <= 1.0):
        offer_share = None
    return {
        "schema": SCHEMA,
        "event_id": str(event.get("event_id") or ""),
        "game_id": str(event.get("game_id") or ""),
        "source": str(event.get("source") or "unknown"),
        "role": role,
        "round": round_number,
        "max_rounds": max_rounds,
        "actor_model": acting_model(event),
        "config_key": _canonical_key(event),
        "config": config,
        "action_class": action_class,
        "offer_share": offer_share,
        "stop": None,
        "stop_censor_reason": None,
        "features_base": base,
        "features_by_window": windows,
        "v1_context": {
            "valid_kind": "offer" if valid_kind_offer else "decision",
            "offered_share": received_share,
            "own_offer_index": len(own_offers),
        },
    }


def _finalize_game_rows(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()
    for event in events:
        row = extract_event_row(event)
        if row is None:
            counters["events_unusable_or_non_bargaining"] += 1
        else:
            rows.append(row)
    if not rows:
        return rows, counters
    last_index = len(rows) - 1
    for index, row in enumerate(rows):
        action = row["action_class"]
        if action in {"accept", "walkaway"}:
            row["stop"] = 1
        elif index < last_index:
            row["stop"] = 0
        elif int(row["round"]) >= int(row["max_rounds"]):
            row["stop"] = 1
        else:
            row["stop"] = None
            row["stop_censor_reason"] = "missing_terminal_callback_before_horizon"
            counters["last_actions_censored_before_horizon"] += 1
    return rows, counters


def iter_extracted_rows(events: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Group consecutive source events by game and yield frozen target rows."""

    current_game: str | None = None
    group: list[dict[str, Any]] = []
    seen_closed: set[str] = set()
    for event in events:
        if str(event.get("game_family") or "") != "bargaining":
            continue
        game_id = str(event.get("game_id") or "")
        if not game_id:
            continue
        if current_game is None:
            current_game = game_id
        if game_id != current_game:
            seen_closed.add(current_game)
            if game_id in seen_closed:
                raise ValueError("events source is not grouped by game_id")
            finalized, _ = _finalize_game_rows(group)
            yield from finalized
            group = []
            current_game = game_id
        group.append(event)
    if group:
        finalized, _ = _finalize_game_rows(group)
        yield from finalized


def extract_corpus(events_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Stream the bargaining slice once and atomically freeze extracted rows."""

    source = Path(events_path)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    counters: Counter[str] = Counter()
    actors: set[str] = set()
    configs: set[str] = set()
    with temporary.open("w", encoding="utf-8") as handle:
        for row in iter_extracted_rows(iter_jsonl(source)):
            counters["rows"] += 1
            counters[f"role:{row['role']}"] += 1
            counters[f"action:{row['action_class']}"] += 1
            counters["stop_observed"] += int(row["stop"] is not None)
            counters["offer_observed"] += int(row["offer_share"] is not None)
            actors.add(str(row["actor_model"]))
            configs.add(str(row["config_key"]))
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
    temporary.replace(destination)
    return {
        "source_path": str(source.resolve()),
        "source_sha256": sha256_file(source),
        "rows_path": str(destination.resolve()),
        "rows_sha256": sha256_file(destination),
        "counts": dict(sorted(counters.items())),
        "actor_count": len(actors),
        "config_count": len(configs),
    }


def build_bargaining_manifest(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    compatible = [
        {
            "game_family": "bargaining",
            "role": row["role"],
            "player_1_model": row["actor_model"] if row["role"] == "player_1" else "__not_acting__",
            "player_2_model": row["actor_model"] if row["role"] == "player_2" else "__not_acting__",
            "public_parameters": row["config"],
        }
        for row in rows
    ]
    # build_manifest uses acting role, so the inert placeholder is never routed.
    return build_manifest(compatible)


def fold_for_row(row: dict[str, Any], axis: str, manifest: dict[str, Any]) -> int:
    compatible = {
        "game_family": "bargaining",
        "role": row["role"],
        "player_1_model": row["actor_model"] if row["role"] == "player_1" else "__not_acting__",
        "player_2_model": row["actor_model"] if row["role"] == "player_2" else "__not_acting__",
        "public_parameters": row["config"],
    }
    return row_fold(compatible, axis, manifest)


def inner_fold(game_id: str) -> int:
    return int(_sha(str(game_id))[:16], 16) % INNER_FOLDS


def _normalizer(rows: Sequence[dict[str, Any]], history_window: int) -> dict[str, dict[str, float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        combined = {**row["features_base"], **row["features_by_window"][str(history_window)]}
        for name, value in combined.items():
            values[name].append(float(value))
    result: dict[str, dict[str, float]] = {}
    for name in sorted(values):
        center = mean(values[name]) if values[name] else 0.0
        variance = mean((value - center) ** 2 for value in values[name]) if len(values[name]) > 1 else 0.0
        result[name] = {"mean": center, "sd": max(math.sqrt(variance), 1e-9)}
    return result


def _vocabulary(rows: Sequence[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "actors": sorted({str(row["actor_model"]) for row in rows}),
        "configs": sorted({str(row["config_key"]) for row in rows}),
    }


def vectorize(row: dict[str, Any], spec: dict[str, Any]) -> dict[str, float]:
    history = int(spec["history_window"])
    combined = {**row["features_base"], **row["features_by_window"][str(history)]}
    normalizer = spec["normalizer"]
    vector = {"intercept": 1.0}
    for name in sorted(combined):
        scale = normalizer[name]
        vector[f"x|{name}"] = (float(combined[name]) - float(scale["mean"])) / float(scale["sd"])
    actor = str(row["actor_model"])
    config = str(row["config_key"])
    if actor in spec["vocabulary"]["actors"]:
        vector[f"actor|{actor}"] = 1.0
    if config in spec["vocabulary"]["configs"]:
        vector[f"config|{config}"] = 1.0
    return vector


def _binary_target(row: dict[str, Any], head: str) -> int | None:
    action = row["action_class"]
    if head == "offer":
        return int(action == "offer")
    if head == "accept_given_response":
        return None if action == "offer" else int(action == "accept")
    if head == "walkaway_given_nonaccept":
        return None if action in {"offer", "accept"} else int(action == "walkaway")
    if head == "stop":
        return None if row.get("stop") is None else int(row["stop"])
    raise ValueError(f"unknown head {head}")


def _binary_objective(encoded: Sequence[tuple[dict[str, float], int]], coefficients: dict[str, float], ridge: float) -> float:
    total = 0.0
    for vector, outcome in encoded:
        eta = math.fsum(coefficients.get(name, 0.0) * value for name, value in vector.items())
        total += (eta + math.log1p(math.exp(-eta)) if eta >= 0 else math.log1p(math.exp(eta))) - outcome * eta
    total += 0.5 * ridge * math.fsum(value * value for name, value in coefficients.items() if name != "intercept")
    return total


def fit_binary(rows: Sequence[dict[str, Any]], head: str, spec: dict[str, Any], ridge: float) -> dict[str, Any]:
    encoded = [(vectorize(row, spec), target) for row in rows if (target := _binary_target(row, head)) is not None]
    if not encoded:
        return {"status": "unavailable", "head": head, "eligible_rows": 0}
    names = sorted({name for vector, _ in encoded for name in vector})
    positives = sum(outcome for _, outcome in encoded)
    rate = (positives + 0.5) / (len(encoded) + 1.0)
    coefficients = {name: 0.0 for name in names}
    coefficients["intercept"] = _logit(rate)
    if positives in {0, len(encoded)}:
        return {
            "status": "degenerate_target",
            "head": head,
            "eligible_rows": len(encoded),
            "positives": positives,
            "coefficients": coefficients,
            "ridge": ridge,
            "iterations": 0,
            "max_gradient": None,
            "kkt_tolerance": KKT_TOLERANCE,
            "objective": _binary_objective(encoded, coefficients, ridge),
            "objective_monotone": True,
            "degenerate_target": True,
        }
    affected: dict[str, list[tuple[int, float]]] = defaultdict(list)
    eta = [coefficients["intercept"] for _ in encoded]
    for index, (vector, _) in enumerate(encoded):
        for name, value in vector.items():
            if name != "intercept" and value != 0.0:
                affected[name].append((index, value))
    affected["intercept"] = [(index, 1.0) for index in range(len(encoded))]
    converged = False
    max_gradient = float("inf")
    objective_history = [_binary_objective(encoded, coefficients, ridge)]
    for iteration in range(1, MAX_ITERATIONS + 1):
        current_objective = objective_history[-1]
        for name in names:
            old = coefficients[name]
            gradient = ridge * old if name != "intercept" else 0.0
            curvature = ridge if name != "intercept" else 0.0
            for index, value in affected[name]:
                probability = _sigmoid(eta[index])
                gradient += (probability - encoded[index][1]) * value
                curvature += probability * (1.0 - probability) * value * value
            step = -gradient / max(curvature, 1e-12)
            if step == 0.0:
                continue
            local_old = 0.5 * ridge * old * old if name != "intercept" else 0.0
            for index, value in affected[name]:
                linear = eta[index]
                outcome = encoded[index][1]
                local_old += (linear + math.log1p(math.exp(-linear)) if linear >= 0 else math.log1p(math.exp(linear))) - outcome * linear
            damping = 1.0
            while damping >= 2 ** -24:
                candidate = old + damping * step
                delta = candidate - old
                local_new = 0.5 * ridge * candidate * candidate if name != "intercept" else 0.0
                for index, value in affected[name]:
                    linear = eta[index] + delta * value
                    outcome = encoded[index][1]
                    local_new += (linear + math.log1p(math.exp(-linear)) if linear >= 0 else math.log1p(math.exp(linear))) - outcome * linear
                if local_new <= local_old + 1e-12:
                    coefficients[name] = candidate
                    for index, value in affected[name]:
                        eta[index] += delta * value
                    current_objective += local_new - local_old
                    break
                damping *= 0.5
            else:
                coefficients[name] = old
        # A full objective recheck makes the certificate independent of the
        # local-coordinate bookkeeping above.
        objective_history.append(_binary_objective(encoded, coefficients, ridge))
        max_gradient = 0.0
        for name in names:
            gradient = ridge * coefficients[name] if name != "intercept" else 0.0
            for index, value in affected[name]:
                gradient += (_sigmoid(eta[index]) - encoded[index][1]) * value
            max_gradient = max(max_gradient, abs(gradient))
        if max_gradient <= KKT_TOLERANCE:
            converged = True
            break
    return {
        "status": "ok" if converged else "solver_failure",
        "head": head,
        "eligible_rows": len(encoded),
        "positives": positives,
        "coefficients": coefficients,
        "ridge": ridge,
        "iterations": iteration,
        "max_gradient": max_gradient,
        "kkt_tolerance": KKT_TOLERANCE,
        "objective": objective_history[-1],
        "objective_monotone": all(right <= left + 1e-8 for left, right in zip(objective_history, objective_history[1:])),
        "degenerate_target": False,
    }


def predict_binary(model: dict[str, Any], row: dict[str, Any], spec: dict[str, Any]) -> float | None:
    if model.get("status") not in {"ok", "solver_failure", "degenerate_target"}:
        return None
    vector = vectorize(row, spec)
    eta = math.fsum(float(model["coefficients"].get(name, 0.0)) * value for name, value in vector.items())
    return _clip_probability(_sigmoid(eta))


def fit_offer(rows: Sequence[dict[str, Any]], spec: dict[str, Any], ridge: float, residual_bins: int) -> dict[str, Any]:
    eligible = [row for row in rows if row.get("offer_share") is not None]
    if not eligible:
        return {"status": "unavailable", "eligible_rows": 0}
    encoded = [(vectorize(row, spec), _logit(float(row["offer_share"]))) for row in eligible]
    names = sorted({name for vector, _ in encoded for name in vector})
    coefficients = {name: 0.0 for name in names}
    coefficients["intercept"] = mean(target for _, target in encoded)
    predictions = [coefficients["intercept"] for _ in encoded]
    affected: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index, (vector, _) in enumerate(encoded):
        for name, value in vector.items():
            if value != 0.0:
                affected[name].append((index, value))
    converged = False
    max_change = float("inf")
    for iteration in range(1, MAX_ITERATIONS + 1):
        max_change = 0.0
        for name in names:
            old = coefficients[name]
            numerator = 0.0
            denominator = 0.0 if name == "intercept" else ridge
            for index, value in affected[name]:
                target = encoded[index][1]
                numerator += value * (target - predictions[index] + old * value)
                denominator += value * value
            new = numerator / max(denominator, 1e-12)
            delta = new - old
            coefficients[name] = new
            if delta:
                for index, value in affected[name]:
                    predictions[index] += delta * value
            max_change = max(max_change, abs(delta))
        if max_change <= KKT_TOLERANCE:
            converged = True
            break
    residuals = [target - prediction for (_, target), prediction in zip(encoded, predictions)]
    center = mean(residuals)
    residuals = [value - center for value in residuals]
    scale = max(math.sqrt(mean(value * value for value in residuals)), 1e-6)
    standardized = [value / scale for value in residuals]
    quantile_residuals = [_quantile(standardized, (index + 0.5) / residual_bins) for index in range(residual_bins)]
    return {
        "status": "ok" if converged else "solver_failure",
        "eligible_rows": len(eligible),
        "coefficients": coefficients,
        "ridge": ridge,
        "iterations": iteration,
        "max_change": max_change,
        "tolerance": KKT_TOLERANCE,
        "residual_center": center,
        "residual_scale": scale,
        "residual_bins": residual_bins,
        "standardized_residual_quantiles": quantile_residuals,
    }


def predict_offer_samples(model: dict[str, Any], row: dict[str, Any], spec: dict[str, Any]) -> list[float] | None:
    if model.get("status") not in {"ok", "solver_failure"}:
        return None
    vector = vectorize(row, spec)
    location = math.fsum(float(model["coefficients"].get(name, 0.0)) * value for name, value in vector.items())
    center = float(model["residual_center"])
    scale = float(model["residual_scale"])
    return [_sigmoid(location + center + scale * float(residual)) for residual in model["standardized_residual_quantiles"]]


def action_probabilities(models: dict[str, Any], row: dict[str, Any], spec: dict[str, Any]) -> dict[str, float] | None:
    offer = predict_binary(models["offer"], row, spec)
    accept = predict_binary(models["accept_given_response"], row, spec)
    walkaway = predict_binary(models["walkaway_given_nonaccept"], row, spec)
    if offer is None or accept is None or walkaway is None:
        return None
    result = {
        "offer": offer,
        "accept": (1.0 - offer) * accept,
        "walkaway": (1.0 - offer) * (1.0 - accept) * walkaway,
        "reject": (1.0 - offer) * (1.0 - accept) * (1.0 - walkaway),
    }
    total = math.fsum(result.values())
    return {key: value / total for key, value in result.items()}


def fit_role_model(rows: Sequence[dict[str, Any]], *, ridge: float, history_window: int, residual_bins: int) -> dict[str, Any]:
    if not rows:
        return {"status": "unavailable", "rows": 0}
    spec = {
        "history_window": history_window,
        "normalizer": _normalizer(rows, history_window),
        "vocabulary": _vocabulary(rows),
    }
    heads = {head: fit_binary(rows, head, spec, ridge) for head in HEADS}
    offer = fit_offer(rows, spec, ridge, residual_bins)
    statuses = [model.get("status") for model in [*heads.values(), offer]]
    return {
        "status": "ok" if all(status == "ok" for status in statuses) else "failed_component",
        "rows": len(rows),
        "spec": spec,
        "heads": heads,
        "offer_distribution": offer,
    }


def fit_simple_role_baseline(rows: Sequence[dict[str, Any]], residual_bins: int = 64) -> dict[str, Any]:
    """Training-only role/intercept comparator frozen with each outer artifact."""

    action_counts = Counter(str(row["action_class"]) for row in rows)
    action_total = sum(action_counts.values())
    action = {
        label: (action_counts[label] + 0.5) / (action_total + 0.5 * len(ACTION_CLASSES))
        for label in ACTION_CLASSES
    }
    stop_values = [int(row["stop"]) for row in rows if row.get("stop") is not None]
    stop = (sum(stop_values) + 0.5) / (len(stop_values) + 1.0) if stop_values else None
    offers = [float(row["offer_share"]) for row in rows if row.get("offer_share") is not None]
    samples = [_quantile(offers, (index + 0.5) / residual_bins) for index in range(residual_bins)] if offers else None
    return {
        "status": "ok" if rows and stop is not None and samples is not None else "unavailable",
        "eligible_rows": len(rows),
        "action": action,
        "stop": stop,
        "offer_samples": samples,
        "offer_rows": len(offers),
    }


def predict_role_model(model: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    spec = model["spec"]
    return {
        "action": action_probabilities(model["heads"], row, spec),
        "stop": predict_binary(model["heads"]["stop"], row, spec),
        "offer_samples": predict_offer_samples(model["offer_distribution"], row, spec) if row.get("offer_share") is not None else None,
    }


def _offer_bin_probability(samples: Sequence[float], observation: float, bins: int) -> float:
    width = 1.0 / bins
    target = min(bins - 1, max(0, int(float(observation) / width)))
    hits = sum(min(bins - 1, max(0, int(float(sample) / width))) == target for sample in samples)
    return (hits + 0.5) / (len(samples) + 0.5 * bins)


def validation_loss(models: dict[str, Any], rows: Sequence[dict[str, Any]], residual_bins: int) -> float:
    game_losses: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        prediction = predict_role_model(models[row["role"]], row)
        action = prediction["action"]
        if action is None:
            return float("inf")
        game_losses[str(row["game_id"])].append(-math.log(_clip_probability(action[row["action_class"]])))
        if row.get("stop") is not None and prediction["stop"] is not None:
            p = _clip_probability(float(prediction["stop"]))
            game_losses[str(row["game_id"])].append(-math.log(p if row["stop"] else 1.0 - p))
        if row.get("offer_share") is not None and prediction["offer_samples"]:
            probability = _offer_bin_probability(prediction["offer_samples"], float(row["offer_share"]), residual_bins)
            game_losses[str(row["game_id"])].append(-math.log(_clip_probability(probability)))
    return mean(mean(values) for values in game_losses.values()) if game_losses else float("inf")


def select_hyperparameters(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scores: list[dict[str, Any]] = []
    for ridge in RIDGE_GRID:
        for history_window in HISTORY_GRID:
            for residual_bins in RESIDUAL_BIN_GRID:
                fold_scores = []
                for fold in range(INNER_FOLDS):
                    training = [row for row in rows if inner_fold(row["game_id"]) != fold]
                    validation = [row for row in rows if inner_fold(row["game_id"]) == fold]
                    models = {
                        role: fit_role_model(
                            [row for row in training if row["role"] == role],
                            ridge=ridge,
                            history_window=history_window,
                            residual_bins=residual_bins,
                        )
                        for role in ROLES
                    }
                    fold_scores.append(validation_loss(models, validation, residual_bins))
                scores.append({
                    "ridge": ridge,
                    "history_window": history_window,
                    "residual_bins": residual_bins,
                    "fold_losses": fold_scores,
                    "cluster_mean_negative_log_likelihood": mean(fold_scores),
                })
    selected = min(
        scores,
        key=lambda item: (
            item["cluster_mean_negative_log_likelihood"],
            -item["ridge"],
            item["history_window"],
            item["residual_bins"],
        ),
    )
    return {"selected": selected, "grid_scores": scores}


def fit_outer_fold(
    rows: Sequence[dict[str, Any]],
    *,
    axis: str,
    fold: int,
    manifest: dict[str, Any],
    source_sha256: str,
    contract_sha256: str,
) -> dict[str, Any]:
    training = [row for row in rows if fold_for_row(row, axis, manifest) != fold]
    evaluation = [row for row in rows if fold_for_row(row, axis, manifest) == fold]
    selection = select_hyperparameters(training)
    chosen = selection["selected"]
    models = {
        role: fit_role_model(
            [row for row in training if row["role"] == role],
            ridge=float(chosen["ridge"]),
            history_window=int(chosen["history_window"]),
            residual_bins=int(chosen["residual_bins"]),
        )
        for role in ROLES
    }
    simple_baselines = {
        role: fit_simple_role_baseline([row for row in training if row["role"] == role])
        for role in ROLES
    }
    training_actors = sorted({row["actor_model"] for row in training})
    evaluation_actors = sorted({row["actor_model"] for row in evaluation})
    training_configs = sorted({row["config_key"] for row in training})
    evaluation_configs = sorted({row["config_key"] for row in evaluation})
    excluded = set(training_actors if axis == "actor" else training_configs) & set(evaluation_actors if axis == "actor" else evaluation_configs)
    if excluded:
        raise ValueError(f"outer {axis} leakage: {sorted(excluded)[:3]}")
    expected = manifest["folds_manifest"][axis][str(fold)]
    payload = {
        "schema": SCHEMA,
        "artifact_kind": "development_outer_fold",
        "axis": axis,
        "fold": fold,
        "folds": 3 if axis == "actor" else 4,
        "source_sha256": source_sha256,
        "contract_sha256": contract_sha256,
        "manifest_sha256": manifest["manifest_sha256"],
        "feature_version": FEATURE_VERSION,
        "feature_sha256": canonical_json_sha256({"base": BASE_FEATURES, "window": WINDOW_FEATURES}),
        "training_key_hashes": expected["training_key_hashes"],
        "evaluation_key_hashes": expected["evaluation_key_hashes"],
        "training_rows": len(training),
        "evaluation_rows": len(evaluation),
        "selection": selection,
        "models": models,
        "simple_role_baselines": simple_baselines,
        "status": "ok" if all(model["status"] == "ok" for model in models.values()) else "failed_component",
        "status_ceiling": "candidate_pending_independent_structural_validation",
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def write_fold_artifact(path: str | Path, payload: dict[str, Any]) -> Path:
    return write_json_atomic(path, payload)
