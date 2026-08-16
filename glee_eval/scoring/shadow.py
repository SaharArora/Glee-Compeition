from __future__ import annotations

import argparse
import json
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_csv, write_json, write_jsonl

FAMILIES = ("bargaining", "negotiation", "persuasion")
ROLE_MAP = {
    "bargaining": ("player_1", "player_2"),
    "negotiation": ("seller", "buyer"),
    "persuasion": ("seller", "buyer"),
}


@dataclass(frozen=True)
class BucketChoice:
    level: str
    key: str
    support: int


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


def _normalized_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    parsed = as_float(value)
    if parsed is not None:
        if abs(parsed - round(parsed)) < 1e-9:
            return int(round(parsed))
        return round(parsed, 6)
    return str(value)


def _canonical_json(payload: dict[str, Any]) -> str:
    clean = {str(key): _normalized_scalar(value) for key, value in sorted(payload.items()) if value is not None}
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def _game_args(config_or_args: Any) -> dict[str, Any]:
    payload = _as_dict(config_or_args)
    nested = payload.get("game_args")
    return _as_dict(nested) if isinstance(nested, (dict, str)) else payload


def _bin(value: Any, width: float, low: float, high: float) -> str:
    parsed = as_float(value)
    if parsed is None:
        return "unknown"
    if parsed < low:
        return f"<{low:.2f}"
    if parsed >= high:
        return f">={high:.2f}"
    start = int(((parsed - low) / width) + 1e-9) * width + low
    return f"{start:.2f}-{start + width:.2f}"


def _coarse_config(family: str, config_or_args: Any) -> dict[str, Any]:
    args = _game_args(config_or_args)
    if family == "bargaining":
        return {
            "max_rounds": args.get("max_rounds"),
            "complete_information": args.get("complete_information"),
            "messages_allowed": args.get("messages_allowed"),
            "delta_1": _bin(args.get("delta_1"), 0.05, 0.0, 1.0),
            "delta_2": _bin(args.get("delta_2"), 0.05, 0.0, 1.0),
        }
    if family == "negotiation":
        seller_value = as_float(args.get("seller_value"))
        buyer_value = as_float(args.get("buyer_value"))
        surplus = None if seller_value is None or buyer_value is None else max(0.0, buyer_value - seller_value)
        return {
            "max_rounds": args.get("max_rounds"),
            "complete_information": args.get("complete_information"),
            "seller_value": _bin(seller_value, 0.10, 0.0, 1.5),
            "buyer_value": _bin(buyer_value, 0.10, 0.0, 1.5),
            "surplus": _bin(surplus, 0.10, 0.0, 1.0),
        }
    if family == "persuasion":
        return {
            "total_rounds": args.get("total_rounds"),
            "p": _bin(args.get("p"), 0.10, 0.0, 1.0),
            "v": _bin(args.get("v"), 0.10, 0.0, 2.0),
            "c": _bin(args.get("c"), 0.10, 0.0, 1.5),
            "seller_message_type": args.get("seller_message_type"),
            "is_seller_know_cv": args.get("is_seller_know_cv"),
            "is_buyer_know_p": args.get("is_buyer_know_p"),
        }
    return {}


def _bucket_keys(family: str, role: str, config_or_args: Any) -> list[tuple[str, str]]:
    args = _game_args(config_or_args)
    return [
        ("exact", f"exact|{family}|{role}|{_canonical_json(args)}"),
        ("coarse", f"coarse|{family}|{role}|{_canonical_json(_coarse_config(family, args))}"),
        ("family_role", f"family_role|{family}|{role}"),
        ("family", f"family|{family}"),
    ]


def _role_payoffs(game: dict[str, Any]) -> list[tuple[str, float]]:
    family = str(game.get("game_family") or "")
    roles = ROLE_MAP.get(family)
    if not roles:
        return []
    p1 = as_float(game.get("player_1_payoff"))
    p2 = as_float(game.get("player_2_payoff"))
    rows: list[tuple[str, float]] = []
    if p1 is not None:
        rows.append((roles[0], p1))
    if p2 is not None:
        rows.append((roles[1], p2))
    return rows


def build_reference_tables(games_path: str | Path) -> dict[str, list[float]]:
    buckets: dict[str, list[float]] = defaultdict(list)
    for game in iter_jsonl(games_path):
        family = str(game.get("game_family") or "")
        config = game.get("configuration") or {}
        for role, payoff in _role_payoffs(game):
            keys = _bucket_keys(family, role, config)
            for _, key in keys:
                buckets[key].append(float(payoff))
            zone = _negotiation_trade_zone(family, config)
            if zone is not None:
                for _, key in keys:
                    buckets[f"{key}|trade_zone:{zone}"].append(float(payoff))
    return {key: sorted(values) for key, values in buckets.items()}


def _negotiation_trade_zone(family: str, config_or_args: Any) -> str | None:
    if family != "negotiation":
        return None
    args = _game_args(config_or_args)
    seller = as_float(args.get("seller_value"))
    buyer = as_float(args.get("buyer_value"))
    if seller is None or buyer is None:
        return None
    return "no_trade_zone" if buyer <= seller else "gains_from_trade"


def _choose_bucket(
    reference: dict[str, list[float]],
    family: str,
    role: str,
    config_or_args: Any,
    *,
    min_reference: int,
) -> BucketChoice | None:
    fallback: BucketChoice | None = None
    for level, key in _bucket_keys(family, role, config_or_args):
        support = len(reference.get(key, []))
        if support <= 0:
            continue
        if fallback is None:
            fallback = BucketChoice(level=level, key=key, support=support)
        if support >= min_reference:
            return BucketChoice(level=level, key=key, support=support)
    return fallback


def _choose_trade_zone_bucket(
    reference: dict[str, list[float]],
    family: str,
    role: str,
    config_or_args: Any,
    zone: str | None,
    *,
    min_reference: int,
) -> BucketChoice | None:
    if zone is None:
        return None
    fallback: BucketChoice | None = None
    for level, base_key in _bucket_keys(family, role, config_or_args):
        key = f"{base_key}|trade_zone:{zone}"
        support = len(reference.get(key, []))
        if support <= 0:
            continue
        if fallback is None:
            fallback = BucketChoice(level=level, key=key, support=support)
        if support >= min_reference:
            return BucketChoice(level=level, key=key, support=support)
    return fallback


def _stratification_warning(family: str, rows: list[dict]) -> dict | None:
    """Flag when a family's percentile pools structurally different sub-populations.

    Negotiation is the case that prompted this. 61% of real configs have no gains
    from trade, and in those 93.9% of real payoffs are exactly zero, against 34.9%
    in gains-from-trade configs. Scoring against the pooled reference therefore
    understates standing in no-trade games and overstates it in the rest --
    measured at 0.385 vs a within-stratum 0.508, and 0.769 vs 0.599.

    This is reported rather than corrected. Stratifying would make the number a
    better measure of *skill*, but the official leaderboard's formula is private
    and replicating it is explicitly out of scope, so a shadow score that diverges
    from it could be a worse predictor of *placement*. Naming the distortion is
    the part that is unambiguously right.
    """

    if family != "negotiation" or not rows:
        return None
    zones: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        zone = row.get("trade_zone")
        if (zone is None or row.get("trade_zone_stratified_percentile") is None
                or abs(float(row["trade_zone_stratified_percentile"]) - float(row["percentile"])) < 1e-12):
            continue
        zones[str(zone)].append(row)
    if len(zones) < 2:
        return None
    comparison = {}
    for zone, zone_rows in sorted(zones.items()):
        pooled = mean(float(row["percentile"]) for row in zone_rows)
        stratified = mean(float(row["trade_zone_stratified_percentile"]) for row in zone_rows)
        comparison[zone] = {
            "episodes": len(zone_rows),
            "mean_official_style_percentile": pooled,
            "mean_trade_zone_stratified_percentile": stratified,
            "difference": stratified - pooled,
        }
    return {
        "reason": "fallback buckets may pool no-trade-zone and gains-from-trade games",
        "episodes_by_zone": {zone: len(zone_rows) for zone, zone_rows in zones.items()},
        "run_specific_comparison": comparison,
        "not_used_for_rating_because": "the official formula is private and replicating it is out of scope",
    }


def percentile_rank(values: list[float], payoff: float) -> float | None:
    if not values:
        return None
    lower = bisect_left(values, payoff)
    upper = bisect_right(values, payoff)
    return (lower + 0.5 * (upper - lower)) / len(values)


def game_rating(percentile: float) -> float:
    return max(100.0, min(5000.0, 2000.0 + 8000.0 * (percentile - 0.5)))


def eta_for_game(game_index: int, *, eta_start: float, eta_floor: float, eta_decay_games: int) -> float:
    if eta_decay_games <= 1:
        return eta_floor
    progress = min(1.0, max(0.0, (game_index - 1) / float(eta_decay_games - 1)))
    return max(eta_floor, eta_start - progress * (eta_start - eta_floor))


def displayed_rating(raw_rating: float, games: int) -> float:
    if games <= 0:
        return 1000.0
    shrink = games / (games + 30.0)
    return 1000.0 + shrink * (raw_rating - 1000.0)


def _episode_fields(record: dict[str, Any]) -> tuple[str, str, dict[str, Any], float, str | None] | None:
    scenario = _as_dict(record.get("scenario"))
    family = str(scenario.get("game_family") or record.get("family") or "")
    role = str(scenario.get("candidate_role") or record.get("role") or "")
    config = _as_dict(scenario.get("public_parameters") or record.get("public_parameters"))
    payoff = as_float(record.get("candidate_payoff"))
    if family not in FAMILIES or not role or payoff is None:
        return None
    simulation = _as_dict(scenario.get("metadata")).get("simulation", {})
    return family, role, config, payoff, simulation.get("trigger") if isinstance(simulation, dict) else None


def score_episodes(
    episodes_path: str | Path,
    reference: dict[str, list[float]],
    *,
    min_reference: int = 20,
    eta_start: float = 0.01,
    eta_floor: float = 0.002,
    eta_decay_games: int = 120,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    raw_ratings = {family: 1000.0 for family in FAMILIES}
    games_by_family = Counter()
    skipped = 0

    for index, record in enumerate(iter_jsonl(episodes_path), start=1):
        fields = _episode_fields(record)
        if fields is None:
            skipped += 1
            continue
        family, role, config, payoff, simulation_trigger = fields
        choice = _choose_bucket(reference, family, role, config, min_reference=min_reference)
        trade_zone = _negotiation_trade_zone(family, config)
        trade_zone_choice = _choose_trade_zone_bucket(
            reference, family, role, config, trade_zone, min_reference=min_reference
        )
        trade_zone_values = reference.get(trade_zone_choice.key, []) if trade_zone_choice else []
        trade_zone_percentile = percentile_rank(trade_zone_values, payoff) if trade_zone_values else None
        percentile = None
        rating = None
        eta = None
        next_raw = raw_ratings[family]
        if choice:
            percentile = percentile_rank(reference.get(choice.key, []), payoff)
            if percentile is not None:
                rating = game_rating(percentile)
                games_by_family[family] += 1
                eta = eta_for_game(games_by_family[family], eta_start=eta_start, eta_floor=eta_floor, eta_decay_games=eta_decay_games)
                next_raw = max(100.0, min(5000.0, raw_ratings[family] + eta * (rating - raw_ratings[family])))
                raw_ratings[family] = next_raw

        scored.append(
            {
                "episode_id": record.get("episode_id"),
                "episode_index": index,
                "family": family,
                "role": role,
                "candidate_payoff": payoff,
                "percentile": percentile,
                "trade_zone": trade_zone,
                "trade_zone_stratified_percentile": trade_zone_percentile,
                "trade_zone_reference_support": len(trade_zone_values),
                "trade_zone_bucket_level": trade_zone_choice.level if trade_zone_choice else None,
                "game_rating": rating,
                "eta": eta,
                "raw_family_rating_after": next_raw,
                "bucket_level": choice.level if choice else None,
                "bucket_support": choice.support if choice else 0,
                "reference_key": choice.key if choice else None,
                "opponent_adjusted": False,
                "simulation_trigger": simulation_trigger,
            }
        )

    families: dict[str, Any] = {}
    for family in FAMILIES:
        rows = [row for row in scored if row["family"] == family and row["percentile"] is not None]
        levels = Counter(row["bucket_level"] for row in rows)
        raw = raw_ratings[family]
        games = int(games_by_family[family])
        families[family] = {
            "games_scored": games,
            "raw_rating": raw,
            "displayed_rating": displayed_rating(raw, games),
            "mean_percentile": mean([float(row["percentile"]) for row in rows]) if rows else None,
            "mean_game_rating": mean([float(row["game_rating"]) for row in rows]) if rows else None,
            "mean_payoff": mean([float(row["candidate_payoff"]) for row in rows]) if rows else None,
            "mean_trade_zone_stratified_percentile": mean(
                [float(row["trade_zone_stratified_percentile"]) for row in rows
                 if row.get("trade_zone_stratified_percentile") is not None]
            ) if any(row.get("trade_zone_stratified_percentile") is not None for row in rows) else None,
            "low_support_trade_zone_games": sum(
                1 for row in rows
                if row.get("trade_zone_stratified_percentile") is not None
                and int(row.get("trade_zone_reference_support") or 0) < min_reference
            ),
            "bucket_levels": dict(levels),
            "low_support_games": sum(1 for row in rows if int(row.get("bucket_support") or 0) < min_reference),
            "percentile_stratification_warning": _stratification_warning(family, rows),
        }

    overall_displayed = mean([families[family]["displayed_rating"] for family in FAMILIES])
    summary = {
        "schema_version": 2,
        "scoring_basis": "official_style_raw_percentile",
        "opponent_adjustment": "not_available_locally",
        "trade_zone_diagnostic": "reported_separately_and_never_used_for_rating",
        "formula": {
            "game_rating": "clamp(2000 + 8000 * (percentile - 0.5), 100, 5000)",
            "rating_update": "R_next = clamp(R + eta * (game_rating - R), 100, 5000)",
            "displayed_rating": "1000 + (games / (games + 30)) * (raw_rating - 1000)",
            "eta_schedule": {
                "eta_start": eta_start,
                "eta_floor": eta_floor,
                "eta_decay_games": eta_decay_games,
            },
        },
        "episodes_scored": sum(int(payload["games_scored"]) for payload in families.values()),
        "episodes_skipped": skipped,
        "overall_displayed_rating": overall_displayed,
        "families": families,
    }
    return scored, summary


def shadow_score(
    episodes_path: str | Path,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "runs/shadow_score",
    *,
    min_reference: int = 20,
    eta_start: float = 0.01,
    eta_floor: float = 0.002,
    eta_decay_games: int = 120,
) -> dict[str, Any]:
    games_path = Path(data_dir) / "processed" / "games.jsonl"
    if not games_path.exists():
        raise FileNotFoundError(f"Reference games not found: {games_path}")
    reference = build_reference_tables(games_path)
    scored, summary = score_episodes(
        episodes_path,
        reference,
        min_reference=min_reference,
        eta_start=eta_start,
        eta_floor=eta_floor,
        eta_decay_games=eta_decay_games,
    )
    out = ensure_dir(output_dir)
    scored_jsonl = write_jsonl(out / "scored_episodes.jsonl", scored)
    scored_csv = write_csv(out / "scored_episodes.csv", scored)
    summary_path = write_json(out / "shadow_score.json", summary)
    markdown_path = out / "shadow_score.md"
    markdown_path.write_text(shadow_score_markdown(summary), encoding="utf-8")
    return {
        "summary": summary,
        "paths": {
            "json": str(summary_path),
            "markdown": str(markdown_path),
            "scored_jsonl": str(scored_jsonl),
            "scored_csv": str(scored_csv),
        },
    }


def score_run(
    run_dir: str | Path,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    *,
    min_reference: int = 20,
    eta_start: float = 0.01,
    eta_floor: float = 0.002,
    eta_decay_games: int = 120,
) -> dict[str, Any]:
    run = Path(run_dir)
    episodes_path = run / "datasets" / "episode_summary.jsonl"
    if not episodes_path.exists():
        raise FileNotFoundError(f"Episode summaries not found: {episodes_path}")
    return shadow_score(
        episodes_path=episodes_path,
        data_dir=data_dir,
        output_dir=run / "shadow_score",
        min_reference=min_reference,
        eta_start=eta_start,
        eta_floor=eta_floor,
        eta_decay_games=eta_decay_games,
    )


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def shadow_score_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Shadow Leaderboard Score",
        "",
        f"Overall displayed rating estimate: **{_fmt(summary.get('overall_displayed_rating'))}**",
        "",
        "This is an official-style local estimate using raw percentile against ingested GLEE reference games. "
        "The live site's private opponent-strength adjustment is not available locally, so treat this as a directional shadow score, not an exact leaderboard replica.",
        "",
        "## Family Ratings",
        "",
        "| Family | Games | Displayed Rating | Raw Rating | Mean Percentile | Trade-Zone Diagnostic | Mean Game Rating | Low-Support Games | Bucket Levels |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family in FAMILIES:
        row = summary["families"][family]
        bucket_levels = ", ".join(f"{key}:{value}" for key, value in sorted((row.get("bucket_levels") or {}).items())) or ""
        lines.append(
            f"| {family} | {row['games_scored']} | {_fmt(row['displayed_rating'])} | {_fmt(row['raw_rating'])} | "
            f"{_fmt(row['mean_percentile'])} | {_fmt(row.get('mean_trade_zone_stratified_percentile'))} | "
            f"{_fmt(row['mean_game_rating'])} | {row['low_support_games']} | {bucket_levels} |"
        )
    lines.extend(
        [
            "",
            "## Negotiation Trade-Zone Diagnostic",
            "",
            "`trade_zone_stratified_percentile` compares negotiation payoff within the same role and trade-zone only. "
            "It is a run-specific skill diagnostic and is never used to derive the official-style rating because the live formula is private.",
            "",
            "## Formula",
            "",
            "- `game_rating = clamp(2000 + 8000 * (percentile - 0.5), 100, 5000)`",
            "- `R_next = clamp(R + eta * (game_rating - R), 100, 5000)`",
            "- `displayed = 1000 + (games / (games + 30)) * (raw_rating - 1000)`",
            "",
            "Bucket fallback order: exact configuration + role, coarse configuration + role, family + role, family.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python3 -m glee_eval shadow-score",
        description="Estimate an official-style GLEE leaderboard score from local episodes.",
    )
    parser.add_argument("--run-dir", help="Experiment run directory containing datasets/episode_summary.jsonl.")
    parser.add_argument("--episodes", help="Explicit episode_summary.jsonl path.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", help="Output directory. Defaults to RUN_DIR/shadow_score or runs/shadow_score.")
    parser.add_argument("--min-reference", type=int, default=20)
    parser.add_argument("--eta-start", type=float, default=0.01)
    parser.add_argument("--eta-floor", type=float, default=0.002)
    parser.add_argument("--eta-decay-games", type=int, default=120)
    args = parser.parse_args(argv)

    if args.run_dir:
        result = score_run(
            args.run_dir,
            data_dir=args.data_dir,
            min_reference=args.min_reference,
            eta_start=args.eta_start,
            eta_floor=args.eta_floor,
            eta_decay_games=args.eta_decay_games,
        )
    else:
        if not args.episodes:
            parser.error("Either --run-dir or --episodes is required.")
        output_dir = args.output_dir or "runs/shadow_score"
        result = shadow_score(
            args.episodes,
            data_dir=args.data_dir,
            output_dir=output_dir,
            min_reference=args.min_reference,
            eta_start=args.eta_start,
            eta_floor=args.eta_floor,
            eta_decay_games=args.eta_decay_games,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
