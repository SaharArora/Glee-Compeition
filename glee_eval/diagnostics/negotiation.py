from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from types import SimpleNamespace
from typing import Any

from glee_eval.data.dataset_audit import support_lookup
from glee_eval.data.ingest import as_float
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, read_json, write_json


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


def _game_args(config_or_args: Any) -> dict[str, Any]:
    payload = _as_dict(config_or_args)
    return _as_dict(payload.get("game_args")) if isinstance(payload.get("game_args"), (dict, str)) else payload


def _bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.8:
        return "0.8+"
    if value < 0.0:
        return "<0"
    start = int(value / 0.2) * 0.2
    return f"{start:.1f}-{start + 0.2:.1f}"


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": mean(ordered),
        "median": median(ordered),
        "p25": ordered[int((len(ordered) - 1) * 0.25)],
        "p75": ordered[int((len(ordered) - 1) * 0.75)],
        "min": ordered[0],
        "max": ordered[-1],
    }


def _floor_for(round_number: int | None, max_rounds: int | None, mode: str = "SAFE") -> float:
    remaining = max(1, (max_rounds or round_number or 1) - (round_number or 1) + 1)
    if mode == "EXPLOIT":
        floor = 0.16
    elif mode == "COMMIT":
        floor = 0.18
    else:
        floor = 0.22
    if remaining <= 2:
        floor = min(floor, 0.10)
    return floor


def _real_negotiation_rows(data_dir: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    games_path = Path(data_dir) / "processed" / "games.jsonl"
    for game in iter_jsonl(games_path):
        if game.get("game_family") != "negotiation":
            continue
        config = _game_args(game.get("configuration"))
        seller_value = as_float(config.get("seller_value"))
        buyer_value = as_float(config.get("buyer_value"))
        terminal = _as_dict(game.get("terminal_outcome"))
        price = as_float(terminal.get("normalized_price"))
        if seller_value is None or buyer_value is None or price is None:
            continue
        surplus = max(0.0, buyer_value - seller_value)
        if surplus <= 0:
            continue
        midpoint = seller_value + 0.5 * surplus
        round_number = int(as_float(terminal.get("agreement_round")) or 1)
        max_rounds = int(as_float(config.get("max_rounds")) or 6)
        for role in ["seller", "buyer"]:
            capture = (price - seller_value) / surplus if role == "seller" else (buyer_value - price) / surplus
            rows.append(
                {
                    "source": "real",
                    "game_id": game.get("game_id"),
                    "role": role,
                    "round": round_number,
                    "max_rounds": max_rounds,
                    "surplus": surplus,
                    "surplus_bucket": _bucket(surplus),
                    "price": price,
                    "midpoint": midpoint,
                    "price_residual": price - midpoint,
                    "capture": capture,
                    "capture_residual": capture - 0.5,
                    "floor": _floor_for(round_number, max_rounds),
                    "config": config,
                }
            )
    return rows


def _smoke_negotiation_rows(run_dir: str | Path | None) -> list[dict[str, Any]]:
    if not run_dir:
        return []
    episodes_path = Path(run_dir) / "datasets" / "episode_summary.jsonl"
    rows: list[dict[str, Any]] = []
    for episode in iter_jsonl(episodes_path):
        scenario = _as_dict(episode.get("scenario"))
        if scenario.get("game_family") != "negotiation":
            continue
        config = _game_args(scenario.get("public_parameters"))
        terminal = _as_dict(episode.get("terminal_outcome"))
        seller_value = as_float(config.get("seller_value"))
        buyer_value = as_float(config.get("buyer_value"))
        price = as_float(terminal.get("normalized_price"))
        surplus = None if seller_value is None or buyer_value is None else max(0.0, buyer_value - seller_value)
        capture = None
        if price is not None and surplus and surplus > 0:
            role = scenario.get("candidate_role")
            capture = (price - seller_value) / surplus if role == "seller" else (buyer_value - price) / surplus
        round_number = int(as_float(terminal.get("agreement_round")) or as_float((episode.get("metrics") or {}).get("critical_round")) or 1)
        max_rounds = int(as_float(config.get("max_rounds")) or 6)
        rows.append(
            {
                "source": "smoke",
                "episode_id": episode.get("episode_id"),
                "role": scenario.get("candidate_role"),
                "round": round_number,
                "max_rounds": max_rounds,
                "surplus": surplus,
                "surplus_bucket": _bucket(surplus),
                "price": price,
                "capture": capture,
                "floor": _floor_for(round_number, max_rounds),
                "candidate_payoff": as_float(episode.get("candidate_payoff")),
                "regret": as_float((episode.get("metrics") or {}).get("regret")),
                "failure_types": [failure.get("failure_type") for failure in episode.get("failure_diagnostics", [])],
                "config": config,
            }
        )
    return rows


def _group(rows: list[dict[str, Any]], fields: tuple[str, ...], value_key: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(value_key)
        if value is None:
            continue
        grouped[tuple(row.get(field) for field in fields)].append(float(value))
    output = []
    for key, values in grouped.items():
        payload = {field: key[idx] for idx, field in enumerate(fields)}
        payload.update(_summary(values))
        output.append(payload)
    return sorted(output, key=lambda item: tuple(str(item.get(field)) for field in fields))


def _floor_support_rows(real_rows: list[dict[str, Any]], support_index: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for row in real_rows:
        key = (row["role"], row["surplus_bucket"], row["round"])
        if key in seen:
            continue
        seen.add(key)
        config = row["config"]
        seller_value = as_float(config.get("seller_value")) or 0.0
        buyer_value = as_float(config.get("buyer_value")) or seller_value
        surplus = max(0.0, buyer_value - seller_value)
        if row["role"] == "seller":
            normalized = seller_value + row["floor"] * surplus
        else:
            normalized = buyer_value - row["floor"] * surplus
        action = {
            "action_type": "offer",
            "numeric_action": normalized * (as_float(config.get("product_price_order")) or 1_000_000.0),
            "structured": {"product_price": normalized * (as_float(config.get("product_price_order")) or 1_000_000.0)},
        }
        state = SimpleNamespace(round=row["round"], horizon=row["max_rounds"])
        rows.append(
            {
                "role": row["role"],
                "surplus_bucket": row["surplus_bucket"],
                "round": row["round"],
                "floor": row["floor"],
                "support": support_lookup("negotiation", config, row["role"], action, state, support_index=support_index),
            }
        )
    return rows


def _rank_causes(real_rows: list[dict[str, Any]], smoke_rows: list[dict[str, Any]], floor_support: list[dict[str, Any]]) -> list[dict[str, Any]]:
    causes = []
    real_below_floor = [row for row in real_rows if row.get("capture") is not None and row["capture"] < row["floor"]]
    real_capture = _summary([float(row["capture"]) for row in real_rows if row.get("capture") is not None])
    below_floor_rate = len(real_below_floor) / len(real_rows) if real_rows else None
    low_support_rate = (
        sum(1 for row in floor_support if (row.get("support") or {}).get("coverage_score", 0.0) < 0.35) / len(floor_support)
        if floor_support
        else None
    )
    smoke_under = [
        row
        for row in smoke_rows
        if row.get("regret") is not None and float(row["regret"]) > 0.25 and "UNDER_AGGRESSIVE" in set(row.get("failure_types") or [])
    ]
    smoke_payoffs = [float(row["candidate_payoff"]) for row in smoke_rows if row.get("candidate_payoff") is not None]
    smoke_captures = [float(row["capture"]) for row in smoke_rows if row.get("capture") is not None]

    if below_floor_rate is not None:
        causes.append(
            {
                "rank_score": below_floor_rate,
                "candidate_cause": "surplus_capture_floor_may_be_above_empirical_acceptance_region",
                "evidence": {
                    "real_accepted_rows": len(real_rows),
                    "real_below_floor_rows": len(real_below_floor),
                    "real_below_floor_rate": below_floor_rate,
                    "real_capture_summary": real_capture,
                },
                "testable_fix": "Run a negotiation-only A/B with floor scale 0.75 and compare shadow percentile plus rejection/no-agreement rate.",
            }
        )
    if low_support_rate is not None:
        causes.append(
            {
                "rank_score": low_support_rate,
                "candidate_cause": "floor_region_is_low_support_so_simulation_or_conservative_fallback_is_justified",
                "evidence": {
                    "floor_support_rows": len(floor_support),
                    "low_support_rate": low_support_rate,
                    "example_low_support": [row for row in floor_support if (row.get("support") or {}).get("coverage_score", 0.0) < 0.35][:5],
                },
                "testable_fix": "Route this bucket through counterfactual simulation before changing the floor.",
            }
        )
    if smoke_rows:
        causes.append(
            {
                "rank_score": len(smoke_under) / len(smoke_rows),
                "candidate_cause": "smoke_runs_show_under_aggressive_negotiation_outcomes",
                "evidence": {
                    "smoke_negotiation_rows": len(smoke_rows),
                    "under_aggressive_rows": len(smoke_under),
                    "under_aggressive_rate": len(smoke_under) / len(smoke_rows),
                    "candidate_payoff_summary": _summary(smoke_payoffs),
                    "candidate_capture_summary": _summary(smoke_captures),
                },
                "testable_fix": "Compare model-guided offers against rule-only offers by surplus bucket before expanding run size.",
            }
        )
    if not causes:
        causes.append(
            {
                "rank_score": 0.0,
                "candidate_cause": "insufficient_negotiation_evidence",
                "evidence": {"real_rows": len(real_rows), "smoke_rows": len(smoke_rows)},
                "testable_fix": "Run a negotiation-only experiment with at least 300 games and regenerate this diagnostic.",
            }
        )
    return sorted(causes, key=lambda row: row["rank_score"], reverse=True)


def diagnostic_hypothesis(report: dict[str, Any]) -> dict[str, Any]:
    top = (report.get("ranked_candidate_causes") or [{}])[0]
    return {
        "hypothesis": f"Negotiation weakness candidate: {top.get('candidate_cause', 'unknown')}.",
        "evidence": top.get("evidence", {}),
        "next_check": top.get("testable_fix", "Inspect negotiation diagnostic outputs."),
        "source": "negotiation_diagnostic",
    }


def negotiation_diagnostic(
    *,
    data_dir: str | Path,
    run_dir: str | Path | None = None,
    support_index: dict[str, Any] | None = None,
    output_dir: str | Path = "reports/negotiation_diagnostic",
) -> dict[str, Any]:
    if support_index is None:
        support_path = Path(run_dir or "") / "audit" / "support_index.json"
        support_index = read_json(support_path) if support_path.exists() else {"buckets": {}}
    real_rows = _real_negotiation_rows(data_dir)
    smoke_rows = _smoke_negotiation_rows(run_dir)
    floor_support = _floor_support_rows(real_rows, support_index)
    report = {
        "schema_version": 1,
        "real_rows": len(real_rows),
        "smoke_rows": len(smoke_rows),
        "real_by_role_surplus": _group(real_rows, ("role", "surplus_bucket"), "capture"),
        "real_price_residual_by_role_surplus": _group(real_rows, ("role", "surplus_bucket"), "price_residual"),
        "smoke_by_role_surplus": _group(smoke_rows, ("role", "surplus_bucket"), "candidate_payoff"),
        "smoke_failure_counts": dict(Counter(failure for row in smoke_rows for failure in (row.get("failure_types") or []) if failure)),
        "floor_support": floor_support,
        "ranked_candidate_causes": _rank_causes(real_rows, smoke_rows, floor_support),
    }
    out = ensure_dir(output_dir)
    write_json(out / "negotiation_diagnostic.json", report)
    (out / "negotiation_diagnostic.md").write_text(negotiation_markdown(report), encoding="utf-8")
    return report


def negotiation_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Negotiation Diagnostic",
        "",
        f"- Real role-rows: {report['real_rows']}",
        f"- Smoke/test role-rows: {report['smoke_rows']}",
        f"- Smoke failure counts: `{report.get('smoke_failure_counts', {})}`",
        "",
        "## Ranked Candidate Causes",
        "",
    ]
    for idx, cause in enumerate(report.get("ranked_candidate_causes", []), start=1):
        lines.extend(
            [
                f"### {idx}. {cause['candidate_cause']}",
                "",
                f"- Rank score: {cause['rank_score']}",
                f"- Evidence: `{cause['evidence']}`",
                f"- Testable fix: {cause['testable_fix']}",
                "",
            ]
        )
    lines.extend(["## Real Capture By Role/Surplus", "", "| Role | Surplus | Count | Mean | Median | P25 | P75 |", "|---|---|---:|---:|---:|---:|---:|"])
    for row in report.get("real_by_role_surplus", [])[:40]:
        lines.append(
            f"| {row.get('role')} | {row.get('surplus_bucket')} | {row.get('count')} | {row.get('mean')} | "
            f"{row.get('median')} | {row.get('p25')} | {row.get('p75')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose negotiation weakness using empirical residuals and run outputs.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--run-dir")
    parser.add_argument("--output-dir", default="reports/negotiation_diagnostic")
    args = parser.parse_args(argv)
    report = negotiation_diagnostic(data_dir=args.data_dir, run_dir=args.run_dir, output_dir=args.output_dir)
    print(json.dumps({"ranked_candidate_causes": report["ranked_candidate_causes"][:3]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
