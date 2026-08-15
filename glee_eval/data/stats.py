from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.storage.trajectories import read_records, write_json


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def summarize_values(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": _mean(values),
        "median": _median(values),
        "p10": _quantile(values, 0.10),
        "p25": _quantile(values, 0.25),
        "p75": _quantile(values, 0.75),
        "p90": _quantile(values, 0.90),
    }


def bargaining_stats(events: list[dict[str, Any]], games: list[dict[str, Any]]) -> dict[str, Any]:
    family_events = [event for event in events if event.get("game_family") == "bargaining"]
    offers = [event for event in family_events if event.get("action_type") == "offer" and event.get("numeric_action") is not None]
    decisions = [event for event in family_events if event.get("action_type") == "decision"]
    first_offer_by_game: dict[str, float] = {}
    by_round: dict[int, list[float]] = defaultdict(list)
    for offer in offers:
        value = as_float(offer.get("numeric_action"))
        money = as_float((offer.get("configuration") or {}).get("money_to_divide")) or 1.0
        if value is None:
            continue
        share = value / money
        first_offer_by_game.setdefault(str(offer.get("game_id")), share)
        by_round[int(offer.get("round") or 0)].append(share)
    agreements = [game for game in games if game.get("game_family") == "bargaining" and (game.get("terminal_outcome") or {}).get("result") == "accept"]
    family_games = [game for game in games if game.get("game_family") == "bargaining"]
    return {
        "opening_offer_share": summarize_values(list(first_offer_by_game.values())),
        "offered_share_by_round": {str(k): summarize_values(v) for k, v in sorted(by_round.items())},
        "acceptance_rate": len([d for d in decisions if d.get("accepted")]) / len(decisions) if decisions else None,
        "agreement_rate": len(agreements) / len(family_games) if family_games else None,
        "agreement_round": summarize_values(
            [float((game.get("terminal_outcome") or {}).get("agreement_round")) for game in agreements if (game.get("terminal_outcome") or {}).get("agreement_round")]
        ),
        "player_1_payoff": summarize_values([float(game.get("player_1_payoff")) for game in family_games if game.get("player_1_payoff") is not None]),
        "player_2_payoff": summarize_values([float(game.get("player_2_payoff")) for game in family_games if game.get("player_2_payoff") is not None]),
    }


def negotiation_stats(events: list[dict[str, Any]], games: list[dict[str, Any]]) -> dict[str, Any]:
    family_events = [event for event in events if event.get("game_family") == "negotiation"]
    offers = [event for event in family_events if event.get("action_type") == "offer" and event.get("numeric_action") is not None]
    decisions = [event for event in family_events if event.get("action_type") == "decision"]
    family_games = [game for game in games if game.get("game_family") == "negotiation"]
    trades = [game for game in family_games if (game.get("terminal_outcome") or {}).get("result") == "AcceptOffer"]
    first_offer_by_game: dict[str, float] = {}
    by_round: dict[int, list[float]] = defaultdict(list)
    for offer in offers:
        config = offer.get("configuration") or {}
        order = as_float(config.get("product_price_order")) or 1.0
        price = as_float(offer.get("numeric_action"))
        if price is None:
            continue
        normalized = price / order
        first_offer_by_game.setdefault(str(offer.get("game_id")), normalized)
        by_round[int(offer.get("round") or 0)].append(normalized)
    return {
        "opening_price_normalized": summarize_values(list(first_offer_by_game.values())),
        "price_by_round": {str(k): summarize_values(v) for k, v in sorted(by_round.items())},
        "acceptance_rate": len([d for d in decisions if d.get("accepted")]) / len(decisions) if decisions else None,
        "agreement_rate": len(trades) / len(family_games) if family_games else None,
        "failure_to_trade_rate": 1 - (len(trades) / len(family_games)) if family_games else None,
        "agreement_round": summarize_values(
            [float((game.get("terminal_outcome") or {}).get("agreement_round")) for game in trades if (game.get("terminal_outcome") or {}).get("agreement_round")]
        ),
        "seller_surplus": summarize_values([float(game.get("player_1_payoff")) for game in family_games if game.get("player_1_payoff") is not None]),
        "buyer_surplus": summarize_values([float(game.get("player_2_payoff")) for game in family_games if game.get("player_2_payoff") is not None]),
    }


def persuasion_stats(events: list[dict[str, Any]], games: list[dict[str, Any]]) -> dict[str, Any]:
    family_events = [event for event in events if event.get("game_family") == "persuasion"]
    seller_events = [event for event in family_events if event.get("role") == "seller"]
    buyer_events = [event for event in family_events if event.get("role") == "buyer" and event.get("buy_no_buy") is not None or event.get("bought") is not None]
    nature_events = [event for event in family_events if event.get("action_type") == "nature_quality"]
    family_games = [game for game in games if game.get("game_family") == "persuasion"]
    buy_events = [event for event in family_events if event.get("role") == "buyer" and event.get("bought") is True]
    yes_recommendations = [event for event in seller_events if (event.get("raw_record") or {}).get("decision") == "yes"]
    quality_high = [event for event in nature_events if "high" in str((event.get("raw_record") or {}).get("round_quality", ""))]
    return {
        "seller_recommend_buy_rate": len(yes_recommendations) / len(seller_events) if seller_events else None,
        "receiver_buy_rate": len(buy_events) / len([e for e in family_events if e.get("role") == "buyer"]) if family_events else None,
        "high_quality_rate": len(quality_high) / len(nature_events) if nature_events else None,
        "sales": summarize_values([float((game.get("terminal_outcome") or {}).get("sales", 0)) for game in family_games]),
        "sender_payoff": summarize_values([float(game.get("player_1_payoff")) for game in family_games if game.get("player_1_payoff") is not None]),
        "receiver_payoff": summarize_values([float(game.get("player_2_payoff")) for game in family_games if game.get("player_2_payoff") is not None]),
    }


def compute_empirical_stats(events: list[dict[str, Any]], games: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dataset": {"events": len(events), "games": len(games)},
        "bargaining": bargaining_stats(events, games),
        "negotiation": negotiation_stats(events, games),
        "persuasion": persuasion_stats(events, games),
    }


def stats_from_processed(data_dir: str | Path = DEFAULT_DATA_DIR) -> dict[str, Any]:
    data_dir = Path(data_dir)
    events = read_records(data_dir / "processed" / "events.jsonl")
    games = read_records(data_dir / "processed" / "games.jsonl")
    stats = compute_empirical_stats(events, games)
    out_dir = data_dir / "empirical"
    write_json(out_dir / "summary.json", stats)
    for family in ["bargaining", "negotiation", "persuasion"]:
        write_json(out_dir / f"{family}.json", stats[family])
    return stats


def stats_from_live_observations(observations_path: str | Path) -> dict[str, Any]:
    """Summarize the adapter's append-only live turn log without needing ingest."""

    path = Path(observations_path)
    if not path.exists():
        raise FileNotFoundError(f"Live observations not found: {path}")
    rows = read_records(path)
    statuses = Counter(str(row.get("status") or "missing") for row in rows)
    families = Counter(str(row.get("game_family") or "missing") for row in rows)
    phases = Counter(str(row.get("phase") or "missing") for row in rows)
    action_types = Counter(str(row.get("action_type") or "missing") for row in rows)
    violation_rows = [row for row in rows if row.get("schema_violations")]
    fallbacks = sum(count for status, count in statuses.items() if status.startswith("fallback"))
    return {
        "observation_log": str(path),
        "turns": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "families": dict(sorted(families.items())),
        "phases": dict(sorted(phases.items())),
        "action_types": dict(sorted(action_types.items())),
        "fallbacks": fallbacks,
        "fallback_rate": fallbacks / len(rows) if rows else None,
        "schema_violation_turns": len(violation_rows),
        "schema_violations": sum(len(row.get("schema_violations") or []) for row in violation_rows),
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m glee_eval stats",
        description="Compute empirical behavior statistics from processed GLEE data.",
    )
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument(
        "--observations",
        help="Summarize a live adapter observations.jsonl directly instead of processed GLEE data.",
    )
    args = parser.parse_args(argv)
    result = stats_from_live_observations(args.observations) if args.observations else stats_from_processed(args.data_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
