"""Wave 5D bargaining-only sequential Model-A v2.

This formulation is intentionally separate from the rejected Wave 5C route.
Every predictor feature is constructed from a strict public-state projection at
the pre-action boundary.  Terminal/censoring metadata is attached only after
features and content row identity have been frozen.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable, Iterator, Sequence

from glee_eval.data.ingest import as_float
from glee_eval.population.bargaining_model_a import (
    ACTION_CLASSES,
    HEADS,
    HISTORY_GRID,
    INNER_FOLDS,
    RESIDUAL_BIN_GRID,
    RIDGE_GRID,
    fit_role_model,
    fit_simple_role_baseline,
    predict_role_model,
)
from glee_eval.population.config_keys import canonical_config_key
from glee_eval.population.crossfit import acting_model, build_manifest, row_fold
from glee_eval.storage.trajectories import canonical_json_sha256, iter_jsonl, write_json_atomic


SCHEMA = "glee.bargaining_model_a.v2"
FEATURE_VERSION = "bargaining_strict_public_tminus1_v2"
ROLES = ("player_1", "player_2")
PUBLIC_CONFIG_FIELDS = (
    "money_to_divide",
    "max_rounds",
    "complete_information",
    "messages_allowed",
    "delta_1",
    "delta_2",
)
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


class VisibilityViolation(ValueError):
    """A row cannot prove its t-1 public-state boundary."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(payload: Any) -> str:
    return canonical_json_sha256(payload)


def _public_configuration(event: dict[str, Any]) -> dict[str, Any]:
    public = event.get("public_parameters")
    if not isinstance(public, dict) or not public:
        raise VisibilityViolation("nonempty public_parameters required; private configuration fallback forbidden")
    if "game_args" in public:
        public = public["game_args"]
        if not isinstance(public, dict) or not public:
            raise VisibilityViolation("public_parameters.game_args must be a nonempty mapping")
    projected = {field: public[field] for field in PUBLIC_CONFIG_FIELDS if field in public}
    if "money_to_divide" not in projected or "max_rounds" not in projected:
        raise VisibilityViolation("money_to_divide and max_rounds must be explicitly public")
    complete = bool(projected.get("complete_information", False))
    if not complete:
        projected.pop("delta_1", None)
        projected.pop("delta_2", None)
    return projected


def _decision(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "").replace(" ", "")


def _event_action(event: dict[str, Any]) -> str | None:
    kind = str(event.get("action_type") or "")
    if kind == "offer":
        return "offer"
    if kind != "decision":
        return None
    if bool(event.get("accepted")):
        return "accept"
    if bool(event.get("rejected")):
        return "reject"
    raw = event.get("raw_record") if isinstance(event.get("raw_record"), dict) else {}
    value = _decision(raw.get("decision"))
    if value in {"accept", "accepted", "acceptoffer"}:
        return "accept"
    if value in {"reject", "rejected", "rejectoffer"}:
        return "reject"
    if value in {"walkaway", "exit", "quit", "nodeal"}:
        return "walkaway"
    return None


def _offer_share(item: dict[str, Any], money: float) -> float | None:
    numeric = as_float(item.get("numeric_action"))
    if numeric is not None:
        return float(numeric) / money
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    raw = raw or (item.get("raw_record") if isinstance(item.get("raw_record"), dict) else {})
    role = str(item.get("role") or "")
    role_gain = as_float(raw.get(f"{role}_gain")) if role else None
    if role_gain is not None:
        return float(role_gain) / money
    self_gain = as_float(raw.get("self_gain"))
    if self_gain is not None:
        return float(self_gain) / money
    gains = [as_float(value) for key, value in raw.items() if str(key).endswith("_gain")]
    finite = [float(value) for value in gains if value is not None]
    return finite[0] / money if len(finite) == 1 else None


def _visible_history(event: dict[str, Any], *, role: str, round_number: int, money: float) -> list[dict[str, Any]]:
    source = event.get("transcript_so_far", [])
    if not isinstance(source, list):
        raise VisibilityViolation("transcript_so_far must be a list")
    visible: list[dict[str, Any]] = []
    last_round = 0
    for index, raw_item in enumerate(source):
        if not isinstance(raw_item, dict):
            raise VisibilityViolation(f"transcript item {index} is not a mapping")
        item_round_value = as_float(raw_item.get("round"))
        if item_round_value is None or int(item_round_value) != item_round_value:
            raise VisibilityViolation(f"transcript item {index} lacks an integer round")
        item_round = int(item_round_value)
        item_role = str(raw_item.get("role") or "")
        if item_role not in ROLES:
            raise VisibilityViolation(f"transcript item {index} has unknown role")
        if item_round < 1 or item_round < last_round or item_round > round_number:
            raise VisibilityViolation(f"transcript item {index} crosses the t-1 boundary")
        if item_round == round_number and item_role == role:
            raise VisibilityViolation(f"same-role current-round item {index} is not pre-action history")
        kind = str(raw_item.get("action_type") or "")
        if kind not in {"offer", "decision"}:
            raise VisibilityViolation(f"transcript item {index} has unsupported action type")
        normalized: dict[str, Any] = {"round": item_round, "role": item_role, "action_type": kind}
        if kind == "offer":
            share = _offer_share(raw_item, money)
            if share is None or not math.isfinite(share) or not 0.0 <= share <= 1.0:
                raise VisibilityViolation(f"transcript offer {index} lacks a valid public share")
            normalized["offer_self_share"] = float(share)
        else:
            raw = raw_item.get("raw") if isinstance(raw_item.get("raw"), dict) else {}
            value = _decision(raw.get("decision") or raw_item.get("decision") or raw_item.get("accept_reject"))
            if value in {"accept", "accepted", "acceptoffer"}:
                normalized["decision"] = "accept"
            elif value in {"reject", "rejected", "rejectoffer"}:
                normalized["decision"] = "reject"
            elif value in {"walkaway", "exit", "quit", "nodeal"}:
                normalized["decision"] = "walkaway"
            else:
                raise VisibilityViolation(f"transcript decision {index} is unrecognized")
            if normalized["decision"] in {"accept", "walkaway"}:
                raise VisibilityViolation("history contains a terminal action before the target")
        visible.append(normalized)
        last_round = item_round
    return visible


def _missing(value: float | None, name: str) -> dict[str, float]:
    return {name: 0.0 if value is None else float(value), f"{name}_missing": float(value is None)}


def _window(own: list[float], counterpart: list[float], size: int) -> dict[str, float]:
    left, right = own[-size:], counterpart[-size:]
    pairs = (
        (left[-1] if left else None, "prior_own_offer"),
        (right[-1] if right else None, "prior_counterpart_offer"),
        (mean(left) if left else None, "own_offer_mean"),
        (mean(right) if right else None, "counterpart_offer_mean"),
        (left[-1] - left[-2] if len(left) >= 2 else None, "own_offer_change"),
        (right[-1] - right[-2] if len(right) >= 2 else None, "counterpart_offer_change"),
    )
    result: dict[str, float] = {}
    for value, name in pairs:
        result.update(_missing(value, name))
    return result


def extract_event_row_v2(event: dict[str, Any]) -> dict[str, Any] | None:
    if str(event.get("game_family") or "") != "bargaining":
        return None
    game_id = str(event.get("game_id") or "")
    role = str(event.get("role") or "")
    if not game_id or role not in ROLES:
        raise VisibilityViolation("bargaining row requires nonempty game_id and known role")
    action = _event_action(event)
    if action is None:
        return None
    config = _public_configuration(event)
    money_value = as_float(config.get("money_to_divide"))
    round_value = as_float(event.get("round"))
    horizon_value = as_float(config.get("max_rounds"))
    if money_value is None or money_value <= 0 or round_value is None or horizon_value is None:
        raise VisibilityViolation("finite positive money, round, and horizon are required")
    if int(round_value) != round_value or int(horizon_value) != horizon_value:
        raise VisibilityViolation("round and horizon must be integers")
    round_number, max_rounds = int(round_value), int(horizon_value)
    if not 1 <= round_number <= max_rounds:
        raise VisibilityViolation("target round lies outside the public horizon")
    money = float(money_value)
    history = _visible_history(event, role=role, round_number=round_number, money=money)
    prior = history[-1] if history else None
    valid_kind = "decision" if prior and prior["action_type"] == "offer" else "offer"
    if (action == "offer") != (valid_kind == "offer"):
        raise VisibilityViolation("target action kind disagrees with t-1 public action schema")
    own_offers = [item["offer_self_share"] for item in history if item["action_type"] == "offer" and item["role"] == role]
    counterpart_offers = [item["offer_self_share"] for item in history if item["action_type"] == "offer" and item["role"] != role]
    last_offer = next((item for item in reversed(history) if item["action_type"] == "offer"), None)
    received = None
    if last_offer is not None and last_offer["role"] != role:
        received = 1.0 - float(last_offer["offer_self_share"])
    complete = bool(config.get("complete_information", False))
    delta_1 = as_float(config.get("delta_1")) if complete else None
    delta_2 = as_float(config.get("delta_2")) if complete else None
    base: dict[str, float] = {
        "round_fraction": round_number / max_rounds,
        "remaining_fraction": (max_rounds - round_number) / max_rounds,
        "own_offer_index_fraction": len(own_offers) / max_rounds,
        "transcript_length_fraction": len(history) / max(1, 2 * max_rounds),
        "pot_log_scale": math.log1p(money) / math.log(101.0),
        "complete_information": float(complete),
        "messages_allowed": float(bool(config.get("messages_allowed", False))),
        "delta_1": 0.0 if delta_1 is None else float(delta_1),
        "delta_1_missing": float(delta_1 is None),
        "delta_2": 0.0 if delta_2 is None else float(delta_2),
        "delta_2_missing": float(delta_2 is None),
        "valid_kind_offer": float(valid_kind == "offer"),
        "prior_action_offer": float(bool(prior and prior["action_type"] == "offer")),
        "prior_action_reject": float(bool(prior and prior.get("decision") == "reject")),
        "prior_action_accept": 0.0,
        "last_received_share": 0.0 if received is None else received,
        "last_received_share_missing": float(received is None),
    }
    offer_share = None
    if action == "offer":
        numeric = as_float(event.get("numeric_action"))
        if numeric is None:
            raise VisibilityViolation("offer target lacks numeric_action")
        offer_share = float(numeric) / money
        if not math.isfinite(offer_share) or not 0.0 <= offer_share <= 1.0:
            raise VisibilityViolation("offer target lies outside public support")
    actor = acting_model(event)
    if not actor:
        raise VisibilityViolation("acting model identity is absent")
    identity_payload = {
        "game_id": game_id,
        "source": str(event.get("source") or "unknown"),
        "role": role,
        "round": round_number,
        "actor_model": actor,
        "public_configuration": config,
        "visible_history": history,
        "target": {"action_class": action, "offer_share": offer_share},
    }
    row_id = _canonical_hash(identity_payload)
    return {
        "schema": SCHEMA,
        "row_id": row_id,
        "event_id_observational_only": str(event.get("event_id") or ""),
        "game_id": game_id,
        "source": str(event.get("source") or "unknown"),
        "role": role,
        "round": round_number,
        "max_rounds": max_rounds,
        "actor_model": actor,
        "config_key": canonical_config_key("bargaining", config),
        "config": config,
        "visible_history": history,
        "visibility_certificate": {
            "boundary": "strict_pre_action_t_minus_1",
            "public_configuration_sha256": _canonical_hash(config),
            "visible_history_sha256": _canonical_hash(history),
            "visible_history_items": len(history),
        },
        "action_class": action,
        "offer_share": offer_share,
        "stop": None,
        "stop_censor_reason": None,
        "trajectory_observed": None,
        "trajectory_censor_reason": None,
        "features_base": base,
        "features_by_window": {str(size): _window(own_offers, counterpart_offers, size) for size in HISTORY_GRID},
        "v1_context": {
            "valid_kind": valid_kind,
            "offered_share": received,
            "own_offer_index": len(own_offers),
            "visible_history": history,
        },
    }


def _finalize_game_rows_v2(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for event in events if (row := extract_event_row_v2(event)) is not None]
    if not rows:
        return []
    for row in rows[:-1]:
        if row["action_class"] in {"accept", "walkaway"}:
            raise VisibilityViolation("action observed after a terminal bargaining decision")
    last = rows[-1]
    completed = last["action_class"] in {"accept", "walkaway"} or (
        last["action_class"] == "reject" and int(last["round"]) >= int(last["max_rounds"])
    )
    censor_reason = None if completed else "missing_terminal_callback_or_right_censored_before_horizon"
    for index, row in enumerate(rows):
        if index < len(rows) - 1:
            row["stop"] = 0
        elif completed:
            row["stop"] = 1
        else:
            row["stop"] = None
            row["stop_censor_reason"] = censor_reason
        row["trajectory_observed"] = completed
        row["trajectory_censor_reason"] = censor_reason
    return rows


def iter_extracted_rows_v2(events: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    current_game: str | None = None
    group: list[dict[str, Any]] = []
    closed: set[str] = set()
    row_ids: set[str] = set()
    for event in events:
        if str(event.get("game_family") or "") != "bargaining":
            continue
        game_id = str(event.get("game_id") or "")
        if not game_id:
            raise VisibilityViolation("bargaining event lacks game_id")
        if current_game is None:
            current_game = game_id
        if game_id != current_game:
            closed.add(current_game)
            if game_id in closed:
                raise VisibilityViolation("events source is not consecutively grouped by game_id")
            for row in _finalize_game_rows_v2(group):
                if row["row_id"] in row_ids:
                    raise VisibilityViolation("duplicate content-derived row_id")
                row_ids.add(row["row_id"])
                yield row
            group = []
            current_game = game_id
        group.append(event)
    for row in _finalize_game_rows_v2(group):
        if row["row_id"] in row_ids:
            raise VisibilityViolation("duplicate content-derived row_id")
        row_ids.add(row["row_id"])
        yield row


def extract_corpus_v2(
    events_path: str | Path,
    output_path: str | Path,
    *,
    artifact_byte_limit: int = 3 * 1024 ** 3,
) -> dict[str, Any]:
    source, destination = Path(events_path), Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    counts: Counter[str] = Counter()
    actors: set[str] = set()
    configs: set[str] = set()
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            for row in iter_extracted_rows_v2(iter_jsonl(source)):
                encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                if handle.tell() + len(encoded.encode("utf-8")) > artifact_byte_limit:
                    raise RuntimeError("extraction artifact byte ceiling would be exceeded")
                handle.write(encoded)
                counts["rows"] += 1
                counts[f"role:{row['role']}"] += 1
                counts[f"action:{row['action_class']}"] += 1
                counts[f"trajectory:{'observed' if row['trajectory_observed'] else 'right_censored'}"] += 1
                actors.add(row["actor_model"])
                configs.add(row["config_key"])
            handle.flush()
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "source_path": str(source.resolve()),
        "source_sha256": sha256_file(source),
        "rows_path": str(destination.resolve()),
        "rows_sha256": sha256_file(destination),
        "counts": dict(sorted(counts.items())),
        "actor_count": len(actors),
        "config_count": len(configs),
        "row_identity": "sha256_canonical_visible_state_plus_target",
    }


def build_bargaining_manifest_v2(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    compatible = [{
        "game_family": "bargaining",
        "role": row["role"],
        "player_1_model": row["actor_model"] if row["role"] == "player_1" else "__not_acting__",
        "player_2_model": row["actor_model"] if row["role"] == "player_2" else "__not_acting__",
        "public_parameters": row["config"],
    } for row in rows]
    return build_manifest(compatible)


def fold_for_row_v2(row: dict[str, Any], axis: str, manifest: dict[str, Any]) -> int:
    compatible = {
        "game_family": "bargaining",
        "role": row["role"],
        "player_1_model": row["actor_model"] if row["role"] == "player_1" else "__not_acting__",
        "player_2_model": row["actor_model"] if row["role"] == "player_2" else "__not_acting__",
        "public_parameters": row["config"],
    }
    return row_fold(compatible, axis, manifest)


def inner_fold_v2(game_id: str) -> int:
    return int(hashlib.sha256(str(game_id).encode("utf-8")).hexdigest()[:16], 16) % INNER_FOLDS


def game_channel_objectives(
    models: dict[str, Any],
    rows: Sequence[dict[str, Any]],
    residual_bins: int,
    *,
    predictor: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = predict_role_model,
) -> dict[str, dict[str, Any]]:
    """One joint objective per game, with equal channel weight within game."""

    from glee_eval.population.bargaining_model_a import _clip_probability, _offer_bin_probability

    channel_losses: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        game = str(row["game_id"])
        channels = channel_losses.setdefault(game, {"action": [], "stop": [], "offer": []})
        prediction = predictor(models[row["role"]], row)
        action = prediction.get("action")
        if action is None:
            return {}
        channels["action"].append(-math.log(_clip_probability(action[row["action_class"]])))
        if row.get("stop") is not None and prediction.get("stop") is not None:
            probability = _clip_probability(float(prediction["stop"]))
            channels["stop"].append(-math.log(probability if row["stop"] else 1.0 - probability))
        if row.get("offer_share") is not None and prediction.get("offer_samples"):
            probability = _offer_bin_probability(prediction["offer_samples"], float(row["offer_share"]), residual_bins)
            channels["offer"].append(-math.log(_clip_probability(probability)))
    result: dict[str, dict[str, Any]] = {}
    for game, channels in sorted(channel_losses.items()):
        channel_means = {name: mean(values) for name, values in channels.items() if values}
        if "action" not in channel_means:
            return {}
        result[game] = {
            "channel_means": channel_means,
            "joint_loss": mean(channel_means.values()),
        }
    return result


def aggregate_inner_game_objective(fold_games: Sequence[dict[str, dict[str, Any]]]) -> float:
    merged: dict[str, float] = {}
    for games in fold_games:
        for game_id, record in games.items():
            if game_id in merged:
                raise ValueError("inner-CV game appears in more than one validation fold")
            merged[game_id] = float(record["joint_loss"])
    return mean(merged.values()) if merged else float("inf")


def select_hyperparameters_v2(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    scores: list[dict[str, Any]] = []
    for ridge in RIDGE_GRID:
        for history_window in HISTORY_GRID:
            for residual_bins in RESIDUAL_BIN_GRID:
                fold_games: list[dict[str, dict[str, Any]]] = []
                for fold in range(INNER_FOLDS):
                    training = [row for row in rows if inner_fold_v2(row["game_id"]) != fold]
                    validation = [row for row in rows if inner_fold_v2(row["game_id"]) == fold]
                    models = {role: fit_role_model(
                        [row for row in training if row["role"] == role],
                        ridge=ridge,
                        history_window=history_window,
                        residual_bins=residual_bins,
                    ) for role in ROLES}
                    fold_games.append(game_channel_objectives(models, validation, residual_bins))
                scores.append({
                    "ridge": ridge,
                    "history_window": history_window,
                    "residual_bins": residual_bins,
                    "validation_games_by_fold": [len(games) for games in fold_games],
                    "unweighted_game_joint_negative_log_likelihood": aggregate_inner_game_objective(fold_games),
                })
    selected = min(scores, key=lambda item: (
        item["unweighted_game_joint_negative_log_likelihood"],
        -item["ridge"], item["history_window"], item["residual_bins"],
    ))
    return {"selected": selected, "grid_scores": scores}


def fit_outer_fold_v2(
    rows: Sequence[dict[str, Any]],
    *, axis: str, fold: int, manifest: dict[str, Any], source_sha256: str, contract_sha256: str,
) -> dict[str, Any]:
    training = [row for row in rows if fold_for_row_v2(row, axis, manifest) != fold]
    evaluation = [row for row in rows if fold_for_row_v2(row, axis, manifest) == fold]
    selection = select_hyperparameters_v2(training)
    chosen = selection["selected"]
    models = {role: fit_role_model(
        [row for row in training if row["role"] == role],
        ridge=float(chosen["ridge"]), history_window=int(chosen["history_window"]),
        residual_bins=int(chosen["residual_bins"]),
    ) for role in ROLES}
    baselines = {role: fit_simple_role_baseline([row for row in training if row["role"] == role]) for role in ROLES}
    train_keys = {row["actor_model"] if axis == "actor" else row["config_key"] for row in training}
    eval_keys = {row["actor_model"] if axis == "actor" else row["config_key"] for row in evaluation}
    if train_keys & eval_keys:
        raise ValueError(f"outer {axis} leakage")
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
        "simple_role_baselines": baselines,
        "status": "ok" if all(model["status"] == "ok" for model in models.values()) else "failed_component",
        "status_ceiling": "candidate_pending_independent_structural_validation",
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload


def write_fold_artifact_v2(path: str | Path, payload: dict[str, Any]) -> Path:
    return write_json_atomic(path, payload)
