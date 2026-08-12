from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.response_models.runtime import bargaining_keys, message_style, negotiation_keys, persuasion_keys
from glee_eval.storage.trajectories import ensure_dir, write_json


def _read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _slug_player(player: str | None) -> str:
    return str(player or "").strip().lower().replace(" ", "_")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _num(value: Any, default: float | None = None) -> float | None:
    parsed = as_float(value)
    return default if parsed is None else parsed


def _last_transcript_action(event: dict[str, Any], action_type: str) -> dict[str, Any] | None:
    transcript = event.get("transcript_so_far") or []
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except json.JSONDecodeError:
            transcript = []
    for item in reversed(transcript):
        if item.get("action_type") == action_type:
            return item
    return None


def _same_round_transcript_item(event: dict[str, Any], *, role: str | None = None, action_type: str | None = None) -> dict[str, Any] | None:
    transcript = event.get("transcript_so_far") or []
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except json.JSONDecodeError:
            transcript = []
    round_number = int(_num(event.get("round"), 0) or 0)
    for item in reversed(transcript):
        if int(_num(item.get("round"), 0) or 0) != round_number:
            continue
        if role is not None and item.get("role") != role:
            continue
        if action_type is not None and item.get("action_type") != action_type:
            continue
        return item
    return None


def _bargaining_share_to_responder(offer: dict[str, Any], responder_role: str, money: float) -> float | None:
    if not offer or money <= 0:
        return None
    raw = _as_dict(offer.get("raw") or offer.get("raw_record"))

    if offer.get("role") == responder_role and offer.get("self_gain") is not None:
        value = as_float(offer.get("self_gain"))
        return None if value is None else value / money
    if offer.get("role") != responder_role and offer.get("other_gain") is not None:
        value = as_float(offer.get("other_gain"))
        return None if value is None else value / money

    gain_keys = [key for key in raw if key.endswith("_gain") and as_float(raw.get(key)) is not None]
    if not gain_keys:
        return None
    proposer_key = f"{_slug_player(raw.get('player') or offer.get('player'))}_gain"
    if offer.get("role") == responder_role and proposer_key in gain_keys:
        key = proposer_key
    else:
        key = next((candidate for candidate in gain_keys if candidate != proposer_key), None)
    if key is None:
        role_key = "alice_gain" if responder_role in {"player_1", "seller"} else "bob_gain"
        key = role_key if role_key in gain_keys else gain_keys[0]
    value = as_float(raw.get(key))
    return None if value is None else value / money


def _extract_bargaining_example(event: dict[str, Any]) -> tuple[str, list[str], bool] | None:
    if event.get("game_family") != "bargaining" or event.get("action_type") != "decision":
        return None
    if event.get("accepted") is None and event.get("rejected") is None:
        return None
    offer = _last_transcript_action(event, "offer")
    if not offer:
        return None
    config = _as_dict(event.get("configuration") or event.get("public_parameters"))
    money = _num(config.get("money_to_divide"), 100.0) or 100.0
    share = _bargaining_share_to_responder(offer, str(event.get("role")), money)
    if share is None:
        return None
    success = bool(event.get("accepted"))
    return "bargaining", bargaining_keys(event, str(event.get("role")), share), success


def _extract_negotiation_example(event: dict[str, Any]) -> tuple[str, list[str], bool] | None:
    if event.get("game_family") != "negotiation" or event.get("action_type") != "decision":
        return None
    if event.get("accepted") is None and event.get("rejected") is None:
        return None
    offer = _last_transcript_action(event, "offer")
    if not offer:
        return None
    raw = _as_dict(offer.get("raw") or offer.get("raw_record"))
    price = _num(offer.get("numeric_action"), None)
    if price is None:
        price = _num(raw.get("product_price"), None)
    config = _as_dict(event.get("configuration") or event.get("public_parameters"))
    order = _num(config.get("product_price_order"), 1_000_000.0) or 1_000_000.0
    if price is None or order <= 0:
        return None
    success = bool(event.get("accepted"))
    return "negotiation", negotiation_keys(event, str(event.get("role")), price / order), success


def _extract_persuasion_example(event: dict[str, Any]) -> tuple[str, list[str], bool] | None:
    if event.get("game_family") != "persuasion" or event.get("role") != "buyer":
        return None
    if event.get("bought") is None:
        return None
    seller = _same_round_transcript_item(event, role="seller")
    if not seller:
        return None
    seller_raw = _as_dict(seller.get("raw") or seller.get("raw_record") or seller.get("structured"))
    recommendation = seller.get("buy_no_buy") or seller_raw.get("decision") or seller_raw.get("recommendation")
    nature = _same_round_transcript_item(event, role="nature", action_type="nature_quality")
    quality = None
    if nature:
        nature_raw = _as_dict(nature.get("raw") or nature.get("raw_record"))
        quality = nature.get("quality") or nature_raw.get("round_quality")
    message = seller.get("free_text_message") or seller_raw.get("message")
    success = bool(event.get("bought"))
    return "persuasion", persuasion_keys(event, str(recommendation), quality, message), success


def extract_response_example(event: dict[str, Any]) -> tuple[str, list[str], bool] | None:
    if event.get("game_family") == "bargaining":
        return _extract_bargaining_example(event)
    if event.get("game_family") == "negotiation":
        return _extract_negotiation_example(event)
    if event.get("game_family") == "persuasion":
        return _extract_persuasion_example(event)
    return None


def _empty_counts() -> dict[str, dict[str, int]]:
    return defaultdict(lambda: {"trials": 0, "successes": 0})  # type: ignore[return-value]


def _add_example(counts: dict[str, dict[str, dict[str, int]]], family: str, keys: list[str], success: bool) -> None:
    for key in keys:
        row = counts[family][key]
        row["trials"] += 1
        row["successes"] += int(success)


def _finalize_family(
    family_counts: dict[str, dict[str, int]],
    *,
    alpha: float,
    min_support: int,
) -> dict[str, Any]:
    global_row = family_counts.get("__global__", {"trials": 0, "successes": 0})
    global_trials = int(global_row.get("trials", 0))
    global_successes = int(global_row.get("successes", 0))
    global_rate = (global_successes + 1.0) / (global_trials + 2.0) if global_trials else 0.5
    buckets: dict[str, Any] = {}
    for key, raw in sorted(family_counts.items()):
        trials = int(raw["trials"])
        successes = int(raw["successes"])
        probability = (successes + alpha * global_rate) / (trials + alpha)
        uncertainty = (probability * (1.0 - probability) / max(1.0, trials + alpha)) ** 0.5
        buckets[key] = {
            "trials": trials,
            "successes": successes,
            "raw_rate": successes / trials if trials else None,
            "probability": probability,
            "uncertainty": uncertainty,
            "support_quality": min(1.0, trials / max(1, min_support)),
        }
    return {
        "global_trials": global_trials,
        "global_successes": global_successes,
        "global_rate": global_rate,
        "bucket_count": len(buckets),
        "buckets": buckets,
    }


def _training_report(model: dict[str, Any], summary: dict[str, Any]) -> str:
    lines = [
        "# Empirical Response Models",
        "",
        f"Created at: `{model['created_at']}`",
        "",
        "## Training Rows",
        "",
        f"- Events scanned: {summary['events_scanned']}",
        f"- Response examples: {summary['examples_total']}",
        f"- Skipped events: {summary['skipped_events']}",
        "",
        "## Family Summary",
        "",
        "| Family | Examples | Global Response Rate | Buckets |",
        "|---|---:|---:|---:|",
    ]
    for family in ["bargaining", "negotiation", "persuasion"]:
        family_model = model["families"].get(family, {})
        lines.append(
            f"| {family} | {summary['examples_by_family'].get(family, 0)} | "
            f"{family_model.get('global_rate')} | {family_model.get('bucket_count', 0)} |"
        )
    lines.extend(
        [
            "",
            "## How To Use",
            "",
            "Set `GLEE_RESPONSE_MODEL` to this directory or `model.json`, then run the agent normally:",
            "",
            "```bash",
            "export GLEE_RESPONSE_MODEL=models/response_v0",
            "python -m glee_eval experiment --agent my_agents.jordan_strategic:MyAgent --name empirical_smoke --games 100",
            "```",
            "",
            "The runtime applies support and uncertainty penalties, so sparse buckets should shift the agent back toward conservative behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def train_response_models(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "models/response_v0",
    *,
    alpha: float = 5.0,
    min_support: int = 50,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    events_path = data_dir / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    counts: dict[str, dict[str, dict[str, int]]] = defaultdict(_empty_counts)
    examples_by_family: Counter[str] = Counter()
    skipped = 0
    events_scanned = 0
    style_counts: Counter[str] = Counter()

    for event in _read_jsonl(events_path):
        events_scanned += 1
        example = extract_response_example(event)
        if example is None:
            skipped += 1
            continue
        family, keys, success = example
        _add_example(counts, family, keys, success)
        examples_by_family[family] += 1
        if family == "persuasion":
            seller = _same_round_transcript_item(event, role="seller")
            raw = _as_dict((seller or {}).get("raw") or (seller or {}).get("raw_record"))
            style_counts[message_style(raw.get("message"))] += 1

    families = {
        family: _finalize_family(counts.get(family, {}), alpha=alpha, min_support=min_support)
        for family in ["bargaining", "negotiation", "persuasion"]
    }
    summary = {
        "events_scanned": events_scanned,
        "examples_total": sum(examples_by_family.values()),
        "examples_by_family": dict(examples_by_family),
        "skipped_events": skipped,
        "message_style_counts": dict(style_counts.most_common()),
    }
    model = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dir": str(data_dir),
        "alpha": alpha,
        "min_support": min_support,
        "summary": summary,
        "families": families,
    }
    out = ensure_dir(output_dir)
    write_json(out / "model.json", model)
    write_json(out / "training_summary.json", summary)
    (out / "training_report.md").write_text(_training_report(model, summary), encoding="utf-8")
    return {"model": model, "summary": summary, "output_dir": str(out)}


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Train empirical response models from processed GLEE events.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="models/response_v0")
    parser.add_argument("--alpha", type=float, default=5.0)
    parser.add_argument("--min-support", type=int, default=50)
    args = parser.parse_args(argv)
    result = train_response_models(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        alpha=args.alpha,
        min_support=args.min_support,
    )
    print(json.dumps({"output_dir": result["output_dir"], **result["summary"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
