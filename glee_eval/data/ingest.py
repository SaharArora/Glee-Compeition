from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from glee_eval.config import DEFAULT_DATA_DIR, DEFAULT_GLEE_ROOT
from glee_eval.data.schemas import compact_id
from glee_eval.storage.trajectories import write_json, write_table_bundle

FAMILIES = {"bargaining", "negotiation", "persuasion"}
SOURCES = {"llm_vs_llm", "human_vs_llm"}
NATURE = "Nature"


@dataclass(frozen=True)
class IngestResult:
    games: list[dict[str, Any]]
    events: list[dict[str, Any]]
    report: dict[str, Any]


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_game_csv(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    try:
        return float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def as_int(value: Any, default: int = 0) -> int:
    parsed = as_float(value)
    return int(parsed) if parsed is not None else default


def clean_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return None if text == "" else text
    return value


def discover_game_dirs(
    glee_root: str | Path = DEFAULT_GLEE_ROOT,
    limit: int | None = None,
    families: Iterable[str] | None = None,
    sources: Iterable[str] | None = None,
) -> list[Path]:
    data_root = Path(glee_root) / "Data"
    dirs: list[Path] = []
    if not data_root.exists():
        return dirs
    selected_sources = list(sources or SOURCES)
    selected_families = list(families or FAMILIES)
    for source in selected_sources:
        for family in selected_families:
            family_root = data_root / source / family
            if not family_root.exists():
                continue
            bucket_count = 0
            for root, _, files in os.walk(family_root):
                if "config.json" in files and "game.csv" in files:
                    dirs.append(Path(root))
                    bucket_count += 1
                    if limit is not None and bucket_count >= limit:
                        break
    return sorted(dirs)


def source_and_family(game_dir: Path, glee_root: str | Path = DEFAULT_GLEE_ROOT) -> tuple[str, str]:
    game_dir = Path(game_dir)
    try:
        rel = game_dir.resolve().relative_to((Path(glee_root) / "Data").resolve())
        parts = rel.parts
    except ValueError:
        parts = game_dir.parts
        if "Data" in parts:
            parts = parts[parts.index("Data") + 1 :]
    if len(parts) < 2:
        return "unknown", "unknown"
    return parts[0], parts[1]


def player_name(config: dict[str, Any], player_number: int) -> str:
    args = config.get(f"player_{player_number}_args", {}) or {}
    return args.get("public_name") or ("Alice" if player_number == 1 else "Bob")


def player_model(config: dict[str, Any], player_number: int) -> str | None:
    args = config.get(f"player_{player_number}_args", {}) or {}
    return args.get("model_name") or config.get(f"player_{player_number}_type")


def role_for_player(family: str, player: str, config: dict[str, Any]) -> str:
    p1 = player_name(config, 1)
    p2 = player_name(config, 2)
    if player == NATURE:
        return "nature"
    if family == "negotiation":
        return "seller" if player == p1 else "buyer" if player == p2 else "unknown"
    if family == "persuasion":
        if player == p1:
            return "seller"
        if player == p2 or player == "the buyer":
            return "buyer"
        return "unknown"
    if player == p1:
        return "player_1"
    if player == p2:
        return "player_2"
    return "unknown"


def visible_private_parameters(family: str, role: str, config: dict[str, Any]) -> dict[str, Any]:
    args = config.get("game_args", {}) or {}
    complete = bool(args.get("complete_information"))
    if family == "bargaining":
        if complete:
            return {"delta_1": args.get("delta_1"), "delta_2": args.get("delta_2")}
        if role == "player_1":
            return {"delta_1": args.get("delta_1")}
        if role == "player_2":
            return {"delta_2": args.get("delta_2")}
    if family == "negotiation":
        if complete:
            return {"seller_value": args.get("seller_value"), "buyer_value": args.get("buyer_value")}
        if role == "seller":
            return {"seller_value": args.get("seller_value")}
        if role == "buyer":
            return {"buyer_value": args.get("buyer_value")}
    if family == "persuasion":
        if role == "seller":
            params = {"p": args.get("p")}
            if args.get("is_seller_know_cv", True):
                params.update({"c": args.get("c"), "v": args.get("v")})
            return params
        if role == "buyer":
            params = {"c": args.get("c"), "v": args.get("v")}
            if args.get("is_buyer_know_p", True):
                params["p"] = args.get("p")
            return params
    return {}


def public_parameters(family: str, config: dict[str, Any]) -> dict[str, Any]:
    args = dict(config.get("game_args", {}) or {})
    if family == "bargaining" and not args.get("complete_information"):
        args.pop("delta_1", None)
        args.pop("delta_2", None)
    if family == "negotiation" and not args.get("complete_information"):
        args.pop("seller_value", None)
        args.pop("buyer_value", None)
    if family == "persuasion":
        if not args.get("is_seller_know_cv", True):
            # These are still known by buyers, but not public to both players.
            args.pop("c", None)
            args.pop("v", None)
        if not args.get("is_buyer_know_p", True):
            args.pop("p", None)
    return args


def row_action_type(family: str, row: dict[str, Any]) -> str:
    decision = clean_cell(row.get("decision"))
    if family == "bargaining":
        if decision in {"accept", "reject"}:
            return "decision"
        if any(key.endswith("_gain") and as_float(row.get(key)) is not None for key in row):
            return "offer"
    if family == "negotiation":
        if decision:
            return "decision"
        if as_float(row.get("product_price")) is not None:
            return "offer"
    if family == "persuasion":
        if clean_cell(row.get("round_quality")):
            return "nature_quality"
        if decision in {"yes", "no"}:
            player = clean_cell(row.get("player"))
            if player == NATURE:
                return "nature_quality"
            if player and player != "Alice":
                return "buy_decision"
            return "recommendation"
        if clean_cell(row.get("message")):
            return "message"
    return "unknown"


def numeric_action(family: str, row: dict[str, Any], config: dict[str, Any]) -> float | None:
    if family == "negotiation":
        return as_float(row.get("product_price"))
    if family == "bargaining":
        player = clean_cell(row.get("player"))
        if not player:
            return None
        key = f"{player.lower().replace(' ', '_')}_gain"
        return as_float(row.get(key))
    if family == "persuasion":
        return as_float(row.get("product_worth"))
    return None


def terminal_for_game(family: str, rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    if family == "bargaining":
        return terminal_bargaining(rows, config)
    if family == "negotiation":
        return terminal_negotiation(rows, config)
    if family == "persuasion":
        return terminal_persuasion(rows, config)
    return {"result": "unknown", "player_1_payoff": None, "player_2_payoff": None}


def terminal_bargaining(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    args = config.get("game_args", {}) or {}
    p1 = player_name(config, 1)
    p2 = player_name(config, 2)
    p1_key = f"{p1.lower().replace(' ', '_')}_gain"
    p2_key = f"{p2.lower().replace(' ', '_')}_gain"
    money = as_float(args.get("money_to_divide")) or 1.0
    delta_1 = as_float(args.get("delta_1")) or 1.0
    delta_2 = as_float(args.get("delta_2")) or 1.0
    last_decision = next((row for row in reversed(rows) if clean_cell(row.get("decision"))), None)
    accepted = last_decision is not None and clean_cell(last_decision.get("decision")) == "accept"
    agreement_round = as_int(last_decision.get("round")) if last_decision else None
    offer = None
    if accepted and last_decision:
        decision_idx = rows.index(last_decision)
        offer = next(
            (
                row
                for row in reversed(rows[:decision_idx])
                if as_float(row.get(p1_key)) is not None and as_float(row.get(p2_key)) is not None
            ),
            None,
        )
    p1_raw = as_float(offer.get(p1_key)) if offer else 0.0
    p2_raw = as_float(offer.get(p2_key)) if offer else 0.0
    round_index = max((agreement_round or 1) - 1, 0)
    return {
        "result": "accept" if accepted else "no_agreement",
        "agreement_round": agreement_round if accepted else None,
        "player_1_raw_gain": p1_raw,
        "player_2_raw_gain": p2_raw,
        "player_1_payoff": (p1_raw / money) * (delta_1**round_index) if accepted else 0.0,
        "player_2_payoff": (p2_raw / money) * (delta_2**round_index) if accepted else 0.0,
        "realized_surplus": ((p1_raw + p2_raw) / money) if accepted else 0.0,
    }


def terminal_negotiation(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    args = config.get("game_args", {}) or {}
    order = as_float(args.get("product_price_order")) or 1.0
    seller_value = as_float(args.get("seller_value")) or 0.0
    buyer_value = as_float(args.get("buyer_value")) or 0.0
    last_decision = next((row for row in reversed(rows) if clean_cell(row.get("decision"))), None)
    decision = clean_cell(last_decision.get("decision")) if last_decision else None
    accepted = decision == "AcceptOffer"
    agreement_round = as_int(last_decision.get("round")) if accepted and last_decision else None
    price = None
    if accepted and last_decision:
        decision_idx = rows.index(last_decision)
        offer = next((row for row in reversed(rows[:decision_idx]) if as_float(row.get("product_price")) is not None), None)
        price = as_float(offer.get("product_price")) if offer else None
    normalized_price = price / order if price is not None else None
    # Deliberately unclamped. Clamping at 0 made accepting a value-destroying
    # trade score identically to correctly walking away, which erased the
    # individual-rationality signal in exactly the configs where it matters --
    # 61% of real negotiation configs have no gains from trade. Bargaining
    # cannot go negative by construction and terminal_persuasion does not clamp
    # either, so negotiation was the odd one out.
    seller_payoff = (normalized_price - seller_value) if normalized_price is not None else 0.0
    buyer_payoff = (buyer_value - normalized_price) if normalized_price is not None else 0.0
    return {
        "result": decision or "no_agreement",
        "agreement_round": agreement_round,
        "final_price": price,
        "normalized_price": normalized_price,
        "player_1_payoff": seller_payoff if accepted else 0.0,
        "player_2_payoff": buyer_payoff if accepted else 0.0,
        "realized_surplus": seller_payoff + buyer_payoff if accepted else 0.0,
    }


def terminal_persuasion(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    args = config.get("game_args", {}) or {}
    product_price = as_float(args.get("product_price")) or 1.0
    sales = 0
    seller_payoff = 0.0
    buyer_payoff = 0.0
    high_bought = 0
    low_bought = 0
    quality_by_round: dict[int, float] = {}
    for row in rows:
        round_number = as_int(row.get("round"))
        if clean_cell(row.get("round_quality")):
            quality_by_round[round_number] = as_float(row.get("product_worth")) or 0.0
    for row in rows:
        if clean_cell(row.get("decision")) == "yes" and clean_cell(row.get("player")) != player_name(config, 1):
            round_number = as_int(row.get("round"))
            worth = quality_by_round.get(round_number, 0.0)
            sales += 1
            seller_payoff += product_price
            buyer_payoff += worth - product_price
            if worth >= product_price:
                high_bought += 1
            else:
                low_bought += 1
    total_rounds = as_float(args.get("total_rounds")) or max(1, len(quality_by_round))
    return {
        "result": "completed",
        "sales": sales,
        "high_quality_bought": high_bought,
        "low_quality_bought": low_bought,
        "player_1_payoff": seller_payoff / (product_price * total_rounds),
        "player_2_payoff": buyer_payoff / (product_price * total_rounds),
        "realized_surplus": (seller_payoff + buyer_payoff) / (product_price * total_rounds),
    }


def parse_game_dir(game_dir: str | Path, glee_root: str | Path = DEFAULT_GLEE_ROOT) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    game_dir = Path(game_dir)
    config = load_config(game_dir / "config.json")
    rows = load_game_csv(game_dir / "game.csv")
    source, family = source_and_family(game_dir, glee_root)
    family = config.get("game_type") or family
    game_id = game_dir.name
    terminal = terminal_for_game(family, rows, config)
    p1 = player_name(config, 1)
    p2 = player_name(config, 2)
    config_id = compact_id(source, family, config.get("experiment_name"), json.dumps(config.get("game_args", {}), sort_keys=True))
    game_record = {
        "game_id": game_id,
        "game_family": family,
        "source": source,
        "config_id": config_id,
        "configuration": config,
        "player_1_name": p1,
        "player_2_name": p2,
        "player_1_model": player_model(config, 1),
        "player_2_model": player_model(config, 2),
        "path": str(game_dir),
        "terminal_outcome": terminal,
        "player_1_payoff": terminal.get("player_1_payoff"),
        "player_2_payoff": terminal.get("player_2_payoff"),
    }
    events = []
    transcript: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cleaned = {key: clean_cell(value) for key, value in row.items()}
        player = cleaned.get("player") or "unknown"
        role = role_for_player(family, player, config)
        action_type = row_action_type(family, cleaned)
        decision = cleaned.get("decision")
        event = {
            "event_id": compact_id(game_id, index),
            "game_id": game_id,
            "game_family": family,
            "source": source,
            "configuration": config.get("game_args", {}),
            "config_id": config_id,
            "player_1_model": player_model(config, 1),
            "player_2_model": player_model(config, 2),
            "player": player,
            "role": role,
            "private_information": visible_private_parameters(family, role, config),
            "public_parameters": public_parameters(family, config),
            "round": as_int(cleaned.get("round")),
            "transcript_so_far": list(transcript),
            "action_type": action_type,
            "numeric_action": numeric_action(family, cleaned, config),
            "free_text_message": cleaned.get("message"),
            "accepted": decision in {"accept", "AcceptOffer"},
            "rejected": decision in {"reject", "RejectOffer"},
            "bought": decision == "yes" if family == "persuasion" and role == "buyer" else None,
            "terminal_outcome": terminal,
            "player_payoff": terminal.get("player_1_payoff") if role in {"player_1", "seller"} else terminal.get("player_2_payoff"),
            "opponent_payoff": terminal.get("player_2_payoff") if role in {"player_1", "seller"} else terminal.get("player_1_payoff"),
            "raw_record": cleaned,
        }
        events.append(event)
        transcript.append({"player": player, "role": role, "round": event["round"], "action_type": action_type, "raw": cleaned})
    return game_record, events


def ingest(
    glee_root: str | Path = DEFAULT_GLEE_ROOT,
    output_dir: str | Path = DEFAULT_DATA_DIR,
    limit: int | None = None,
    families: Iterable[str] | None = None,
    sources: Iterable[str] | None = None,
) -> IngestResult:
    selected_families = list(families or ["bargaining", "negotiation", "persuasion"])
    selected_sources = list(sources or ["llm_vs_llm", "human_vs_llm"])
    selected_family_set = set(selected_families)
    selected_source_set = set(selected_sources)
    games: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    dirs = discover_game_dirs(glee_root, limit=limit, families=selected_families, sources=selected_sources)
    parsed_count = 0
    for game_dir in dirs:
        source, family = source_and_family(game_dir, glee_root)
        if source not in selected_source_set or family not in selected_family_set:
            continue
        try:
            game_record, event_records = parse_game_dir(game_dir, glee_root)
            games.append(game_record)
            events.extend(event_records)
            parsed_count += 1
        except Exception as exc:
            failures.append({"path": str(game_dir), "error": f"{type(exc).__name__}: {exc}"})
    out = Path(output_dir)
    game_outputs = write_table_bundle(out / "processed" / "games", games)
    event_outputs = write_table_bundle(out / "processed" / "events", events)
    report = {
        "glee_root": str(glee_root),
        "raw_game_dirs_discovered": len(dirs),
        "games_parsed": len(games),
        "events_parsed": len(events),
        "failures": failures[:100],
        "failure_count": len(failures),
        "outputs": {"games": game_outputs, "events": event_outputs},
        "parquet_available": bool(game_outputs.get("parquet") and event_outputs.get("parquet")),
    }
    write_json(Path("reports") / "data_validation.json", report)
    return IngestResult(games=games, events=events, report=report)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Ingest released GLEE logs into normalized records.")
    parser.add_argument("--glee-root", default=str(DEFAULT_GLEE_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--limit", type=int, help="Maximum games per selected source/family bucket.")
    parser.add_argument("--families", default="bargaining,negotiation,persuasion")
    parser.add_argument("--sources", default="llm_vs_llm,human_vs_llm")
    args = parser.parse_args(argv)
    result = ingest(
        glee_root=args.glee_root,
        output_dir=args.output_dir,
        limit=args.limit,
        families=[part for part in args.families.split(",") if part],
        sources=[part for part in args.sources.split(",") if part],
    )
    print(json.dumps(result.report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
