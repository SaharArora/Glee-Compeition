"""Bounded necessity audit for a sequential opponent-behaviour model (Model A).

This module deliberately evaluates the *current* operational schema-v1 opponent
population.  It does not fit a replacement model.  Released rows are restricted
to the acting-model holdout and live rows come only from terminal-complete strict
run logs.  The output is therefore a misfit/architecture certificate, not a
promotion or an independent model-validation result.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import (
    bargaining_offer_self_share,
    bargaining_share_to_responder,
    persuasion_round_quality,
    persuasion_text_intent,
    transcript_item_decision,
    transcript_items,
)
from glee_eval.population.opponent_fit import OpponentPopulation
from glee_eval.population.splits import is_holdout_key
from glee_eval.storage.trajectories import iter_jsonl, write_json

FAMILIES = ("bargaining", "negotiation", "persuasion")
FIRST_ROLES = {"bargaining": "player_1", "negotiation": "seller", "persuasion": "seller"}
EPSILON = 1e-12


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clip_probability(value: float) -> float:
    return min(1.0 - EPSILON, max(EPSILON, float(value)))


def log_loss(probability: float, outcome: bool | int) -> float:
    p = _clip_probability(probability)
    y = float(bool(outcome))
    return -(y * math.log(p) + (1.0 - y) * math.log1p(-p))


def empirical_crps(samples: Iterable[float], observation: float) -> float:
    """Exact empirical CRPS in O(n log n), including the diagonal pairs."""

    ordered = sorted(float(value) for value in samples)
    if not ordered:
        raise ValueError("CRPS requires at least one predictive sample")
    n = len(ordered)
    first = math.fsum(abs(value - observation) for value in ordered) / n
    pair_half = math.fsum((2 * index - n + 1) * value for index, value in enumerate(ordered)) / (n * n)
    return first - pair_half


def _quantile(ordered: list[float], probability: float) -> float:
    if not ordered:
        raise ValueError("quantile requires samples")
    index = min(len(ordered) - 1, max(0, int(round(probability * (len(ordered) - 1)))))
    return ordered[index]


def _calibration_fit(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Logistic calibration ``y ~ intercept + slope * logit(p)``."""

    if len(rows) < 20 or len({int(row["outcome"]) for row in rows}) < 2:
        return {"intercept": None, "slope": None}
    intercept, slope = 0.0, 1.0
    for _ in range(80):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for row in rows:
            p = _clip_probability(float(row["predicted"]))
            x = math.log(p / (1.0 - p))
            eta = max(-35.0, min(35.0, intercept + slope * x))
            q = 1.0 / (1.0 + math.exp(-eta))
            residual = q - float(row["outcome"])
            weight = max(q * (1.0 - q), 1e-12)
            g0 += residual
            g1 += residual * x
            h00 += weight
            h01 += weight * x
            h11 += weight * x * x
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-15:
            return {"intercept": None, "slope": None}
        step0 = (h11 * g0 - h01 * g1) / determinant
        step1 = (-h01 * g0 + h00 * g1) / determinant
        intercept -= step0
        slope -= step1
        if max(abs(step0), abs(step1)) < 1e-9:
            break
    if not all(math.isfinite(value) and abs(value) <= 1e6 for value in (intercept, slope)):
        return {"intercept": None, "slope": None}
    return {"intercept": intercept, "slope": slope}


def _bootstrap_mean_ci(rows: list[dict[str, Any]], field: str, seed: int, replicates: int = 500) -> list[float] | None:
    games: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = row.get(field)
        if value is not None and math.isfinite(float(value)):
            games[str(row["game_id"])].append(float(value))
    if len(games) < 5:
        return None
    keys = sorted(games)
    rng = random.Random(seed)
    estimates = []
    for _ in range(replicates):
        selected = [rng.choice(keys) for _ in keys]
        values = [value for key in selected for value in games[key]]
        estimates.append(mean(values))
    estimates.sort()
    return [_quantile(estimates, 0.025), _quantile(estimates, 0.975)]


class OperationalV1Predictor:
    """Integrate predictions over the actual schema-v1 sampling contract."""

    def __init__(self, population_path: str | Path, *, draws: int = 4096, seed: int = 20260816):
        self.path = Path(population_path)
        population = OpponentPopulation.load(self.path)
        if population is None or int(population.payload.get("schema_version", 0)) != 1:
            raise ValueError("Model-A necessity audit requires the operational schema-v1 population")
        self.population = population
        self.draws = int(draws)
        self.seed = int(seed)
        self.specs: dict[str, list[dict[str, float]]] = {}
        self._offer_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        archetypes = sorted(population.bands)
        if not archetypes:
            raise ValueError("Operational population has no archetype bands")
        for family_index, family in enumerate(FAMILIES):
            rng = random.Random(seed + family_index * 100_003)
            rows = []
            for _ in range(self.draws):
                archetype = rng.choice(archetypes)
                params = population.parameters(family, archetype, rng)
                params["action_noise"] = rng.uniform(0.0, 0.03) if family != "persuasion" else 0.0
                rows.append(params)
            self.specs[family] = rows

    def discrete_probability(self, family: str, role: str, channel: str, context: dict[str, Any]) -> float | None:
        specs = self.specs[family]
        if family == "bargaining" and channel == "accept":
            share = context.get("offered_share")
            if share is None:
                return None
            thresholds = sorted(float(spec.get("accept_threshold", 0.4)) for spec in specs)
            return bisect.bisect_right(thresholds, float(share)) / len(thresholds)
        if family == "negotiation" and channel == "accept":
            offer = context.get("normalized_offer")
            own_value = context.get("own_value")
            if offer is None or own_value is None:
                return None
            gain = float(offer) - float(own_value) if role == "seller" else float(own_value) - float(offer)
            margins = sorted(float(spec.get("accept_margin", 0.02)) for spec in specs)
            return bisect.bisect_right(margins, gain) / len(margins)
        if family == "persuasion" and channel in {"recommend_high", "recommend_low"}:
            parameter = "honesty" if channel == "recommend_high" else "yes_on_low_rate"
            return mean(float(spec.get(parameter, 0.5)) for spec in specs)
        if family == "persuasion" and channel in {"buy_after_yes", "buy_after_no"}:
            if channel == "buy_after_no":
                return 0.022
            return mean(float(spec.get("trust_prior", 0.55)) for spec in specs)
        return None

    def offer_distribution(self, family: str, role: str, own_offer_index: int, context: dict[str, Any]) -> dict[str, Any]:
        seller_value = round(float(context.get("seller_value", 0.0)), 9)
        buyer_value = round(float(context.get("buyer_value", 0.0)), 9)
        key = (family, role, int(own_offer_index), seller_value, buyer_value)
        if key in self._offer_cache:
            return self._offer_cache[key]
        values = []
        for draw_index, spec in enumerate(self.specs[family]):
            # The real policy samples a deterministic per-round uniform perturbation.
            noise_width = float(spec.get("action_noise", 0.0))
            noise_rng = random.Random(self.seed + draw_index * 8191 + own_offer_index * 131)
            noise = noise_rng.uniform(-noise_width, noise_width)
            concession = float(spec.get("concession_rate", 0.04))
            if family == "bargaining":
                value = float(spec.get("target_share", 0.58)) - concession * own_offer_index + noise
                value = min(0.95, max(0.05, value))
            elif role == "seller":
                value = float(spec.get("aspiration_price", buyer_value or 1.1)) - concession * own_offer_index + noise
                value = min(1.5, max(seller_value, value))
            else:
                value = float(spec.get("aspiration_price", seller_value or 0.7)) + concession * own_offer_index + noise
                value = min(1.5, max(0.0, min(buyer_value, value)))
            values.append(value)
        ordered = sorted(values)
        payload = {
            "samples": ordered,
            "mean": mean(ordered),
            "median": median(ordered),
            "q10": _quantile(ordered, 0.10),
            "q90": _quantile(ordered, 0.90),
        }
        self._offer_cache[key] = payload
        return payload


def _actor_model(event: dict[str, Any]) -> str:
    family, role = str(event.get("game_family") or ""), str(event.get("role") or "")
    key = "player_1_model" if role == FIRST_ROLES.get(family) else "player_2_model"
    return str(event.get(key) or "")


def _config(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("configuration") or event.get("public_parameters") or {}
    return value if isinstance(value, dict) else {}


def _history_band(length: int) -> str:
    if length <= 1:
        return "0-1"
    if length <= 5:
        return "2-5"
    if length <= 15:
        return "6-15"
    return "16+"


def _slice_fields(event: dict[str, Any]) -> dict[str, Any]:
    cfg = _config(event)
    transcript = transcript_items(event)
    horizon = cfg.get("max_rounds", cfg.get("total_rounds", 99))
    horizon_known = bool(horizon not in {None, 99, "99"})
    return {
        "complete_information": cfg.get("complete_information", "na"),
        "horizon_known": horizon_known,
        "message_mode": cfg.get("seller_message_type", cfg.get("messages_allowed", "na")),
        "history_band": _history_band(len(transcript)),
    }


def _last_negotiation_price(event: dict[str, Any]) -> float | None:
    cfg = _config(event)
    order = as_float(cfg.get("product_price_order")) or 1_000_000.0
    for item in reversed(transcript_items(event)):
        if item.get("action_type") != "offer":
            continue
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        price = as_float(item.get("numeric_action")) or as_float(raw.get("product_price")) or as_float(raw.get("price"))
        return None if price is None else price / order
    return None


def _seller_stance_from_event(event: dict[str, Any]) -> str | None:
    raw = event.get("raw_record") if isinstance(event.get("raw_record"), dict) else {}
    decision = raw.get("decision")
    if decision in {"yes", "no"}:
        return str(decision)
    return persuasion_text_intent(str(event.get("free_text_message") or raw.get("message") or ""))


def _buyer_previous_stance(event: dict[str, Any]) -> str | None:
    current_round = int(as_float(event.get("round")) or 0)
    for item in reversed(transcript_items(event)):
        if item.get("role") != "seller" or int(as_float(item.get("round")) or 0) != current_round:
            continue
        decision = transcript_item_decision(item)
        if decision in {"yes", "no"}:
            return decision
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        return persuasion_text_intent(str(raw.get("message") or item.get("message") or ""))
    return None


def _released_rows(events_path: Path, predictor: OperationalV1Predictor) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    discrete: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    counters = Counter()
    terminal_rounds: dict[str, dict[str, Any]] = {}
    for event in iter_jsonl(events_path):
        counters["events_scanned"] += 1
        actor_model = _actor_model(event)
        if not actor_model or not is_holdout_key(actor_model, 0.25):
            continue
        counters["acting_model_holdout_events"] += 1
        family, role = str(event.get("game_family") or ""), str(event.get("role") or "")
        if family not in FAMILIES:
            continue
        allowed_roles = {
            "bargaining": {"player_1", "player_2"},
            "negotiation": {"seller", "buyer"},
            "persuasion": {"seller", "buyer"},
        }[family]
        if role not in allowed_roles:
            continue
        game_id = str(event.get("game_id") or "")
        round_number = int(as_float(event.get("round")) or 0)
        cfg = _config(event)
        slices = _slice_fields(event)
        terminal = event.get("terminal_outcome") if isinstance(event.get("terminal_outcome"), dict) else {}
        if game_id:
            record = terminal_rounds.setdefault(game_id, {"family": family, "role": role, "observed_round": 0, "configured_horizon": cfg.get("max_rounds", cfg.get("total_rounds"))})
            record["observed_round"] = max(int(record["observed_round"]), round_number, int(as_float(terminal.get("agreement_round")) or 0))

        action_type = str(event.get("action_type") or "")
        if action_type == "offer" and family in {"bargaining", "negotiation"}:
            actual = bargaining_offer_self_share(event) if family == "bargaining" else (
                (as_float(event.get("numeric_action")) or 0.0) / (as_float(cfg.get("product_price_order")) or 1_000_000.0)
            )
            own_index = max(0, (round_number - 1) // 2) if role != "buyer" else max(0, (round_number - 2) // 2)
            distribution = predictor.offer_distribution(family, role, own_index, cfg)
            row = {
                "source": "released_actor_model_holdout",
                "game_id": game_id,
                "family": family,
                "role": role,
                "channel": "offer",
                "actual": actual,
                "predicted": distribution["mean"],
                "error": distribution["mean"] - actual,
                "absolute_error": abs(distribution["mean"] - actual),
                "crps": empirical_crps(distribution["samples"], actual),
                "covered_80": int(distribution["q10"] <= actual <= distribution["q90"]),
                "own_offer_index": own_index,
                **slices,
            }
            offers.append(row)
            continue

        channel = None
        outcome: bool | None = None
        context: dict[str, Any] = {}
        if action_type == "decision" and family == "bargaining":
            money = as_float(cfg.get("money_to_divide")) or 100.0
            previous = transcript_items(event)[-1] if transcript_items(event) else None
            context["offered_share"] = bargaining_share_to_responder(previous or {}, role, money)
            channel, outcome = "accept", bool(event.get("accepted"))
        elif action_type == "decision" and family == "negotiation":
            context["normalized_offer"] = _last_negotiation_price(event)
            context["own_value"] = as_float(cfg.get("seller_value" if role == "seller" else "buyer_value"))
            channel, outcome = "accept", bool(event.get("accepted"))
        elif family == "persuasion" and role == "seller" and action_type in {"recommendation", "message"}:
            quality = persuasion_round_quality(event)
            stance = _seller_stance_from_event(event)
            if quality in {"high-quality", "high", "low-quality", "low"} and stance in {"yes", "no"}:
                channel = "recommend_high" if str(quality).startswith("high") else "recommend_low"
                outcome = stance == "yes"
            else:
                counters["persuasion_seller_unknown_stance_or_quality"] += 1
        elif family == "persuasion" and role == "buyer" and action_type == "buy_decision":
            stance = _buyer_previous_stance(event)
            if stance in {"yes", "no"}:
                channel = "buy_after_yes" if stance == "yes" else "buy_after_no"
                outcome = bool(event.get("bought"))
            else:
                counters["persuasion_buyer_unknown_stance"] += 1
        if channel is None or outcome is None:
            continue
        probability = predictor.discrete_probability(family, role, channel, context)
        if probability is None:
            counters[f"unsupported:{family}:{role}:{channel}"] += 1
            continue
        discrete.append({
            "source": "released_actor_model_holdout",
            "game_id": game_id,
            "family": family,
            "role": role,
            "channel": channel,
            "predicted": probability,
            "outcome": int(outcome),
            "brier": (probability - int(outcome)) ** 2,
            "log_loss": log_loss(probability, outcome),
            "calibration_error": probability - int(outcome),
            **slices,
        })
    term_rows = []
    for game_id, row in terminal_rounds.items():
        horizon = as_float(row.get("configured_horizon"))
        if horizon is not None:
            term_rows.append({"game_id": game_id, **row, "round_error_vs_configured_horizon": float(row["observed_round"]) - horizon})
    return discrete, offers, {"counters": dict(counters), "terminal_rows": term_rows}


def _terminal_live_records(live_dirs: list[Path]) -> list[dict[str, Any]]:
    by_game: dict[str, dict[str, Any]] = {}
    for run_dir in live_dirs:
        latest_observation: dict[str, dict[str, Any]] = {}
        for row in iter_jsonl(run_dir / "observations.jsonl"):
            if isinstance(row.get("game_state"), dict):
                latest_observation[str(row.get("game_id"))] = row
        path = run_dir / "move_results.jsonl"
        for row in iter_jsonl(path):
            move = row.get("move_result") if isinstance(row.get("move_result"), dict) else {}
            if move.get("status") == "completed" and isinstance(move.get("game_state"), dict):
                record = dict(move)
                record["run_name"] = run_dir.name
                by_game[str(move.get("game_id"))] = record
            elif row.get("game_over") is True and isinstance(row.get("result"), dict):
                game_id = str(row.get("game_id"))
                observation = latest_observation.get(game_id)
                if observation is None:
                    continue
                record = {
                    "game_family": observation.get("game_family"),
                    "game_id": game_id,
                    "game_state": observation["game_state"],
                    "result": row["result"],
                    "status": "completed",
                    "your_player": observation.get("your_player"),
                    "terminal_candidate_action": observation.get("action"),
                    "terminal_candidate_phase": observation.get("phase"),
                    "run_name": run_dir.name,
                }
                by_game[game_id] = record
    return [by_game[key] for key in sorted(by_game)]


def _live_rows(records: list[dict[str, Any]], predictor: OperationalV1Predictor) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    discrete: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    for record in records:
        family = str(record.get("game_family") or "")
        state = record["game_state"]
        game_id = str(record.get("game_id") or "")
        your_player = str(record.get("your_player") or "")
        opponent_player = "player_2" if your_player == "player_1" else "player_1"
        opponent_role = opponent_player
        if family in {"negotiation", "persuasion"}:
            opponent_role = "seller" if opponent_player == "player_1" else "buyer"
        history = list(state.get("history")) if isinstance(state.get("history"), list) else []
        last_offer = state.get("last_offer") if isinstance(state.get("last_offer"), dict) else None
        if last_offer is not None:
            last_round = int(as_float(last_offer.get("round")) or 0)
            if not any(int(as_float((item.get("offer") or {}).get("round")) or 0) == last_round for item in history if isinstance(item, dict)):
                if family == "bargaining":
                    history.append({"round": last_round, "proposer": last_offer.get("proposer"), "offer": last_offer, "decision": None})
                elif family == "negotiation":
                    history.append({"round": last_round, "decided_by": your_player, "offer": last_offer, "decision": None})
        terminal_action = record.get("terminal_candidate_action") if isinstance(record.get("terminal_candidate_action"), dict) else None
        if terminal_action is not None and record.get("terminal_candidate_phase") == "offer" and family in {"bargaining", "negotiation"}:
            terminal_round = int(as_float(state.get("round")) or len(history) + 1)
            accepted = str((record.get("result") or {}).get("outcome")) == "agreement"
            if family == "bargaining":
                offer = {
                    "round": terminal_round,
                    "proposer": your_player,
                    f"{your_player}_gain": terminal_action.get("alice_gain" if your_player == "player_1" else "bob_gain"),
                    f"{'player_2' if your_player == 'player_1' else 'player_1'}_gain": terminal_action.get("bob_gain" if your_player == "player_1" else "alice_gain"),
                }
                history.append({"round": terminal_round, "proposer": your_player, "offer": offer, "decision": "accept" if accepted else "reject"})
            else:
                price = terminal_action.get("product_price", terminal_action.get("price"))
                history.append({
                    "round": terminal_round,
                    "decided_by": opponent_player,
                    "offer": {"round": terminal_round, "from_player": your_player, "price": price},
                    "decision": "AcceptOffer" if accepted else "RejectOffer",
                })
        horizon = state.get("max_rounds", state.get("total_rounds", 99 if not state.get("horizon_known", False) else len(history)))
        base_slices = {
            "complete_information": state.get("complete_information", "na"),
            "horizon_known": bool(state.get("horizon_known", family == "persuasion")),
            "message_mode": state.get("seller_message_type", state.get("messages_allowed", "na")),
        }
        terminals.append({
            "source": "live_terminal_complete",
            "run_name": record["run_name"],
            "game_id": game_id,
            "family": family,
            "role": opponent_role,
            "observed_round": len(history),
            "configured_horizon": horizon,
            "round_error_vs_configured_horizon": len(history) - float(as_float(horizon) or len(history)),
        })
        if family == "bargaining":
            money = as_float(state.get("money_to_divide")) or 100.0
            for item_index, item in enumerate(history):
                proposer = str(item.get("proposer") or (item.get("offer") or {}).get("proposer") or "")
                offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
                round_number = int(as_float(item.get("round")) or item_index + 1)
                if proposer == opponent_player:
                    actual = (as_float(offer.get(f"{opponent_player}_gain")) or 0.0) / money
                    dist = predictor.offer_distribution(family, opponent_role, max(0, (round_number - 1) // 2), {})
                    offers.append(_live_offer_row(record, opponent_role, actual, dist, round_number, base_slices))
                responder = "player_2" if proposer == "player_1" else "player_1"
                if responder == opponent_player:
                    offered = (as_float(offer.get(f"{opponent_player}_gain")) or 0.0) / money
                    probability = predictor.discrete_probability(family, opponent_role, "accept", {"offered_share": offered})
                    discrete.append(_live_discrete_row(record, opponent_role, "accept", probability, str(item.get("decision")).lower() == "accept", item_index, base_slices))
        elif family == "negotiation":
            order = _infer_live_order(state)
            seller_raw = as_float(state.get("player_1_value"))
            buyer_raw = as_float(state.get("player_2_value"))
            seller_value = None if seller_raw is None else seller_raw / order
            buyer_value = None if buyer_raw is None else buyer_raw / order
            for item_index, item in enumerate(history):
                offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
                proposer = str(offer.get("from_player") or "")
                round_number = int(as_float(item.get("round")) or item_index + 1)
                if proposer == opponent_player:
                    if (opponent_role == "seller" and seller_value is None) or (opponent_role == "buyer" and buyer_value is None):
                        continue
                    actual = (as_float(offer.get("price")) or 0.0) / order
                    own_index = max(0, (round_number - 1) // 2) if opponent_role == "seller" else max(0, (round_number - 2) // 2)
                    dist = predictor.offer_distribution(family, opponent_role, own_index, {"seller_value": seller_value, "buyer_value": buyer_value})
                    offers.append(_live_offer_row(record, opponent_role, actual, dist, round_number, base_slices))
                if str(item.get("decided_by")) == opponent_player:
                    normalized = (as_float(offer.get("price")) or 0.0) / order
                    own_value = seller_value if opponent_role == "seller" else buyer_value
                    if own_value is None:
                        continue
                    probability = predictor.discrete_probability(family, opponent_role, "accept", {"normalized_offer": normalized, "own_value": own_value})
                    outcome = str(item.get("decision")) == "AcceptOffer"
                    discrete.append(_live_discrete_row(record, opponent_role, "accept", probability, outcome, item_index, base_slices))
        elif family == "persuasion":
            for item_index, item in enumerate(history):
                quality = str(item.get("quality") or "")
                message = str(item.get("seller_message") or "")
                stance = persuasion_text_intent(message)
                if opponent_role == "seller" and stance in {"yes", "no"} and quality in {"high", "low"}:
                    channel = "recommend_high" if quality == "high" else "recommend_low"
                    probability = predictor.discrete_probability(family, opponent_role, channel, {})
                    discrete.append(_live_discrete_row(record, opponent_role, channel, probability, stance == "yes", item_index, base_slices))
                if opponent_role == "buyer" and stance in {"yes", "no"}:
                    channel = "buy_after_yes" if stance == "yes" else "buy_after_no"
                    probability = predictor.discrete_probability(family, opponent_role, channel, {})
                    discrete.append(_live_discrete_row(record, opponent_role, channel, probability, bool(item.get("bought")), item_index, base_slices))
    return discrete, offers, terminals


def _infer_live_order(state: dict[str, Any]) -> float:
    values = [as_float(state.get("player_1_value")), as_float(state.get("player_2_value"))]
    prices = [as_float((item.get("offer") or {}).get("price")) for item in state.get("history", []) if isinstance(item, dict)]
    scale = max([value for value in values + prices if value is not None] or [1.0])
    for order in (1.0, 100.0, 10_000.0, 1_000_000.0):
        normalized = scale / order
        if normalized <= 2.5:
            return order
    return 1_000_000.0


def _live_discrete_row(record: dict[str, Any], role: str, channel: str, probability: float | None, outcome: bool, history_index: int, slices: dict[str, Any]) -> dict[str, Any]:
    if probability is None:
        raise ValueError(f"Unsupported live discrete channel {record.get('game_family')}/{role}/{channel}")
    return {
        "source": "live_terminal_complete",
        "run_name": record["run_name"],
        "game_id": record["game_id"],
        "family": record["game_family"],
        "role": role,
        "channel": channel,
        "predicted": probability,
        "outcome": int(outcome),
        "brier": (probability - int(outcome)) ** 2,
        "log_loss": log_loss(probability, outcome),
        "calibration_error": probability - int(outcome),
        "history_band": _history_band(history_index),
        **slices,
    }


def _live_offer_row(record: dict[str, Any], role: str, actual: float, dist: dict[str, Any], round_number: int, slices: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "live_terminal_complete",
        "run_name": record["run_name"],
        "game_id": record["game_id"],
        "family": record["game_family"],
        "role": role,
        "channel": "offer",
        "actual": actual,
        "predicted": dist["mean"],
        "error": dist["mean"] - actual,
        "absolute_error": abs(dist["mean"] - actual),
        "crps": empirical_crps(dist["samples"], actual),
        "covered_80": int(dist["q10"] <= actual <= dist["q90"]),
        "history_band": _history_band(round_number - 1),
        **slices,
    }


def _summarize_discrete(rows: list[dict[str, Any]], source: str, min_n: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["source"] == source:
            groups[(row["family"], row["role"], row["channel"])].append(row)
    output = []
    for (family, role, channel), group in sorted(groups.items()):
        predicted = mean(float(row["predicted"]) for row in group)
        observed = mean(float(row["outcome"]) for row in group)
        output.append({
            "source": source,
            "family": family,
            "role": role,
            "channel": channel,
            "n": len(group),
            "interpretable": len(group) >= min_n,
            "mean_predicted": predicted,
            "observed_rate": observed,
            "calibration_in_the_large": predicted - observed,
            "calibration_error_ci95_game_bootstrap": _bootstrap_mean_ci(group, "calibration_error", 20260816 + len(output)),
            "brier": mean(float(row["brier"]) for row in group),
            "log_loss": mean(float(row["log_loss"]) for row in group),
            "calibration_model": _calibration_fit(group),
            "games": len({row["game_id"] for row in group}),
        })
    return output


def _summarize_offers(rows: list[dict[str, Any]], source: str, min_n: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["source"] == source:
            groups[(row["family"], row["role"])].append(row)
    output = []
    for (family, role), group in sorted(groups.items()):
        output.append({
            "source": source,
            "family": family,
            "role": role,
            "channel": "offer",
            "n": len(group),
            "interpretable": len(group) >= min_n,
            "mean_actual": mean(float(row["actual"]) for row in group),
            "mean_predicted": mean(float(row["predicted"]) for row in group),
            "bias": mean(float(row["error"]) for row in group),
            "mae": mean(float(row["absolute_error"]) for row in group),
            "mae_ci95_game_bootstrap": _bootstrap_mean_ci(group, "absolute_error", 20260816 + 100 + len(output)),
            "crps": mean(float(row["crps"]) for row in group),
            "central_80_coverage": mean(float(row["covered_80"]) for row in group),
            "games": len({row["game_id"] for row in group}),
        })
    return output


def _conditional_slices(discrete: list[dict[str, Any]], offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for metric_type, rows, value_field in (("discrete", discrete, "calibration_error"), ("offer", offers, "absolute_error")):
        for slice_name in ("complete_information", "horizon_known", "message_mode", "history_band"):
            groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                groups[(row["source"], row["family"], row["role"], row["channel"], str(row.get(slice_name, "unknown")))].append(row)
            for key, group in sorted(groups.items(), key=lambda item: tuple(str(value) for value in item[0])):
                if len(group) < 30:
                    continue
                output.append({
                    "metric_type": metric_type,
                    "source": key[0],
                    "family": key[1],
                    "role": key[2],
                    "channel": key[3],
                    "slice": slice_name,
                    "value": key[4],
                    "n": len(group),
                    "mean_residual": mean(float(row[value_field]) for row in group),
                })
    return output


def _advance_decision(discrete_summary: list[dict[str, Any]], offer_summary: list[dict[str, Any]]) -> dict[str, Any]:
    released_defects: list[tuple[dict[str, Any], str]] = []
    live_defects: list[tuple[dict[str, Any], str]] = []
    for row in discrete_summary:
        if row["interpretable"] and abs(float(row["calibration_in_the_large"])) >= 0.05:
            direction = "calibration_high" if float(row["calibration_in_the_large"]) > 0 else "calibration_low"
            (live_defects if row["source"].startswith("live") else released_defects).append((row, direction))
    for row in offer_summary:
        target = live_defects if row["source"].startswith("live") else released_defects
        if row["interpretable"] and float(row["mae"]) >= 0.08:
            target.append((row, "mae_high"))
        if row["interpretable"] and float(row["central_80_coverage"]) < 0.70:
            target.append((row, "coverage_low"))
    mechanisms = {(row["family"], row["role"], row["channel"], direction) for row, direction in released_defects}
    live_mechanisms = {(row["family"], row["role"], row["channel"], direction) for row, direction in live_defects}
    replicated_signatures = sorted(mechanisms & live_mechanisms)
    replicated = sorted({signature[:3] for signature in replicated_signatures})
    # A live opponent action is, by construction, a branch reached by Jordan.
    decision_relevance = bool(replicated)
    warranted = bool(released_defects and replicated and decision_relevance)
    return {
        "status": "model_a_campaign_warranted" if warranted else "deferred_no_demonstrated_incremental_need",
        "released_defect_signatures": len(released_defects),
        "live_defect_signatures": len(live_defects),
        "replicated_candidate_reached_mechanisms": [list(key) for key in replicated],
        "replicated_defect_signatures": [list(key) for key in replicated_signatures],
        "three_part_gate": {
            "reproducible_predictive_defect": bool(released_defects and replicated),
            "plausible_sequential_model": bool(replicated),
            "named_downstream_decision_can_change": decision_relevance,
        },
    }


def run_audit(
    events_path: str | Path,
    population_path: str | Path,
    live_dirs: list[str | Path],
    output_path: str | Path,
    *,
    draws: int = 4096,
    events_sha256: str | None = None,
) -> dict[str, Any]:
    events = Path(events_path)
    population = Path(population_path)
    live = [Path(path) for path in live_dirs]
    predictor = OperationalV1Predictor(population, draws=draws)
    released_discrete, released_offers, released_meta = _released_rows(events, predictor)
    live_records = _terminal_live_records(live)
    live_discrete, live_offers, live_terminals = _live_rows(live_records, predictor)
    discrete = released_discrete + live_discrete
    offers = released_offers + live_offers
    discrete_summary = _summarize_discrete(discrete, "released_actor_model_holdout", 200) + _summarize_discrete(discrete, "live_terminal_complete", 30)
    offer_summary = _summarize_offers(offers, "released_actor_model_holdout", 100) + _summarize_offers(offers, "live_terminal_complete", 20)
    result = {
        "schema": "glee.wave5b.model_a_necessity.v1",
        "evidence_class": "candidate_self_audited_architecture_evidence",
        "not_independent_validation": True,
        "operational_model": {
            "path": str(population.resolve()),
            "sha256": _sha256(population),
            "schema_version": 1,
            "draws": draws,
            "seed": 20260816,
            "model_b_used": False,
        },
        "released_source": {
            "path": str(events.resolve()),
            "bytes": events.stat().st_size,
            "sha256": events_sha256,
            "sha256_provenance": "previous fully-consumed source manifest; not recomputed by this bounded audit" if events_sha256 else None,
            "selection": "acting model in deterministic 25% model holdout",
            "limitation": "operational v1 was fitted on all released data; misfit is descriptive/conservative, not independent validation",
        },
        "live_source": {
            "run_dirs": [str(path.resolve()) for path in live],
            "file_sha256s": {
                path.name: {
                    name: _sha256(path / name)
                    for name in ("launch_manifest.json", "observations.jsonl", "move_results.jsonl", "run_summary.json")
                }
                for path in live
            },
            "terminal_complete_games": len(live_records),
            "agent_class": "my_agents.jordan_strategic:MyAgent",
            "exact_agent_commit_captured": False,
            "limitation": "launch manifests do not record the git commit and official per-game rating outputs are absent",
        },
        "released_extraction": released_meta["counters"],
        "discrete_cells": discrete_summary,
        "offer_cells": offer_summary,
        "conditional_residuals_n_ge_30": _conditional_slices(discrete, offers),
        "termination": {
            "operational_coverage": {
                "bargaining": "no learned termination hazard",
                "negotiation": "John exit only at configured final round",
                "persuasion": "fixed configured total rounds",
            },
            "released": _summarize_termination(released_meta["terminal_rows"]),
            "live": _summarize_termination(live_terminals),
        },
        "advance_decision": _advance_decision(discrete_summary, offer_summary),
        "status_ceiling": "candidate_pending_independent_structural_validation",
        "prohibitions": ["no simulator replacement", "no promotion gate", "no factorial baseline change", "no live policy change"],
    }
    write_json(output_path, result)
    return result


def _summarize_termination(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["family"]), str(row["role"]))].append(row)
    return [{
        "family": family,
        "role": role,
        "games": len(group),
        "mean_observed_round": mean(float(row["observed_round"]) for row in group),
        "mean_configured_horizon": mean(float(row["configured_horizon"]) for row in group if as_float(row.get("configured_horizon")) is not None),
        "mean_round_error_vs_configured_horizon": mean(float(row["round_error_vs_configured_horizon"]) for row in group),
    } for (family, role), group in sorted(groups.items())]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", required=True)
    parser.add_argument("--population", required=True)
    parser.add_argument("--live-dir", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--draws", type=int, default=4096)
    parser.add_argument("--events-sha256")
    args = parser.parse_args(argv)
    result = run_audit(
        args.events,
        args.population,
        args.live_dir,
        args.output,
        draws=args.draws,
        events_sha256=args.events_sha256,
    )
    print(json.dumps({"output": args.output, "advance_decision": result["advance_decision"]}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
