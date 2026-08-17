"""Back-test the public shadow leaderboard proxy against captured batch endpoints.

The live logs do not contain official per-game percentiles/ratings or the private
opponent adjustment, and their launch manifests do not contain a git commit.  The
module therefore emits a partially identified, class-attributed batch diagnostic
rather than inventing per-game ground truth.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from glee_eval.data.ingest import as_float
from glee_eval.scoring.shadow import (
    FAMILIES,
    _choose_bucket,
    _choose_trade_zone_bucket,
    _negotiation_trade_zone,
    build_reference_tables,
    displayed_rating,
    eta_for_game,
    game_rating,
    percentile_rank,
)
from glee_eval.storage.trajectories import iter_jsonl, write_json


def invert_displayed_rating(displayed: float, games: int) -> float:
    if games <= 0:
        return 1000.0
    return 1000.0 + (displayed - 1000.0) * (games + 30.0) / games


def _infer_order(state: dict[str, Any]) -> float:
    values = [as_float(state.get("player_1_value")), as_float(state.get("player_2_value"))]
    prices = [as_float((row.get("offer") or {}).get("price")) for row in state.get("history", []) if isinstance(row, dict)]
    scale = max([value for value in values + prices if value is not None] or [1.0])
    for order in (1.0, 100.0, 10_000.0, 1_000_000.0):
        if scale / order <= 2.5:
            return order
    return 1_000_000.0


def _terminal_records(run_dir: Path) -> list[dict[str, Any]]:
    by_game: dict[str, dict[str, Any]] = {}
    latest_observation: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(run_dir / "observations.jsonl"):
        if isinstance(row.get("game_state"), dict):
            latest_observation[str(row.get("game_id"))] = row
    for row in iter_jsonl(run_dir / "move_results.jsonl"):
        move = row.get("move_result") if isinstance(row.get("move_result"), dict) else {}
        if move.get("status") != "completed" or not isinstance(move.get("game_state"), dict):
            if row.get("game_over") is not True or not isinstance(row.get("result"), dict):
                continue
            game_id = str(row.get("game_id"))
            observation = latest_observation.get(game_id)
            if observation is None:
                continue
            payload = {
                "game_family": observation.get("game_family"),
                "game_id": game_id,
                "game_state": observation["game_state"],
                "result": row["result"],
                "status": "completed",
                "your_player": observation.get("your_player"),
                "captured_at": row.get("captured_at"),
            }
            by_game[game_id] = payload
        else:
            payload = dict(move)
            payload["captured_at"] = row.get("captured_at")
            by_game[str(move.get("game_id"))] = payload
    return sorted(by_game.values(), key=lambda row: (str(row.get("captured_at") or ""), str(row.get("game_id") or "")))


def _episode(record: dict[str, Any]) -> dict[str, Any] | None:
    family = str(record.get("game_family") or "")
    if family not in FAMILIES:
        return None
    state = record["game_state"]
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    your_player = str(record.get("your_player") or "")
    if your_player not in {"player_1", "player_2"}:
        return None
    role = your_player
    if family in {"negotiation", "persuasion"}:
        role = "seller" if your_player == "player_1" else "buyer"
    raw_payoff = as_float(result.get(f"{your_player}_payoff"))
    if raw_payoff is None:
        return None
    if family == "bargaining":
        scale = as_float(state.get("money_to_divide")) or 100.0
        payoff = raw_payoff / scale
        config = {
            "money_to_divide": scale,
            "max_rounds": state.get("max_rounds", 99 if not state.get("horizon_known", False) else len(state.get("history", []))),
            "complete_information": state.get("complete_information"),
            "messages_allowed": state.get("messages_allowed"),
            "delta_1": state.get("delta_1"),
            "delta_2": state.get("delta_2"),
        }
    elif family == "negotiation":
        scale = _infer_order(state)
        payoff = raw_payoff / scale
        config = {
            "seller_value": (as_float(state.get("player_1_value")) / scale) if as_float(state.get("player_1_value")) is not None else None,
            "buyer_value": (as_float(state.get("player_2_value")) / scale) if as_float(state.get("player_2_value")) is not None else None,
            "product_price_order": scale,
            "max_rounds": state.get("max_rounds", 99 if not state.get("horizon_known", False) else len(state.get("history", []))),
            "complete_information": state.get("complete_information"),
            "messages_allowed": state.get("messages_allowed"),
        }
    else:
        price = as_float(state.get("product_price")) or 1.0
        rounds = int(as_float(state.get("total_rounds")) or 20)
        payoff = raw_payoff / (price * rounds)
        config = {
            "p": state.get("p"),
            "v": (as_float(state.get("v")) / price) if as_float(state.get("v")) is not None else None,
            "c": (as_float(state.get("u")) / price) if as_float(state.get("u")) is not None else 0,
            "product_price": price,
            "total_rounds": rounds,
            "is_seller_know_cv": state.get("is_seller_know_cv"),
            "is_buyer_know_p": state.get("is_buyer_know_p", True),
            "seller_message_type": state.get("seller_message_type"),
            "is_myopic": state.get("is_myopic"),
            "allow_buyer_message": state.get("allow_buyer_message", False),
        }
    return {
        "game_id": record.get("game_id"),
        "captured_at": record.get("captured_at"),
        "family": family,
        "role": role,
        "config": config,
        "payoff": payoff,
        "opponent_name": (record.get("opponent") or {}).get("name"),
        "opponent_type": (record.get("opponent") or {}).get("type"),
    }


def _score_episode(episode: dict[str, Any], reference: dict[str, list[float]], min_reference: int) -> dict[str, Any]:
    family, role, config, payoff = episode["family"], episode["role"], episode["config"], episode["payoff"]
    choice = _choose_bucket(reference, family, role, config, min_reference=min_reference)
    exact = _choose_bucket(reference, family, role, config, min_reference=1)
    # _choose_bucket with min=1 returns the first nonempty key, i.e. exact when available.
    percentile = percentile_rank(reference.get(choice.key, []), payoff) if choice else None
    exact_percentile = percentile_rank(reference.get(exact.key, []), payoff) if exact and exact.level == "exact" else None
    zone = _negotiation_trade_zone(family, config)
    zone_choice = _choose_trade_zone_bucket(reference, family, role, config, zone, min_reference=min_reference)
    zone_percentile = percentile_rank(reference.get(zone_choice.key, []), payoff) if zone_choice else None
    return {
        **episode,
        "percentile": percentile,
        "exact_config_percentile": exact_percentile,
        "public_formula_game_rating": game_rating(percentile) if percentile is not None else None,
        "bucket_level": choice.level if choice else None,
        "bucket_support": choice.support if choice else 0,
        "trade_zone_percentile": zone_percentile,
        "opponent_adjustment_available": False,
    }


def _snapshot(path: Path) -> dict[str, dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scores = ((payload.get("stats") or {}).get("scores") or {})
    return {family: {"games": int(scores[family]["games_played"]), "rating": float(scores[family]["rating"])} for family in FAMILIES}


def _project_batch(
    rows: list[dict[str, Any]],
    start: dict[str, dict[str, float]],
    end: dict[str, dict[str, float]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for family in FAMILIES:
        family_rows = [row for row in rows if row["family"] == family and row["public_formula_game_rating"] is not None]
        raw = invert_displayed_rating(start[family]["rating"], int(start[family]["games"]))
        for index, row in enumerate(family_rows, start=1):
            absolute_game_index = int(start[family]["games"]) + index
            eta = eta_for_game(absolute_game_index, eta_start=0.01, eta_floor=0.002, eta_decay_games=120)
            raw = max(100.0, min(5000.0, raw + eta * (float(row["public_formula_game_rating"]) - raw)))
        projected_games = int(start[family]["games"]) + len(family_rows)
        projected_displayed = displayed_rating(raw, projected_games)
        observed = float(end[family]["rating"])
        count_delta = int(end[family]["games"]) - int(start[family]["games"])
        exact_rows = [row for row in family_rows if row["exact_config_percentile"] is not None]
        errors = [float(row["trade_zone_percentile"]) - float(row["percentile"]) for row in family_rows if row["trade_zone_percentile"] is not None]
        output[family] = {
            "captured_terminal_games": len([row for row in rows if row["family"] == family]),
            "proxy_scored_games": len(family_rows),
            "official_game_count_delta": count_delta,
            "count_attribution_exact": count_delta == len([row for row in rows if row["family"] == family]),
            "start_displayed_rating": start[family]["rating"],
            "observed_end_displayed_rating": observed,
            "projected_end_displayed_rating": projected_displayed,
            "batch_endpoint_error_proxy_minus_observed": projected_displayed - observed,
            "mean_percentile": mean(float(row["percentile"]) for row in family_rows) if family_rows else None,
            "median_percentile": median(float(row["percentile"]) for row in family_rows) if family_rows else None,
            "mean_public_formula_game_rating": mean(float(row["public_formula_game_rating"]) for row in family_rows) if family_rows else None,
            "raw_exact_configuration_percentile": {
                "available_games": len(exact_rows),
                "coverage": len(exact_rows) / len(family_rows) if family_rows else 0.0,
                "mean": mean(float(row["exact_config_percentile"]) for row in exact_rows) if exact_rows else None,
            },
            "bucket_levels": dict(Counter(str(row["bucket_level"]) for row in family_rows)),
            "trade_zone_sensitivity_percentile_delta": {
                "n": len(errors),
                "mean": mean(errors) if errors else None,
                "minimum": min(errors) if errors else None,
                "maximum": max(errors) if errors else None,
            },
        }
    return output


def _forecast(
    current: dict[str, dict[str, float]],
    all_rows: list[dict[str, Any]],
    batch_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output = {}
    for family in FAMILIES:
        rows = [row for row in all_rows if row["family"] == family and row["public_formula_game_rating"] is not None]
        mean_game = mean(float(row["public_formula_game_rating"]) for row in rows)
        batch_errors = [
            abs(float(result[family]["batch_endpoint_error_proxy_minus_observed"]))
            for result in batch_results.values()
            if result[family]["count_attribution_exact"]
        ]
        projections = {}
        for target in (300, 500):
            games = int(current[family]["games"])
            raw = invert_displayed_rating(float(current[family]["rating"]), games)
            for index in range(games + 1, target + 1):
                eta = eta_for_game(index, eta_start=0.01, eta_floor=0.002, eta_decay_games=120)
                raw = max(100.0, min(5000.0, raw + eta * (mean_game - raw)))
            point = displayed_rating(raw, target)
            empirical_radius = max(batch_errors) if batch_errors else None
            projections[str(target)] = {
                "public_formula_point": point,
                "empirical_batch_endpoint_sensitivity": (
                    [point - empirical_radius, point + empirical_radius] if empirical_radius is not None else None
                ),
                "private_opponent_adjustment_envelope": "unbounded_from_captured_fields",
            }
        exact = [row for row in rows if row["exact_config_percentile"] is not None]
        output[family] = {
            "raw_exact_configuration_percentile": mean(float(row["exact_config_percentile"]) for row in exact) if exact else None,
            "public_formula_game_rating_proxy": mean_game,
            "empirically_calibrated_proxy": None,
            "empirical_calibration_obstruction": "only three batch endpoints and no official per-game ratings or adjustment terms",
            "uncertainty_sensitivity_envelope": projections,
        }
    return output


def run_backtest(
    games_path: str | Path,
    start_summary: str | Path,
    run_dirs: list[str | Path],
    output_path: str | Path,
    *,
    min_reference: int = 20,
) -> dict[str, Any]:
    reference = build_reference_tables(games_path)
    starts = _snapshot(Path(start_summary))
    batch_results: dict[str, dict[str, Any]] = {}
    all_rows = []
    current = starts
    run_attribution = {}
    for path_like in run_dirs:
        run_dir = Path(path_like)
        records = _terminal_records(run_dir)
        episodes = [episode for record in records if (episode := _episode(record)) is not None]
        scored = [_score_episode(episode, reference, min_reference) for episode in episodes]
        end = _snapshot(run_dir / "run_summary.json")
        batch_results[run_dir.name] = _project_batch(scored, current, end)
        manifest = json.loads((run_dir / "launch_manifest.json").read_text(encoding="utf-8"))
        run_attribution[run_dir.name] = {
            "terminal_complete_games": len(records),
            "agent_class": manifest.get("agent"),
            "exact_agent_commit": None,
            "official_per_game_output_captured": False,
            "opponent_adjustment_inputs_complete": False,
        }
        all_rows.extend(scored)
        current = end
    exact_batches = [name for name, result in batch_results.items() if all(result[family]["count_attribution_exact"] for family in FAMILIES)]
    errors_by_family = {
        family: [batch_results[name][family]["batch_endpoint_error_proxy_minus_observed"] for name in exact_batches]
        for family in FAMILIES
    }
    result = {
        "schema": "glee.wave5b.leaderboard_proxy_backtest.v1",
        "evidence_class": "class_attributed_batch_sensitivity_not_per_game_validation",
        "formal_fully_attributable_batches": 0,
        "formal_obstruction": "no live launch manifest records the exact agent commit; no log captures official per-game rating or private opponent adjustment",
        "run_attribution": run_attribution,
        "batch_results": batch_results,
        "batch_endpoint_error_summary": {
            family: {
                "n_exact_count_batches": len(errors),
                "bias": mean(errors) if errors else None,
                "mae": mean(abs(value) for value in errors) if errors else None,
                "median_absolute_error": median(abs(value) for value in errors) if errors else None,
                "correlation": None,
                "interval_coverage": None,
                "ranking_agreement": None,
                "why_per_game_metrics_unidentified": "official per-game ratings/percentiles and opponent adjustments were not captured",
            }
            for family, errors in errors_by_family.items()
        },
        "errors_by_opponent_strength": "unidentified: opponent strength/adjustment missing or hidden",
        "current_official_snapshot": current,
        "four_part_forecast": _forecast(current, all_rows, batch_results),
        "no_reverse_engineering": True,
    }
    write_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", required=True)
    parser.add_argument("--start-summary", required=True)
    parser.add_argument("--run-dir", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-reference", type=int, default=20)
    args = parser.parse_args(argv)
    result = run_backtest(args.games, args.start_summary, args.run_dir, args.output, min_reference=args.min_reference)
    print(json.dumps({"output": args.output, "formal_fully_attributable_batches": result["formal_fully_attributable_batches"]}, indent=2))


if __name__ == "__main__":
    main()
