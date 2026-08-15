"""Conservatively reconstruct terminal episodes from live observation logs."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _base(last: dict[str, Any]) -> dict[str, Any]:
    state = last.get("game_state") or {}
    return {
        "game_id": last.get("game_id"),
        "game_family": last.get("game_family"),
        "role": last.get("your_player"),
        "last_round": state.get("round"),
        "last_phase": last.get("phase"),
        "last_action": last.get("action"),
        "terminal_status": "indeterminate",
        "basis": "opponent_terminal_response_not_observed",
        "normalized_payoff": None,
        "payoff_bounds": None,
        "missing_fields": ["terminal_result"],
    }


def _bargaining(last: dict[str, Any]) -> dict[str, Any]:
    row = _base(last)
    state, action = last.get("game_state") or {}, last.get("action") or {}
    decision = str(action.get("decision") or "").lower()
    if decision == "accept":
        player = str(last.get("your_player") or "")
        offer = state.get("last_offer") or {}
        gain = _number(offer.get(f"{player}_gain"))
        pot = _number(state.get("money_to_divide"))
        delta = _number(state.get("delta_1" if player == "player_1" else "delta_2"))
        round_no = _number(state.get("round"))
        missing = [name for name, value in ((f"{player}_gain", gain), ("money_to_divide", pot),
                                             (f"delta_{player[-1:]}", delta), ("round", round_no)) if value is None]
        if not missing and pot and delta is not None and round_no is not None:
            row.update(terminal_status="reconstructed", basis="candidate_accepted_last_offer",
                       normalized_payoff=(gain / pot) * delta ** (round_no - 1), missing_fields=[])
            row["payoff_bounds"] = [row["normalized_payoff"], row["normalized_payoff"]]
        else:
            row.update(basis="accepted_offer_missing_payoff_inputs", missing_fields=missing)
    elif decision in {"walkaway", "walk_away"}:
        row.update(terminal_status="reconstructed", basis="candidate_walked_away",
                   normalized_payoff=0.0, payoff_bounds=[0.0, 0.0], missing_fields=[])
    elif decision == "reject" and _number(state.get("round")) == _number(state.get("max_rounds")):
        row.update(terminal_status="reconstructed", basis="candidate_rejected_at_horizon",
                   normalized_payoff=0.0, payoff_bounds=[0.0, 0.0], missing_fields=[])
    return row


def _negotiation(last: dict[str, Any]) -> dict[str, Any]:
    row = _base(last)
    state, action = last.get("game_state") or {}, last.get("action") or {}
    decision = str(action.get("decision") or "")
    if decision == "WalkAway" or (decision == "RejectOffer" and
            _number(state.get("round")) == _number(state.get("max_rounds"))):
        row.update(terminal_status="reconstructed", basis="candidate_walked_away" if decision == "WalkAway"
                   else "candidate_rejected_at_horizon", normalized_payoff=0.0,
                   payoff_bounds=[0.0, 0.0], missing_fields=[])
    elif decision == "AcceptOffer":
        role = state.get(f"{last.get('your_player')}_role")
        own = _number(state.get(f"{last.get('your_player')}_value"))
        price = _number((state.get("last_offer") or {}).get("price"))
        missing = [name for name, value in (("own_value", own), ("last_offer.price", price)) if value is None]
        if not missing:
            raw = price - own if role == "seller" else own - price
            row["raw_payoff"] = raw
            row.update(terminal_status="reconstructed", basis="accepted_offer_raw_margin_only",
                       missing_fields=["product_price_order"])
        else:
            row.update(basis="accepted_offer_missing_payoff_inputs", missing_fields=missing)
    return row


def _persuasion(last: dict[str, Any]) -> dict[str, Any]:
    row = _base(last)
    state, action = last.get("game_state") or {}, last.get("action") or {}
    price, rounds = _number(state.get("product_price")), _number(state.get("total_rounds"))
    role = state.get(f"{last.get('your_player')}_role") or ("seller" if last.get("your_player") == "player_1" else "buyer")
    total = _number(state.get(f"{role}_total_payoff"))
    denom = price * rounds if price and rounds else None
    if role == "buyer" and str(action.get("decision") or "").lower() == "no":
        missing = [name for name, value in (("buyer_total_payoff", total), ("product_price", price),
                                             ("total_rounds", rounds)) if value is None]
        if not missing and denom:
            value = total / denom
            row.update(terminal_status="reconstructed", basis="final_buyer_declined",
                       normalized_payoff=value, payoff_bounds=[value, value], missing_fields=[])
        else:
            row.update(basis="final_buyer_declined_missing_payoff_inputs", missing_fields=missing)
    elif role == "buyer" and str(action.get("decision") or "").lower() == "yes":
        low, high = _number(state.get("u")), _number(state.get("v"))
        missing = [name for name, value in (("buyer_total_payoff", total), ("product_price", price),
                                             ("total_rounds", rounds), ("u", low), ("v", high)) if value is None]
        if not missing and denom:
            bounds = sorted(((total + low - price) / denom, (total + high - price) / denom))
            row.update(basis="final_purchase_quality_not_observed", payoff_bounds=bounds,
                       missing_fields=["terminal_product_quality"])
        else:
            row.update(basis="final_purchase_missing_payoff_inputs", missing_fields=missing)
    elif role == "seller" and total is not None and denom:
        bounds = sorted((total / denom, (total + price) / denom))
        row.update(basis="final_buyer_decision_not_observed", payoff_bounds=bounds,
                   missing_fields=["terminal_buyer_decision"])
    return row


def reconstruct_live_episodes(observations: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(observations)
    games: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        game_id = record.get("game_id")
        if not game_id:
            raise ValueError(f"Observation line {line_no} has no game_id")
        games[str(game_id)].append(record)
    handlers = {"bargaining": _bargaining, "negotiation": _negotiation, "persuasion": _persuasion}
    episodes = []
    for records in games.values():
        last = records[-1]
        handler = handlers.get(str(last.get("game_family")))
        episodes.append(handler(last) if handler else _base(last))
    episodes.sort(key=lambda row: str(row["game_id"]))

    summary: dict[str, Any] = {"games": len(episodes), "families": {}}
    for family in sorted({str(row["game_family"]) for row in episodes}):
        rows = [row for row in episodes if row["game_family"] == family]
        counts = Counter(row["terminal_status"] for row in rows)
        exact = all(row["normalized_payoff"] is not None for row in rows)
        summary["families"][family] = {
            "games": len(rows), "terminal_status_counts": dict(sorted(counts.items())),
            "comparable_payoff_status": "available" if exact else "unavailable",
            "comparable_mean_normalized_payoff": (
                sum(row["normalized_payoff"] for row in rows) / len(rows) if exact and rows else None
            ),
        }
    all_exact = bool(episodes) and all(row["normalized_payoff"] is not None for row in episodes)
    summary["comparable_payoff_status"] = "available" if all_exact else "unavailable"
    summary["comparable_mean_normalized_payoff"] = (
        sum(row["normalized_payoff"] for row in episodes) / len(episodes) if all_exact else None
    )
    return episodes, summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python3 -m glee_eval live-episodes",
                                     description="Reconstruct auditable terminal episodes from offline live observations.")
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    episodes, summary = reconstruct_live_episodes(args.observations)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "episodes.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in episodes), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
