"""Past-only deceptive-seller diagnostic on released persuasion decisions.

This module does not change the agent.  It asks whether a guard would have a
measurable premise: after a buyer has *observed* a seller recommend a low-quality
product, is the shipped posterior over-confident and are subsequent purchases
worse?  Evidence is reconstructed through ``state_from_event`` so it obeys the
same visibility rules as production.  In particular, myopic market statistics do
not reveal whether an unbought recommendation was a lie and are never promoted to
seller-honesty evidence here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.schemas import GameState
from glee_eval.data.transcripts import (
    persuasion_recommendation,
    persuasion_round_quality,
    same_round_transcript_item,
    transcript_item_decision,
    transcript_item_quality,
)
from glee_eval.population.splits import HOLDOUT, partition_of
from glee_eval.probes.extract import state_from_event
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json

MIN_REACH_DECISIONS = 200
MIN_REACH_GAMES = 30
MIN_REACH_RATE = 0.01


def past_dishonesty_evidence(state: GameState) -> dict[str, Any]:
    """Count only lies visible before the current decision.

    A persistent buyer sees prior recommendation/quality pairs.  A myopic buyer
    sees aggregate outcomes of purchased products, which cannot identify the
    seller's recommendation on an unbought product, so no lie count is inferred.
    """

    transcript = list(state.visible_transcript or [])
    myopic = bool(state.public_parameters.get("is_myopic")) or any(
        item.get("action_type") == "market_statistics" for item in transcript
    )
    if myopic:
        return {
            "observable": False,
            "reason": "myopic_market_statistics_do_not_identify_past_recommendations",
            "prior_yes_high": None,
            "prior_yes_low": None,
            "prior_yes_total": None,
        }

    qualities: dict[int, str] = {}
    recommendations: dict[int, str] = {}
    for item in transcript:
        round_number = int(as_float(item.get("round")) or 0)
        if round_number <= 0 or round_number >= state.round:
            continue
        quality = transcript_item_quality(item)
        if item.get("action_type") == "nature_quality" and quality in {"high-quality", "low-quality"}:
            qualities[round_number] = quality
        if item.get("role") == "seller":
            decision = transcript_item_decision(item)
            if decision in {"yes", "no"}:
                recommendations[round_number] = decision

    yes_high = yes_low = 0
    for round_number, recommendation in recommendations.items():
        if recommendation != "yes":
            continue
        quality = qualities.get(round_number)
        yes_high += int(quality == "high-quality")
        yes_low += int(quality == "low-quality")
    return {
        "observable": True,
        "reason": "persistent_visible_history",
        "prior_yes_high": yes_high,
        "prior_yes_low": yes_low,
        "prior_yes_total": yes_high + yes_low,
    }


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buys = [row for row in rows if row["agent_would_buy"]]
    return {
        "decisions": len(rows),
        "games": len({row["game_id"] for row in rows}),
        "mean_predicted": _mean(rows, "predicted"),
        "observed_high_quality_rate": _mean(rows, "was_high_quality"),
        "overconfidence": (
            _mean(rows, "predicted") - _mean(rows, "was_high_quality")
            if rows and _mean(rows, "predicted") is not None and _mean(rows, "was_high_quality") is not None
            else None
        ),
        "agent_buy_decisions": len(buys),
        "agent_buy_games": len({row["game_id"] for row in buys}),
        "agent_buy_mean_realized_surplus": _mean(buys, "realized_surplus"),
        "agent_buy_value_destroying_rate": _mean(buys, "value_destroying"),
    }


def _round_bucket(round_number: int) -> str:
    if round_number <= 3:
        return "1-3"
    if round_number <= 6:
        return "4-6"
    if round_number <= 10:
        return "7-10"
    return "11+"


def _evidence_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count == 2:
        return "2"
    if count <= 4:
        return "3-4"
    if count <= 9:
        return "5-9"
    return "10+"


def _stratum_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["pvc_regime"]),
        str(row["round_bucket"]),
        str(row["memory_mode"]),
        str(row["seller_message_type"]),
        str(row["evidence_count_bucket"]),
    )


def _matched_contrast(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Overlap-weighted lie-minus-no-lie contrasts within exact strata."""

    buckets: dict[tuple[str, ...], dict[bool, list[dict[str, Any]]]] = {}
    for row in rows:
        buckets.setdefault(_stratum_key(row), {True: [], False: []})[row["prior_yes_low"] > 0].append(row)

    calibration_weight = value_weight = 0
    calibration_delta = value_delta = 0.0
    calibration_strata = value_strata = 0
    matched_lie_rows: list[dict[str, Any]] = []
    matched_lie_buys: list[dict[str, Any]] = []
    for cohorts in buckets.values():
        lies, clean = cohorts[True], cohorts[False]
        if not lies or not clean:
            continue
        weight = min(len(lies), len(clean))
        lie_residual = sum(row["predicted"] - row["was_high_quality"] for row in lies) / len(lies)
        clean_residual = sum(row["predicted"] - row["was_high_quality"] for row in clean) / len(clean)
        calibration_weight += weight
        calibration_delta += weight * (lie_residual - clean_residual)
        calibration_strata += 1
        matched_lie_rows.extend(lies)

        lie_buys = [row for row in lies if row["agent_would_buy"]]
        clean_buys = [row for row in clean if row["agent_would_buy"]]
        if not lie_buys or not clean_buys:
            continue
        buy_weight = min(len(lie_buys), len(clean_buys))
        value_weight += buy_weight
        value_delta += buy_weight * (
            float(_mean(lie_buys, "realized_surplus")) - float(_mean(clean_buys, "realized_surplus"))
        )
        value_strata += 1
        matched_lie_buys.extend(lie_buys)

    return {
        "calibration_strata": calibration_strata,
        "value_strata": value_strata,
        "overlap_weighted_rows": calibration_weight,
        "overlap_weighted_buy_rows": value_weight,
        "effective_matched_buy_decisions": value_weight,
        "matched_prior_lie_rows": len(matched_lie_rows),
        "matched_prior_lie_games": len({row["game_id"] for row in matched_lie_rows}),
        "matched_prior_lie_buy_decisions": len(matched_lie_buys),
        "matched_prior_lie_buy_games": len({row["game_id"] for row in matched_lie_buys}),
        "lie_minus_no_lie_overconfidence": (
            calibration_delta / calibration_weight if calibration_weight else None
        ),
        "lie_minus_no_lie_realized_surplus": value_delta / value_weight if value_weight else None,
    }


def summarize_axis(rows: list[dict[str, Any]], axis: str) -> dict[str, Any]:
    held = [row for row in rows if row[f"{axis}_partition"] == HOLDOUT and row["observable"]]
    prior_lie = [row for row in held if row["prior_yes_low"] > 0]
    no_prior_lie = [row for row in held if row["prior_yes_low"] == 0]
    eligible_buys = [row for row in held if row["agent_would_buy"]]
    reached = [row for row in prior_lie if row["agent_would_buy"]]
    reach_rate = len(reached) / len(eligible_buys) if eligible_buys else 0.0
    prior_summary = _cohort(prior_lie)
    no_prior_summary = _cohort(no_prior_lie)
    worse_value = (
        prior_summary["agent_buy_mean_realized_surplus"] is not None
        and no_prior_summary["agent_buy_mean_realized_surplus"] is not None
        and prior_summary["agent_buy_mean_realized_surplus"]
        < no_prior_summary["agent_buy_mean_realized_surplus"]
    )
    matched = _matched_contrast(held)
    matched_reach_rate = (
        matched["effective_matched_buy_decisions"] / len(eligible_buys) if eligible_buys else 0.0
    )
    criteria = {
        "matched_positive_overconfidence_difference": bool(
            matched["lie_minus_no_lie_overconfidence"] is not None
            and matched["lie_minus_no_lie_overconfidence"] > 0
        ),
        "matched_worse_value_outcomes_after_prior_lie": bool(
            matched["lie_minus_no_lie_realized_surplus"] is not None
            and matched["lie_minus_no_lie_realized_surplus"] < 0
        ),
        "matched_reach_decisions_at_least_200": matched["effective_matched_buy_decisions"] >= MIN_REACH_DECISIONS,
        "matched_reach_games_at_least_30": matched["matched_prior_lie_buy_games"] >= MIN_REACH_GAMES,
        "matched_reach_at_least_1_percent": matched_reach_rate >= MIN_REACH_RATE,
    }
    return {
        "partition": HOLDOUT,
        "eligible_observable_yes_decisions": len(held),
        "eligible_agent_buy_decisions": len(eligible_buys),
        "prior_lie": prior_summary,
        "no_prior_lie": no_prior_summary,
        "reachable_agent_buy_decisions": len(reached),
        "reachable_games": len({row["game_id"] for row in reached}),
        "reach_rate": reach_rate,
        "unmatched_direction": {
            "positive_overconfidence_after_prior_lie": bool(
                prior_summary["overconfidence"] is not None and prior_summary["overconfidence"] > 0
            ),
            "worse_value_outcomes_after_prior_lie": worse_value,
        },
        "matched": {**matched, "reach_rate": matched_reach_rate},
        "criteria": criteria,
        "passes_all_kill_criteria": all(criteria.values()),
    }


def persuasion_past_dishonesty_audit(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/persuasion_past_dishonesty",
    *,
    agent_spec: str = "my_agents.jordan_strategic:MyAgent",
    limit: int | None = None,
) -> dict[str, Any]:
    from glee_eval.adapters.candidate_agent import load_agent

    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")
    agent = load_agent(agent_spec, seed=0)
    rows: list[dict[str, Any]] = []
    scanned = skipped = myopic_unobservable = 0
    for event in iter_jsonl(events_path):
        if event.get("game_family") != "persuasion" or event.get("role") != "buyer":
            continue
        if event.get("action_type") != "buy_decision" or event.get("bought") is None:
            continue
        scanned += 1
        if limit is not None and len(rows) >= limit:
            break
        quality = persuasion_round_quality(event)
        seller_item = same_round_transcript_item(event, role="seller")
        recommendation = persuasion_recommendation(seller_item)
        if quality not in {"high-quality", "low-quality"} or recommendation != "yes":
            if quality not in {"high-quality", "low-quality"} or recommendation not in {"yes", "no"}:
                skipped += 1
            continue
        state = state_from_event(event)
        visible = past_dishonesty_evidence(state)
        if not visible["observable"]:
            myopic_unobservable += 1
        beliefs = agent._persuasion_beliefs(state)
        evidence = agent._persuasion_evidence(state, beliefs)
        control = agent._control(state, beliefs, evidence, "persuasion")
        # Use the exact production reader.  Under incomplete information these
        # values may be private even though they are still known to the buyer.
        high_value = as_float(beliefs.get("high_value"))
        low_value = as_float(beliefs.get("low_value"))
        if high_value is None or low_value is None:
            skipped += 1
            continue
        realized = high_value - 1.0 if quality == "high-quality" else low_value - 1.0
        rows.append(
            {
                "game_id": str(event.get("game_id")),
                "config_id": str(event.get("config_id")),
                "round": int(event.get("round") or 0),
                "observable": visible["observable"],
                "prior_yes_high": visible["prior_yes_high"],
                "prior_yes_low": visible["prior_yes_low"],
                "prior_yes_total": visible["prior_yes_total"],
                "predicted": float(beliefs.get("posterior_quality_given_yes") or 0.0),
                "was_high_quality": int(quality == "high-quality"),
                "agent_would_buy": agent._persuasion_buy_decision(state, control) == "yes",
                "realized_surplus": realized,
                "value_destroying": int(realized < 0),
                "pvc_regime": "|".join(
                    f"{name}={float(value):.6g}"
                    for name, value in (
                        ("p", beliefs.get("base_quality_prob")),
                        ("v", high_value),
                        ("c", low_value),
                    )
                ),
                "round_bucket": _round_bucket(int(event.get("round") or 0)),
                "memory_mode": "persistent" if visible["observable"] else "myopic",
                "seller_message_type": str(state.public_parameters.get("seller_message_type") or "unknown"),
                "evidence_count_bucket": (
                    _evidence_bucket(int(visible["prior_yes_total"] or 0))
                    if visible["observable"] else "unobservable"
                ),
                "model_partition": partition_of(event, "model"),
                "config_partition": partition_of(event, "config"),
            }
        )

    axes = {axis: summarize_axis(rows, axis) for axis in ("model", "config")}
    report = {
        "schema_version": 1,
        "events_considered": scanned,
        "yes_recommendation_rows_used": len(rows),
        "rows_skipped_schema": skipped,
        "myopic_yes_rows_unobservable": myopic_unobservable,
        "axes": axes,
        "kill_criteria": {
            "required_on_each_axis": [
                "matched_positive_overconfidence_difference",
                "matched_worse_value_outcomes_after_prior_lie",
                "matched_reach_decisions_at_least_200",
                "matched_reach_games_at_least_30",
                "matched_reach_at_least_1_percent",
            ],
            "survives_both_axes": all(summary["passes_all_kill_criteria"] for summary in axes.values()),
        },
        "notes": [
            "All dishonesty evidence is production-visible and strictly precedes the current decision.",
            "Myopic market statistics do not identify past seller recommendations; those rows are not imputed.",
            "This is one-step released-data evidence, not a payoff promotion or trajectory-level causal estimate.",
        ],
    }
    out = ensure_dir(output_dir)
    write_json(out / "persuasion_past_dishonesty.json", report)
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Past-only deceptive-seller diagnostic.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/persuasion_past_dishonesty")
    parser.add_argument("--agent", default="my_agents.jordan_strategic:MyAgent")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    report = persuasion_past_dishonesty_audit(
        args.data_dir, args.output_dir, agent_spec=args.agent, limit=args.limit
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
