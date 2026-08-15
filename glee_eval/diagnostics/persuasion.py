"""Is the buyer's purchase rule calibrated, and are its purchases individually rational?

The first debug report suspected the break-even purchase rule of admitting
negative-expected-value buys, on the strength of one IR violation in a synthetic
run. That was never actually tested. This tests it against real buyer decisions.

Two questions, kept separate because they have different answers and different
fixes:

1. **Calibration.** The rule buys when its posterior belief that the product is
   high quality clears a break-even threshold. If that posterior is systematically
   too high, the rule buys things it should not, and no amount of threshold tuning
   fixes it. Measured reliability-diagram style: bin the predicted probability,
   compare each bin against the frequency actually observed.
2. **Realized decision quality.** Independently of calibration, what did the rule's
   purchases actually earn? A rule can be badly calibrated and still profitable, or
   well calibrated and unprofitable, so the realized payoff is reported on its own.

The realized quality is read from the transcript for scoring only. It is never
placed in the state the agent sees.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import (
    persuasion_recommendation,
    persuasion_round_quality,
    same_round_transcript_item,
    transcript_item_decision,
    transcript_item_quality,
    transcript_items,
)
from glee_eval.population.splits import partition_of
from glee_eval.probes.extract import state_from_event
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json

DEFAULT_BINS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
PLATT_EPSILON = 1e-6
PLATT_BOOTSTRAP_SEED = 20260815
PLATT_BOOTSTRAP_REPLICATES = 2000


def _bin_label(value: float, edges: tuple[float, ...]) -> str:
    for low, high in zip(edges, edges[1:]):
        if low <= value < high:
            return f"{low:.1f}-{high:.1f}"
    return f"{edges[-2]:.1f}-{edges[-1]:.1f}"


def _summarize_bins(rows: list[dict[str, Any]], edges: tuple[float, ...]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(_bin_label(row["predicted"], edges), []).append(row)
    out = []
    for label in sorted(buckets):
        group = buckets[label]
        predicted = sum(row["predicted"] for row in group) / len(group)
        observed = sum(row["was_high_quality"] for row in group) / len(group)
        out.append(
            {
                "bin": label,
                "n": len(group),
                "mean_predicted": predicted,
                "observed_frequency": observed,
                "gap": predicted - observed,
            }
        )
    return out


def _expected_calibration_error(bins: list[dict[str, Any]]) -> float | None:
    total = sum(row["n"] for row in bins)
    if not total:
        return None
    return sum(row["n"] * abs(row["gap"]) for row in bins) / total


def _purchase_channel_stats(event: dict[str, Any]) -> dict[str, Any]:
    """Audit prior purchases without placing their outcomes in agent-visible state.

    Market statistics report quality among *purchased* products.  The posterior
    used by the buy rule is quality conditional on a positive recommendation.
    Those estimands coincide only when every purchase followed ``yes``.  Keep the
    recommendation-conditioned counts here as diagnostic scoring data so that
    the calibration report can measure that assumption explicitly.
    """

    current_round = int(as_float(event.get("round")) or 0)
    items = [item for item in transcript_items(event) if int(as_float(item.get("round")) or 0) < current_round]
    seller_by_round = {
        int(as_float(item.get("round")) or 0): transcript_item_decision(item)
        for item in items
        if item.get("role") == "seller"
    }
    quality_by_round = {
        int(as_float(item.get("round")) or 0): transcript_item_quality(item)
        for item in items
        if item.get("action_type") == "nature_quality"
    }
    purchases = high_purchases = after_yes = high_after_yes = after_no = unknown_recommendation = 0
    for item in items:
        if item.get("role") != "buyer" or item.get("action_type") != "buy_decision":
            continue
        if transcript_item_decision(item) != "yes":
            continue
        round_number = int(as_float(item.get("round")) or 0)
        recommendation = seller_by_round.get(round_number)
        quality = quality_by_round.get(round_number)
        purchases += 1
        high_purchases += int(quality == "high-quality")
        if recommendation == "yes":
            after_yes += 1
            high_after_yes += int(quality == "high-quality")
        elif recommendation == "no":
            after_no += 1
        else:
            unknown_recommendation += 1
    if purchases == 0:
        alignment = "no_purchases"
    elif after_yes == purchases:
        alignment = "all_after_yes"
    elif after_no:
        alignment = "contains_after_no"
    else:
        alignment = "unknown_recommendation"
    return {
        "prior_purchases": purchases,
        "prior_high_quality_purchases": high_purchases,
        "prior_purchases_after_yes": after_yes,
        "prior_high_quality_after_yes": high_after_yes,
        "prior_purchases_after_no": after_no,
        "prior_purchases_with_unknown_recommendation": unknown_recommendation,
        "purchase_recommendation_alignment": alignment,
    }


def _calibration_slice(rows: list[dict[str, Any]], bins: tuple[float, ...]) -> dict[str, Any]:
    summarized = _summarize_bins(rows, bins)
    return {
        "n": len(rows),
        "bins": summarized,
        "expected_calibration_error": _expected_calibration_error(summarized),
        "brier_score": (
            sum((row["predicted"] - row["was_high_quality"]) ** 2 for row in rows) / len(rows)
            if rows else None
        ),
    }


def _grouped_calibration(
    rows: list[dict[str, Any]], key: str, bins: tuple[float, ...]
) -> dict[str, dict[str, Any]]:
    values = sorted({str(row.get(key, "unknown")) for row in rows})
    return {
        value: _calibration_slice([row for row in rows if str(row.get(key, "unknown")) == value], bins)
        for value in values
    }


def _clip_probability(value: float) -> float:
    return min(max(float(value), PLATT_EPSILON), 1.0 - PLATT_EPSILON)


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _fit_platt(rows: list[dict[str, Any]]) -> tuple[float, float]:
    """Maximum-likelihood two-parameter Platt map, fitted without dependencies."""

    if not rows:
        raise ValueError("Cannot fit Platt calibration without rows")
    a, b = 0.0, 1.0
    for _ in range(100):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for row in rows:
            p = _clip_probability(row["predicted"])
            x = math.log(p / (1.0 - p))
            y = float(row["was_high_quality"])
            q = _sigmoid(a + b * x)
            residual = q - y
            weight = max(q * (1.0 - q), 1e-12)
            g_a += residual
            g_b += residual * x
            h_aa += weight
            h_ab += weight * x
            h_bb += weight * x * x
        determinant = h_aa * h_bb - h_ab * h_ab
        if determinant <= 1e-18:
            raise ValueError("Platt calibration Hessian is singular")
        step_a = (h_bb * g_a - h_ab * g_b) / determinant
        step_b = (-h_ab * g_a + h_aa * g_b) / determinant
        a -= step_a
        b -= step_b
        if max(abs(step_a), abs(step_b)) < 1e-10:
            break
    return a, b


def _platt_probability(raw: float, a: float, b: float) -> float:
    p = _clip_probability(raw)
    return _clip_probability(_sigmoid(a + b * math.log(p / (1.0 - p))))


def _log_loss(probability: float, outcome: float) -> float:
    p = _clip_probability(probability)
    return -(outcome * math.log(p) + (1.0 - outcome) * math.log(1.0 - p))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _game_cluster_bootstrap(
    per_game: dict[str, tuple[int, float, float]],
    *,
    seed: int = PLATT_BOOTSTRAP_SEED,
    replicates: int = PLATT_BOOTSTRAP_REPLICATES,
) -> dict[str, list[float]]:
    """Paired bootstrap of whole games; repeated rows never split across samples."""

    game_ids = sorted(per_game)
    if not game_ids or replicates <= 0:
        raise ValueError("Bootstrap requires games and positive replicates")
    rng = random.Random(seed)
    brier: list[float] = []
    log_loss: list[float] = []
    for _ in range(replicates):
        count = brier_sum = log_loss_sum = 0.0
        for _ in game_ids:
            n, game_brier, game_log_loss = per_game[game_ids[rng.randrange(len(game_ids))]]
            count += n
            brier_sum += game_brier
            log_loss_sum += game_log_loss
        brier.append(brier_sum / count)
        log_loss.append(log_loss_sum / count)
    return {
        "brier": [_percentile(brier, 0.025), _percentile(brier, 0.975)],
        "log_loss": [_percentile(log_loss, 0.025), _percentile(log_loss, 0.975)],
    }


def _named_bin_gap(rows: list[dict[str, Any]], prediction_key: str) -> dict[str, Any]:
    selected = [row for row in rows if 0.5 <= row[prediction_key] < 0.8]
    if not selected:
        return {"n": 0, "mean_predicted": None, "observed_frequency": None, "gap": None}
    predicted = sum(row[prediction_key] for row in selected) / len(selected)
    observed = sum(row["was_high_quality"] for row in selected) / len(selected)
    return {"n": len(selected), "mean_predicted": predicted, "observed_frequency": observed, "gap": predicted - observed}


def _evaluate_platt_axis(
    rows: list[dict[str, Any]],
    axis: str,
    bins: tuple[float, ...] = DEFAULT_BINS,
    *,
    bootstrap_seed: int = PLATT_BOOTSTRAP_SEED,
    bootstrap_replicates: int = PLATT_BOOTSTRAP_REPLICATES,
) -> dict[str, Any]:
    partition_key = f"{axis}_partition"
    fit_rows = [row for row in rows if row[partition_key] == "fit"]
    holdout = [dict(row) for row in rows if row[partition_key] == "holdout"]
    if not holdout:
        raise ValueError(f"Cannot evaluate Platt calibration without {axis} holdout rows")
    a, b = _fit_platt(fit_rows)
    per_game: dict[str, tuple[int, float, float]] = {}
    brier_delta = log_loss_delta = 0.0
    for row in holdout:
        raw = _clip_probability(row["predicted"])
        calibrated = _platt_probability(raw, a, b)
        outcome = float(row["was_high_quality"])
        row["calibrated"] = calibrated
        row_brier = (calibrated - outcome) ** 2 - (raw - outcome) ** 2
        row_log_loss = _log_loss(calibrated, outcome) - _log_loss(raw, outcome)
        brier_delta += row_brier
        log_loss_delta += row_log_loss
        game_id = str(row["game_id"])
        n, game_brier, game_log_loss = per_game.get(game_id, (0, 0.0, 0.0))
        per_game[game_id] = (n + 1, game_brier + row_brier, game_log_loss + row_log_loss)
    intervals = _game_cluster_bootstrap(
        per_game, seed=bootstrap_seed, replicates=bootstrap_replicates
    )
    calibrated_rows = [{**row, "predicted": row["calibrated"]} for row in holdout]
    return {
        "axis": axis,
        "fit_n": len(fit_rows),
        "holdout_n": len(holdout),
        "holdout_games": len(per_game),
        "parameters": {"a": a, "b": b},
        "bootstrap": {"seed": bootstrap_seed, "replicates": bootstrap_replicates, "cluster": "game_id"},
        "brier_delta": {"mean": brier_delta / len(holdout), "ci95": intervals["brier"]},
        "log_loss_delta": {"mean": log_loss_delta / len(holdout), "ci95": intervals["log_loss"]},
        "raw": {
            "ece": _calibration_slice(holdout, bins)["expected_calibration_error"],
            "gap_0.5_0.8": _named_bin_gap(holdout, "predicted"),
        },
        "calibrated": {
            "ece": _calibration_slice(calibrated_rows, bins)["expected_calibration_error"],
            "gap_0.5_0.8": _named_bin_gap(holdout, "calibrated"),
        },
        "success": (
            brier_delta / len(holdout) < 0.0
            and intervals["brier"][1] < 0.0
            and intervals["log_loss"][1] <= 0.0
        ),
    }


def persuasion_calibration(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/persuasion_calibration",
    *,
    agent_spec: str = "my_agents.jordan_strategic:MyAgent",
    limit: int | None = None,
    bins: tuple[float, ...] = DEFAULT_BINS,
) -> dict[str, Any]:
    from glee_eval.adapters.candidate_agent import load_agent

    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    agent = load_agent(agent_spec, seed=0)
    rows: list[dict[str, Any]] = []
    scanned = 0
    skipped = 0

    for event in iter_jsonl(events_path):
        if event.get("game_family") != "persuasion" or event.get("role") != "buyer":
            continue
        if event.get("action_type") != "buy_decision" or event.get("bought") is None:
            continue
        scanned += 1
        if limit and len(rows) >= limit:
            break

        quality = persuasion_round_quality(event)
        seller_item = same_round_transcript_item(event, role="seller")
        recommendation = persuasion_recommendation(seller_item)
        if quality not in {"high-quality", "low-quality"} or recommendation not in {"yes", "no"}:
            skipped += 1
            continue

        state = state_from_event(event)
        config = state.public_parameters or {}
        price = as_float(config.get("product_price")) or 1.0
        high_value = as_float(config.get("v"))
        low_value = as_float(config.get("c"))
        if high_value is None or low_value is None or price <= 0:
            skipped += 1
            continue

        beliefs = agent._persuasion_beliefs(state)
        evidence = agent._persuasion_evidence(state, beliefs)
        control = agent._control(state, beliefs, evidence, "persuasion")
        would_buy = agent._persuasion_buy_decision(state, control) == "yes"

        # v and c are multipliers of the price, so realized surplus per unit price
        # is (v - 1) on a high-quality product and (c - 1) on a low-quality one.
        realized = (high_value - 1.0) if quality == "high-quality" else (low_value - 1.0)
        purchase_stats = _purchase_channel_stats(event)
        evidence_count = int(float(beliefs.get("evidence_observations") or 0.0))
        rows.append(
            {
                "predicted": float(beliefs.get("posterior_quality_given_yes") or 0.0),
                "was_high_quality": 1 if quality == "high-quality" else 0,
                "recommendation": recommendation,
                "agent_would_buy": bool(would_buy),
                "real_buyer_bought": bool(event.get("bought")),
                "realized_surplus_if_bought": realized,
                "is_myopic": bool(config.get("is_myopic")),
                "evidence_channel": "market_statistics" if bool(config.get("is_myopic")) else "transcript_history",
                "evidence_count": evidence_count,
                "evidence_band": "0" if evidence_count == 0 else "1-3" if evidence_count <= 3 else "4+",
                "base_quality_probability": float(beliefs.get("base_quality_prob") or 0.0),
                "seller_message_type": str(config.get("seller_message_type") or "unknown"),
                "game_id": str(event.get("game_id") or ""),
                "source": str(event.get("source") or "unknown"),
                "model_partition": partition_of(event, "model"),
                "config_partition": partition_of(event, "config"),
                **purchase_stats,
            }
        )

    on_yes = [row for row in rows if row["recommendation"] == "yes"]
    agent_buys = [row for row in rows if row["agent_would_buy"]]
    real_buys = [row for row in rows if row["real_buyer_bought"]]

    def _mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    calibration_bins = _summarize_bins(on_yes, bins)
    report = {
        "schema_version": 2,
        "events_considered": scanned,
        "rows_used": len(rows),
        "rows_skipped": skipped,
        "calibration_on_yes_recommendations": {
            "bins": calibration_bins,
            "expected_calibration_error": _expected_calibration_error(calibration_bins),
            "mean_predicted": _mean([row["predicted"] for row in on_yes]),
            "observed_high_quality_rate": _mean([float(row["was_high_quality"]) for row in on_yes]),
            "brier_score": _calibration_slice(on_yes, bins)["brier_score"],
        },
        "evidence_channel_audit_on_yes": {
            "by_evidence_channel": _grouped_calibration(on_yes, "evidence_channel", bins),
            "by_evidence_band": _grouped_calibration(on_yes, "evidence_band", bins),
            "by_purchase_recommendation_alignment": _grouped_calibration(
                on_yes, "purchase_recommendation_alignment", bins
            ),
            "by_model_partition": _grouped_calibration(on_yes, "model_partition", bins),
            "by_config_partition": _grouped_calibration(on_yes, "config_partition", bins),
            "states_with_prior_purchase_after_no": sum(row["prior_purchases_after_no"] > 0 for row in on_yes),
            "states_with_prior_purchases": sum(row["prior_purchases"] > 0 for row in on_yes),
            "note": (
                "Market-statistics states estimate quality among purchased products; this equals "
                "quality conditional on a yes recommendation only for all_after_yes histories."
            ),
        },
        "predictive_platt_evaluation": {
            axis: _evaluate_platt_axis(on_yes, axis, bins)
            for axis in ("model", "config")
        },
        "decision_quality": {
            "agent_purchase_rate": len(agent_buys) / len(rows) if rows else None,
            "real_buyer_purchase_rate": len(real_buys) / len(rows) if rows else None,
            "agent_mean_realized_surplus_per_purchase": _mean([row["realized_surplus_if_bought"] for row in agent_buys]),
            "real_buyer_mean_realized_surplus_per_purchase": _mean(
                [row["realized_surplus_if_bought"] for row in real_buys]
            ),
            "agent_high_quality_hit_rate": _mean([float(row["was_high_quality"]) for row in agent_buys]),
            "real_buyer_high_quality_hit_rate": _mean([float(row["was_high_quality"]) for row in real_buys]),
        },
        "by_myopic": {
            str(flag): {
                "n": len([row for row in rows if row["is_myopic"] is flag]),
                "agent_purchase_rate": _mean([float(row["agent_would_buy"]) for row in rows if row["is_myopic"] is flag]),
                "agent_mean_realized_surplus_per_purchase": _mean(
                    [row["realized_surplus_if_bought"] for row in rows if row["is_myopic"] is flag and row["agent_would_buy"]]
                ),
            }
            for flag in (True, False)
        },
        "notes": [
            "Realized quality is used only for scoring; it never enters the state the agent sees.",
            "Recommendation-conditioned purchase counts are diagnostic-only and are never placed in agent-visible state.",
            "Surplus is per unit of product price: v-1 on high quality, c-1 on low.",
            "A negative agent_mean_realized_surplus_per_purchase means the rule buys "
            "value-destroying products on average -- the individually-irrational-purchase failure.",
        ],
    }
    out = ensure_dir(output_dir)
    write_json(out / "persuasion_calibration.json", report)
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Calibration and decision quality of the persuasion buy rule.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/persuasion_calibration")
    parser.add_argument("--agent", default="my_agents.jordan_strategic:MyAgent")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    report = persuasion_calibration(args.data_dir, args.output_dir, agent_spec=args.agent, limit=args.limit)
    print(json.dumps({k: v for k, v in report.items() if k != "notes"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
