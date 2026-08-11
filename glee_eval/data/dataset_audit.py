from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.storage.trajectories import ensure_dir, read_records, write_json


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return False
    return True


def _field_rate(records: list[dict[str, Any]], field: str, *, require_nonempty: bool = False) -> dict[str, Any]:
    present = 0
    for record in records:
        if field not in record:
            continue
        if require_nonempty and not _present(record.get(field)):
            continue
        present += 1
    total = len(records)
    return {"present": present, "total": total, "rate": present / total if total else None}


def _counter(records: list[dict[str, Any]], field: str, *, limit: int | None = None) -> dict[str, int]:
    counts = Counter(str(record.get(field) if _present(record.get(field)) else "missing") for record in records)
    rows = counts.most_common(limit)
    return {key: count for key, count in rows}


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": mean(ordered),
        "median": median(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _bin(value: float, width: float = 0.1, low: float = 0.0, high: float = 1.5) -> str:
    if value < low:
        return f"<{low:.1f}"
    if value >= high:
        return f">={high:.1f}"
    start = int(((value - low) / width) + 1e-9) * width + low
    end = start + width
    return f"{start:.1f}-{end:.1f}"


def _private_key_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        private = event.get("private_information") or {}
        if isinstance(private, str):
            try:
                private = json.loads(private)
            except json.JSONDecodeError:
                private = {}
        for key, value in (private or {}).items():
            if _present(value):
                counts[str(key)] += 1
    return dict(counts.most_common())


def _public_key_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        public = event.get("public_parameters") or event.get("configuration") or {}
        if isinstance(public, str):
            try:
                public = json.loads(public)
            except json.JSONDecodeError:
                public = {}
        for key, value in (public or {}).items():
            if _present(value):
                counts[str(key)] += 1
    return dict(counts.most_common())


def _message_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    messages = [str(event.get("free_text_message")) for event in events if _present(event.get("free_text_message"))]
    lengths = [float(len(message)) for message in messages]
    top_messages = Counter(messages).most_common(10)
    player_turns = [event for event in events if event.get("role") not in {"nature", "missing"}]
    return {
        "message_events": len(messages),
        "player_turns": len(player_turns),
        "message_rate_per_player_turn": len(messages) / len(player_turns) if player_turns else None,
        "length_chars": _summary(lengths),
        "unique_messages": len(set(messages)),
        "top_messages": [{"message": message, "count": count} for message, count in top_messages],
    }


def _support_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    bargaining_bins: Counter[str] = Counter()
    negotiation_bins: Counter[str] = Counter()
    persuasion_seller: Counter[str] = Counter()
    persuasion_buyer: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    by_family_role_action: Counter[str] = Counter()

    for event in events:
        family = str(event.get("game_family") or "missing")
        role = str(event.get("role") or "missing")
        action_type = str(event.get("action_type") or "missing")
        by_family_role_action[f"{family}:{role}:{action_type}"] += 1

        if family == "bargaining" and action_type == "offer":
            numeric = as_float(event.get("numeric_action"))
            config = event.get("configuration") or {}
            money = as_float(config.get("money_to_divide")) or 1.0
            if numeric is not None:
                bargaining_bins[_bin(numeric / money, width=0.1, low=0.0, high=1.0)] += 1

        if family == "negotiation" and action_type == "offer":
            numeric = as_float(event.get("numeric_action"))
            config = event.get("configuration") or {}
            order = as_float(config.get("product_price_order")) or 1.0
            if numeric is not None:
                negotiation_bins[_bin(numeric / order, width=0.1, low=0.0, high=1.5)] += 1

        if family == "persuasion":
            raw = event.get("raw_record") or {}
            decision = raw.get("decision")
            if role == "seller" and decision in {"yes", "no"}:
                persuasion_seller[str(decision)] += 1
            if role == "buyer" and decision in {"yes", "no"}:
                persuasion_buyer[str(decision)] += 1
            if action_type == "nature_quality":
                quality[str(raw.get("round_quality") or "missing")] += 1

    return {
        "by_family_role_action": dict(by_family_role_action.most_common()),
        "bargaining_offer_share_bins": dict(sorted(bargaining_bins.items())),
        "negotiation_price_bins": dict(sorted(negotiation_bins.items())),
        "persuasion_seller_recommendations": dict(persuasion_seller.most_common()),
        "persuasion_buyer_decisions": dict(persuasion_buyer.most_common()),
        "persuasion_quality": dict(quality.most_common()),
    }


def _repeated_identity_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    p1_models = Counter(str(game.get("player_1_model")) for game in games if _present(game.get("player_1_model")))
    p2_models = Counter(str(game.get("player_2_model")) for game in games if _present(game.get("player_2_model")))
    p1_names = Counter(str(game.get("player_1_name")) for game in games if _present(game.get("player_1_name")))
    p2_names = Counter(str(game.get("player_2_name")) for game in games if _present(game.get("player_2_name")))
    return {
        "player_1_model_availability": _field_rate(games, "player_1_model", require_nonempty=True),
        "player_2_model_availability": _field_rate(games, "player_2_model", require_nonempty=True),
        "top_player_1_models": dict(p1_models.most_common(20)),
        "top_player_2_models": dict(p2_models.most_common(20)),
        "repeated_public_names": {
            "player_1": {name: count for name, count in p1_names.most_common(20) if count > 1},
            "player_2": {name: count for name, count in p2_names.most_common(20) if count > 1},
        },
    }


def _turns_per_game(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(event.get("game_id")) for event in events if _present(event.get("game_id")))
    return _summary([float(value) for value in counts.values()])


def _schema_rates(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    game_fields = [
        "game_id",
        "game_family",
        "source",
        "config_id",
        "configuration",
        "terminal_outcome",
        "player_1_payoff",
        "player_2_payoff",
        "player_1_model",
        "player_2_model",
        "path",
    ]
    event_fields = [
        "event_id",
        "game_id",
        "game_family",
        "source",
        "config_id",
        "role",
        "round",
        "transcript_so_far",
        "action_type",
        "numeric_action",
        "free_text_message",
        "private_information",
        "public_parameters",
        "terminal_outcome",
        "player_payoff",
        "opponent_payoff",
    ]
    return {
        "game_fields": {
            field: _field_rate(games, field, require_nonempty=field in {"player_1_model", "player_2_model", "path"})
            for field in game_fields
        },
        "event_fields": {
            field: _field_rate(events, field, require_nonempty=field in {"numeric_action", "free_text_message"})
            for field in event_fields
        },
    }


def _strategy_verdict(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    game_count = len(games)
    event_count = len(events)
    has_messages = any(_present(event.get("free_text_message")) for event in events)
    has_private = any(_present(event.get("private_information")) for event in events)
    has_models = any(_present(game.get("player_1_model")) or _present(game.get("player_2_model")) for game in games)
    has_three_families = len({game.get("game_family") for game in games if _present(game.get("game_family"))}) >= 3

    if game_count == 0:
        verdict = "no_processed_dataset"
        budget = "Do not run large simulations. First ingest or obtain real GLEE records."
    elif game_count < 1000:
        verdict = "toy_or_smoke_dataset"
        budget = "Use simulation only for harness sanity checks and adversarial smoke tests. Do not treat synthetic rows as the main training dataset."
    elif game_count < 100000:
        verdict = "empirical_pilot_dataset"
        budget = "Use real data for priors and response-surface pilots. Keep simulation targeted to counterfactual and adversarial gaps."
    else:
        verdict = "empirical_foundation_candidate"
        budget = "Make real data the primary foundation. Simulation should be targeted stress testing, rare-event generation, and counterfactual policy evaluation."

    blockers = []
    if 0 < game_count < 1000:
        blockers.append("dataset_too_small_for_empirical_foundation")
    if not has_three_families:
        blockers.append("not_all_three_game_families_present")
    if not has_private:
        blockers.append("private_or_hidden_state_sparse_or_missing")
    if not has_messages:
        blockers.append("message_text_sparse_or_missing")
    if not has_models:
        blockers.append("player_or_model_identity_sparse_or_missing")
    if event_count == 0:
        blockers.append("no_turn_level_events")

    next_actions = [
        "Audit the largest real GLEE dataset you can access before scaling simulation.",
        "Use action-support bins to decide where offline response models are reliable.",
        "Use synthetic tournaments for smoke tests and adversarial search, not as the primary behavioral population.",
        "Only train behavioral or counterfactual models after confirming turn-level state, action, outcome, and hidden-state coverage.",
    ]

    return {
        "verdict": verdict,
        "simulation_budget": budget,
        "blockers": blockers,
        "next_actions": next_actions,
    }


def audit_records(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dataset_size": {
            "games": len(games),
            "events": len(events),
            "turns_per_game": _turns_per_game(events),
        },
        "distributions": {
            "games_by_family": _counter(games, "game_family"),
            "events_by_family": _counter(events, "game_family"),
            "games_by_source": _counter(games, "source"),
            "events_by_role": _counter(events, "role"),
            "events_by_action_type": _counter(events, "action_type"),
            "top_config_ids": _counter(games, "config_id", limit=25),
        },
        "schema_availability": _schema_rates(games, events),
        "identity": _repeated_identity_summary(games),
        "history_and_messages": _message_summary(events),
        "state_keys": {
            "public_parameter_keys": _public_key_counts(events),
            "private_information_keys": _private_key_counts(events),
        },
        "empirical_action_support": _support_summary(events),
        "strategy_recommendation": _strategy_verdict(games, events),
    }


def _fmt_rate(row: dict[str, Any]) -> str:
    rate = row.get("rate")
    return "" if rate is None else f"{rate:.3f}"


def _counter_table(title: str, rows: dict[str, int], limit: int = 20) -> list[str]:
    lines = [f"## {title}", "", "| Value | Count |", "|---|---:|"]
    if not rows:
        lines.append("| none | 0 |")
    for key, count in list(rows.items())[:limit]:
        lines.append(f"| {key} | {count} |")
    lines.append("")
    return lines


def audit_markdown(report: dict[str, Any]) -> str:
    size = report["dataset_size"]
    recommendation = report["strategy_recommendation"]
    lines = [
        "# GLEE Dataset Audit",
        "",
        f"Verdict: `{recommendation['verdict']}`",
        "",
        recommendation["simulation_budget"],
        "",
        "## Size",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Games | {size['games']} |",
        f"| Events | {size['events']} |",
        f"| Mean turns/events per game | {size['turns_per_game'].get('mean')} |",
        "",
    ]

    blockers = recommendation.get("blockers") or []
    lines.extend(["## Blockers", ""])
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("No immediate schema blockers detected by this lightweight audit.")
    lines.append("")

    lines.extend(_counter_table("Games By Family", report["distributions"]["games_by_family"]))
    lines.extend(_counter_table("Events By Role", report["distributions"]["events_by_role"]))
    lines.extend(_counter_table("Events By Action Type", report["distributions"]["events_by_action_type"]))

    lines.extend(["## Essential Event Field Availability", "", "| Field | Present | Total | Rate |", "|---|---:|---:|---:|"])
    essential = ["game_id", "game_family", "role", "round", "action_type", "transcript_so_far", "private_information", "public_parameters", "terminal_outcome"]
    event_fields = report["schema_availability"]["event_fields"]
    for field in essential:
        row = event_fields[field]
        lines.append(f"| {field} | {row['present']} | {row['total']} | {_fmt_rate(row)} |")
    lines.append("")

    messages = report["history_and_messages"]
    lines.extend(
        [
            "## Messages",
            "",
            f"- Message events: {messages['message_events']}",
            f"- Message rate per player turn: {messages['message_rate_per_player_turn']}",
            f"- Unique messages: {messages['unique_messages']}",
            "",
        ]
    )

    support = report["empirical_action_support"]
    lines.extend(_counter_table("Bargaining Offer Share Support", support["bargaining_offer_share_bins"]))
    lines.extend(_counter_table("Negotiation Price Support", support["negotiation_price_bins"]))
    lines.extend(_counter_table("Persuasion Seller Recommendations", support["persuasion_seller_recommendations"]))
    lines.extend(_counter_table("Persuasion Buyer Decisions", support["persuasion_buyer_decisions"]))

    lines.extend(["## Next Actions", ""])
    for item in recommendation["next_actions"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def audit_processed(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/dataset_audit",
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    games = read_records(data_dir / "processed" / "games.jsonl")
    events = read_records(data_dir / "processed" / "events.jsonl")
    report = audit_records(games, events)
    out = ensure_dir(output_dir)
    write_json(out / "audit.json", report)
    (out / "audit.md").write_text(audit_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Audit processed GLEE data for empirical-first strategy readiness.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/dataset_audit")
    args = parser.parse_args(argv)
    report = audit_processed(args.data_dir, args.output_dir)
    print(json.dumps(report["strategy_recommendation"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
