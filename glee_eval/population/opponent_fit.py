"""Fit synthetic-opponent parameters to the real GLEE population.

Two problems this solves at once.

`sample_opponent_spec` drew every behavioral parameter from a hand-picked
`rng.uniform(...)` range that was never checked against data, so every synthetic
tournament measured the agent against invented opponents. And because it always
supplied those parameters, the archetype-specific defaults in `policies.py`
(`_target_share`, `_honesty`, `_trust`) were dead code -- the 16 archetype labels
had no effect on negotiation or persuasion behavior at all, and only a marginal
one on bargaining.

Here an archetype instead names a *band of the observed distribution*: an
`aggressive_extractor` is drawn from the top quantiles of what real players
actually did, a `conceding` opponent from the bottom. That keeps archetypes
meaningful without inventing them, and without building the learned latent-type
model (Model B) that remains deliberately deferred.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import (
    as_dict,
    bargaining_offer_self_share,
    bargaining_share_to_responder,
    last_transcript_action,
    negotiation_normalized_price,
    persuasion_recommendation,
    persuasion_round_quality,
    same_round_transcript_item,
)
from glee_eval.population.splits import DEFAULT_HOLDOUT_FRACTION, add_split_arguments, is_holdout_key, keeps, split_provenance
from glee_eval.population.config_keys import canonical_config, canonical_config_key
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json


# Where each archetype sits in the observed behavioral distribution, as a
# quantile window. Wide windows mean a less predictable opponent; `random` spans
# almost the whole range on purpose.
ARCHETYPE_BANDS: dict[str, tuple[float, float]] = {
    "aggressive_extractor": (0.80, 0.98),
    "boulware": (0.75, 0.95),
    "commitment_testing": (0.70, 0.92),
    "deceptive": (0.70, 0.95),
    "level_2": (0.60, 0.85),
    "rational": (0.55, 0.80),
    "adaptive": (0.50, 0.80),
    "historical_imitator": (0.40, 0.60),
    "commitment_respecting": (0.35, 0.60),
    "reciprocal": (0.35, 0.60),
    "level_1": (0.30, 0.55),
    "fairness_sensitive": (0.25, 0.50),
    "myopic": (0.20, 0.50),
    "level_0": (0.10, 0.35),
    "conceding": (0.05, 0.25),
    "random": (0.02, 0.98),
}
DEFAULT_BAND = (0.25, 0.75)

# Parameters where a *higher* observed value means a *softer* opponent, so the
# archetype band has to be read from the other end.
INVERTED_PARAMETERS = {"concession_rate", "accept_margin", "trust_prior"}

_MIN_BUCKET = 25
_QUANTILE_POINTS = tuple(round(0.01 * i, 2) for i in range(1, 100))


def config_signature(family: str, config: dict[str, Any], *, coarse: bool = False) -> str:
    """Deterministic configuration key used by fit and production draws."""

    if not coarse:
        return canonical_config_key(family, config)
    config = canonical_config(family, config)
    def number(name: str, default: float = 0.0) -> float:
        value = config.get(name)
        return default if value is None else float(value)
    if family == "bargaining":
        selected = {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "messages_allowed": config.get("messages_allowed"),
            "delta_1": round(number("delta_1", 1.0) / 0.05) * 0.05,
            "delta_2": round(number("delta_2", 1.0) / 0.05) * 0.05,
        }
    elif family == "negotiation":
        selected = {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "messages_allowed": config.get("messages_allowed"),
            "seller_value": round(number("seller_value"), 1),
            "buyer_value": round(number("buyer_value"), 1),
        }
    else:
        selected = {
            "p": round(number("p"), 1),
            "v": round(number("v"), 1),
            "c": round(number("c"), 1),
            "is_seller_know_cv": config.get("is_seller_know_cv"),
            "is_buyer_know_p": config.get("is_buyer_know_p"),
            "seller_message_type": config.get("seller_message_type"),
            "is_myopic": config.get("is_myopic"),
        }
    return json.dumps(selected, sort_keys=True, separators=(",", ":"), default=str)


def _actor_model(event: dict[str, Any], role: str) -> str:
    """Stable actor identity available in the released corpus."""

    first_roles = {"player_1", "seller"}
    field = "player_1_model" if role in first_roles else "player_2_model"
    return str(event.get(field) or "unknown")


def extract_joint_bundle_observations(events: Any) -> list[dict[str, Any]]:
    """Extract raw identifiable Model-B endpoints by model/config/role.

    This helper deliberately performs no normalization, latent scoring, shrinkage,
    or missing-value imputation, so holdout diagnostics can evaluate the exact same
    endpoints without learning from the holdout.
    """

    stats: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "offers": [],
            "first_offers": [],
            "offer_sequences": defaultdict(list),
            "concessions": [],
            "accept_margins": [],
            "decision_curve": defaultdict(lambda: [0, 0]),
            "truth": [0, 0],
            "yes_low": [0, 0],
            "buy_yes": [0, 0],
            "buy_no": [0, 0],
            "games": set(),
            "parameter_games": defaultdict(set),
            "configuration": None,
        }
    )
    last_offer: dict[tuple[str, str], float] = {}
    for event in events:
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "")
        if family not in {"bargaining", "negotiation", "persuasion"} or not role:
            continue
        config_id = str(event.get("config_id") or "unknown")
        model = _actor_model(event, role)
        key = (family, model, config_id, role)
        bucket = stats[key]
        bucket["games"].add(str(event.get("game_id") or "unknown"))
        config = as_dict(event.get("configuration") or event.get("public_parameters"))
        if bucket["configuration"] is None:
            bucket["configuration"] = config
        raw = as_dict(event.get("raw_record"))
        game_role = (str(event.get("game_id")), role)
        game_id = str(event.get("game_id") or "unknown")

        if family == "bargaining":
            share = bargaining_offer_self_share(event)
            if share is not None:
                bucket["offers"].append(share)
                bucket["offer_sequences"][game_id].append(share)
                bucket["parameter_games"]["target_share"].add(game_id)
                previous = last_offer.get(game_role)
                if previous is None:
                    bucket["first_offers"].append(share)
                else:
                    bucket["concessions"].append(previous - share)
                    bucket["parameter_games"]["concession_rate"].add(game_id)
                last_offer[game_role] = share
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                money = as_float(config.get("money_to_divide")) or 100.0
                offered = bargaining_share_to_responder(offer or {}, role, money)
                if offered is not None:
                    binned = round(min(1.0, max(0.0, offered)) * 20) / 20
                    accepted = int(str(raw.get("decision") or "").lower() == "accept")
                    bucket["decision_curve"][binned][0] += accepted
                    bucket["decision_curve"][binned][1] += 1
                    bucket["parameter_games"]["accept_threshold"].add(game_id)
        elif family == "negotiation":
            price = negotiation_normalized_price(event)
            if price is not None:
                bucket["offers"].append(price)
                bucket["offer_sequences"][game_id].append(price)
                bucket["parameter_games"]["aspiration_price"].add(game_id)
                previous = last_offer.get(game_role)
                if previous is None:
                    bucket["first_offers"].append(price)
                else:
                    delta = previous - price if role == "seller" else price - previous
                    if -0.5 <= delta <= 0.5:
                        bucket["concessions"].append(delta)
                        bucket["parameter_games"]["concession_rate"].add(game_id)
                last_offer[game_role] = price
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer") or {}
                order = as_float(config.get("product_price_order")) or 1_000_000.0
                accepted_price = as_float(offer.get("numeric_action"))
                if accepted_price is None:
                    accepted_price = as_float(as_dict(offer.get("raw")).get("product_price"))
                own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
                if accepted_price is not None and own is not None and order > 0:
                    normalized = accepted_price / order
                    margin = normalized - own if role == "seller" else own - normalized
                    binned = round(margin * 20) / 20
                    accepted = int(str(raw.get("decision") or "") == "AcceptOffer")
                    bucket["decision_curve"][binned][0] += accepted
                    bucket["decision_curve"][binned][1] += 1
                    bucket["parameter_games"]["accept_margin"].add(game_id)
        else:
            if role == "seller" and event.get("action_type") in {"recommendation", "message"}:
                quality = persuasion_round_quality(event)
                recommendation = persuasion_recommendation(event) or raw.get("decision")
                if quality and recommendation in {"yes", "no"}:
                    if quality == "high-quality":
                        bucket["truth"][0] += int(recommendation == "yes")
                        bucket["truth"][1] += 1
                        bucket["parameter_games"]["honesty"].add(game_id)
                    if quality == "low-quality":
                        bucket["yes_low"][0] += int(recommendation == "yes")
                        bucket["yes_low"][1] += 1
                        bucket["parameter_games"]["yes_on_low_rate"].add(game_id)
            elif role == "buyer" and event.get("action_type") == "buy_decision":
                recommendation = persuasion_recommendation(same_round_transcript_item(event, role="seller"))
                bought = raw.get("decision") or event.get("buy_no_buy")
                if recommendation in {"yes", "no"} and bought in {"yes", "no"}:
                    target = bucket["buy_yes" if recommendation == "yes" else "buy_no"]
                    target[0] += int(bought == "yes")
                    target[1] += 1
                    parameter = "trust_prior" if recommendation == "yes" else "buy_after_no_rate"
                    bucket["parameter_games"][parameter].add(game_id)

    rows: list[dict[str, Any]] = []
    for (family, model, config_id, role), bucket in sorted(stats.items()):
        params: dict[str, float] = {}
        counts: dict[str, int] = {}
        if family == "bargaining":
            if bucket["first_offers"]:
                params["target_share"] = mean(bucket["first_offers"])
                counts["target_share"] = len(bucket["first_offers"])
            if bucket["concessions"]:
                params["concession_rate"] = mean(bucket["concessions"])
                counts["concession_rate"] = len(bucket["concessions"])
            threshold = _threshold_crossing(bucket["decision_curve"])
            if threshold is not None:
                params["accept_threshold"] = threshold
                counts["accept_threshold"] = sum(v[1] for v in bucket["decision_curve"].values())
        elif family == "negotiation":
            if bucket["first_offers"]:
                params["aspiration_price"] = mean(bucket["first_offers"])
                counts["aspiration_price"] = len(bucket["first_offers"])
            if bucket["concessions"]:
                params["concession_rate"] = mean(bucket["concessions"])
                counts["concession_rate"] = len(bucket["concessions"])
            threshold = _threshold_crossing(bucket["decision_curve"])
            if threshold is not None:
                params["accept_margin"] = threshold
                counts["accept_margin"] = sum(v[1] for v in bucket["decision_curve"].values())
        if family in {"bargaining", "negotiation"} and bucket["first_offers"] and bucket["concessions"]:
            intercept = mean(bucket["first_offers"])
            slope = mean(bucket["concessions"])
            residuals = []
            for sequence in bucket["offer_sequences"].values():
                for index, observed in enumerate(sequence):
                    predicted = intercept - slope * index if family == "bargaining" or role == "seller" else intercept + slope * index
                    residuals.append(observed - predicted)
            if len(residuals) >= 2:
                params["action_noise"] = sqrt(3.0) * pstdev(residuals)
                counts["action_noise"] = len(residuals)
                bucket["parameter_games"]["action_noise"].update(bucket["offer_sequences"].keys())
        if family == "persuasion":
            sources = (("honesty", "truth"), ("yes_on_low_rate", "yes_low")) if role == "seller" else (
                ("trust_prior", "buy_yes"), ("buy_after_no_rate", "buy_no")
            )
            for name, source in sources:
                hits, total = bucket[source]
                if total:
                    params[name] = hits / total
                    counts[name] = total
        rows.append({
            "bundle_id": f"{family}|{model}|{config_id}|{role}",
            "family": family,
            "player_model": model,
            "actor_model_is_holdout": is_holdout_key(model),
            "config_id": config_id,
            "role": role,
            "parameters": params,
            "parameter_observations": counts,
            "parameter_game_counts": {
                parameter: len(bucket["parameter_games"].get(parameter, set()))
                for parameter in params
            },
            "game_count": len(bucket["games"]),
            "game_ids": sorted(bucket["games"]),
            "configuration": dict(bucket["configuration"] or {}),
            "config_signature": config_signature(family, bucket["configuration"] or {}),
            "coarse_config_signature": config_signature(family, bucket["configuration"] or {}, coarse=True),
        })
    return rows


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if len(values) < _MIN_BUCKET:
        return None
    ordered = sorted(values)
    table = {}
    for point in _QUANTILE_POINTS:
        index = min(len(ordered) - 1, max(0, int(round(point * (len(ordered) - 1)))))
        table[f"{point:.2f}"] = ordered[index]
    return table


def _threshold_crossing(curve: dict[float, list[int]], *, ascending: bool = True) -> float | None:
    """Share at which observed acceptance probability crosses one half."""

    usable = sorted((share, hits / total) for share, (hits, total) in curve.items() if total >= 10)
    if len(usable) < 3:
        return None
    if not ascending:
        usable = list(reversed(usable))
    previous = None
    for share, rate in usable:
        if rate >= 0.5:
            if previous is None:
                return share
            prev_share, prev_rate = previous
            if rate == prev_rate:
                return share
            # Linear interpolation between the bracketing bins.
            weight = (0.5 - prev_rate) / (rate - prev_rate)
            return prev_share + weight * (share - prev_share)
        previous = (share, rate)
    return None


def fit_opponent_population(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "models/opponent_population",
    *,
    split_mode: str = "none",
    split: str | None = None,
    holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION,
) -> dict[str, Any]:
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    barg_shares: dict[tuple[str, str], list[float]] = defaultdict(list)
    barg_concessions: list[float] = []
    barg_curve: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    neg_prices: dict[tuple[str, str], list[float]] = defaultdict(list)
    neg_concessions: list[float] = []
    neg_curve: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    pers_truth: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_yes_on_low: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_trust: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_buy_after_no: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    last_share: dict[tuple[str, str], float] = {}
    last_price: dict[tuple[str, str], float] = {}
    scanned = 0

    skipped_by_split = 0
    for event in iter_jsonl(events_path):
        if not keeps(event, mode=split_mode, split=split, holdout_fraction=holdout_fraction):
            skipped_by_split += 1
            continue
        scanned += 1
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "")
        config = as_dict(event.get("configuration") or event.get("public_parameters"))
        config_id = str(event.get("config_id") or "unknown")
        raw = as_dict(event.get("raw_record"))
        game_role = (str(event.get("game_id")), role)

        if family == "bargaining":
            share = bargaining_offer_self_share(event)
            if share is not None:
                previous = last_share.get(game_role)
                if previous is None:
                    barg_shares[(config_id, role)].append(share)
                else:
                    barg_concessions.append(previous - share)
                last_share[game_role] = share
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                money = as_float(config.get("money_to_divide")) or 100.0
                offered = bargaining_share_to_responder(offer or {}, role, money)
                if offered is not None:
                    binned = round(min(1.0, max(0.0, offered)) * 20) / 20
                    accepted = 1 if str(raw.get("decision") or "").lower() == "accept" else 0
                    bucket = barg_curve[f"{config_id}|{role}"][binned]
                    bucket[0] += accepted
                    bucket[1] += 1

        elif family == "negotiation":
            price = negotiation_normalized_price(event)
            if price is not None:
                previous = last_price.get(game_role)
                if previous is None:
                    neg_prices[(config_id, role)].append(price)
                else:
                    neg_concessions.append(previous - price if role == "seller" else price - previous)
                last_price[game_role] = price
            elif event.get("action_type") == "decision":
                offer = last_transcript_action(event, "offer")
                order = as_float(config.get("product_price_order")) or 1_000_000.0
                accepted_price = as_float((offer or {}).get("numeric_action"))
                if accepted_price is None:
                    accepted_price = as_float(as_dict((offer or {}).get("raw")).get("product_price"))
                own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
                if accepted_price is not None and own is not None and order > 0:
                    normalized = accepted_price / order
                    margin = normalized - own if role == "seller" else own - normalized
                    binned = round(margin * 20) / 20
                    curve_bucket = neg_curve[f"{config_id}|{role}"][binned]
                    curve_bucket[0] += int(str(raw.get("decision") or "") == "AcceptOffer")
                    curve_bucket[1] += 1

        elif family == "persuasion":
            if role == "seller" and event.get("action_type") in {"recommendation", "message"}:
                quality = persuasion_round_quality(event)
                recommendation = persuasion_recommendation(event) or (raw.get("decision") if raw else None)
                if quality and recommendation in {"yes", "no"}:
                    if quality == "high-quality":
                        bucket = pers_truth[config_id]
                        bucket[0] += int(recommendation == "yes")
                        bucket[1] += 1
                    if quality == "low-quality":
                        low = pers_yes_on_low[config_id]
                        low[0] += int(recommendation == "yes")
                        low[1] += 1
            elif role == "buyer" and event.get("action_type") == "buy_decision":
                seller_item = same_round_transcript_item(event, role="seller")
                recommendation = persuasion_recommendation(seller_item)
                bought = raw.get("decision") or event.get("buy_no_buy")
                if recommendation in {"yes", "no"} and bought in {"yes", "no"}:
                    bucket = pers_trust[config_id] if recommendation == "yes" else pers_buy_after_no[config_id]
                    bucket[0] += int(bought == "yes")
                    bucket[1] += 1

    def _rates(counts: dict[str, list[int]]) -> list[float]:
        return [hits / total for hits, total in counts.values() if total >= 10]

    barg_thresholds = [value for value in (_threshold_crossing(curve) for curve in barg_curve.values()) if value is not None]
    neg_thresholds = [value for value in (_threshold_crossing(curve) for curve in neg_curve.values()) if value is not None]

    families: dict[str, Any] = {
        "bargaining": {
            "target_share": _quantiles([mean(values) for values in barg_shares.values() if values]),
            "concession_rate": _quantiles([value for value in barg_concessions if -0.5 <= value <= 0.5]),
            "accept_threshold": _quantiles(barg_thresholds),
        },
        "negotiation": {
            "aspiration_price": _quantiles([mean(values) for values in neg_prices.values() if values]),
            "concession_rate": _quantiles([value for value in neg_concessions if -0.5 <= value <= 0.5]),
            "accept_margin": _quantiles(neg_thresholds),
        },
        "persuasion": {
            "honesty": _quantiles(_rates(pers_truth)),
            "yes_on_low_rate": _quantiles(_rates(pers_yes_on_low)),
            "trust_prior": _quantiles(_rates(pers_trust)),
            "buy_after_no_rate": _quantiles(_rates(pers_buy_after_no)),
        },
    }

    observations = {
        "bargaining_offer_segments": len(barg_shares),
        "bargaining_concession_observations": len(barg_concessions),
        "bargaining_threshold_segments": len(barg_thresholds),
        "negotiation_offer_segments": len(neg_prices),
        "negotiation_concession_observations": len(neg_concessions),
        "negotiation_threshold_segments": len(neg_thresholds),
        "persuasion_seller_segments": len(pers_truth),
        "persuasion_buyer_segments": len(pers_trust),
    }

    filtered_events = (
        event
        for event in iter_jsonl(events_path)
        if keeps(event, mode=split_mode, split=split, holdout_fraction=holdout_fraction)
    )
    raw_bundles = extract_joint_bundle_observations(filtered_events)
    parameter_names = {
        ("bargaining", "*"): {"target_share", "concession_rate", "accept_threshold", "action_noise"},
        ("negotiation", "*"): {"aspiration_price", "concession_rate", "accept_margin", "action_noise"},
        ("persuasion", "seller"): {"honesty", "yes_on_low_rate"},
        ("persuasion", "buyer"): {"trust_prior", "buy_after_no_rate"},
    }
    for row in raw_bundles:
        supported = {
            name: value
            for name, value in row["parameters"].items()
            if row["parameter_game_counts"].get(name, 0) >= 2
        }
        row["parameters"] = supported
        row["parameter_observations"] = {name: row["parameter_observations"][name] for name in supported}
        row["parameter_game_counts"] = {name: row["parameter_game_counts"][name] for name in supported}
        expected = parameter_names.get((row["family"], row["role"]), parameter_names.get((row["family"], "*"), set()))
        row["missing_parameters"] = sorted(expected - set(supported))
    retained = [row for row in raw_bundles if len(row["parameters"]) >= 2]
    for family in ("bargaining", "negotiation"):
        noise_values = [row["parameters"]["action_noise"] for row in retained if row["family"] == family and "action_noise" in row["parameters"]]
        families[family]["action_noise"] = _quantiles(noise_values)
    # Score whole bundles using only empirical ranks learned inside this fit
    # partition. Ranking within family+role prevents incomparable role semantics
    # from manufacturing a latent ordering.
    by_cell_parameter: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in retained:
        for parameter, value in row["parameters"].items():
            by_cell_parameter[(row["family"], row["role"], parameter)].append(float(value))
    joint_bundles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in retained:
        ranks = []
        for parameter, value in sorted(row["parameters"].items()):
            if parameter == "action_noise":
                continue
            reference = sorted(by_cell_parameter[(row["family"], row["role"], parameter)])
            rank = sum(candidate <= float(value) for candidate in reference) / len(reference)
            if parameter in {"concession_rate", "trust_prior"} or (
                parameter == "aspiration_price" and row["role"] == "buyer"
            ):
                rank = 1.0 - rank
            ranks.append(rank)
        score = mean(ranks)
        copied = dict(row)
        copied["latent_score"] = score
        copied["weight"] = max(1, int(row["game_count"]))
        joint_bundles[row["family"]].append(copied)
    for family, bundles in joint_bundles.items():
        by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for bundle in bundles:
            by_role[str(bundle["role"])].append(bundle)
        for role_bundles in by_role.values():
            ordered_role = sorted(role_bundles, key=lambda row: (row["latent_score"], row["bundle_id"]))
            denominator = max(1, len(ordered_role) - 1)
            for index, row in enumerate(ordered_role):
                row["latent_percentile"] = index / denominator
        joint_bundles[family] = sorted(bundles, key=lambda row: (row["role"], row["latent_percentile"], row["bundle_id"]))

    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dir": str(data_dir),
        "events_scanned": scanned,
        "events_skipped_by_split": skipped_by_split,
        "provenance": split_provenance(split_mode, split, holdout_fraction),
        "min_segment_observations": _MIN_BUCKET,
        "archetype_bands": {name: list(band) for name, band in ARCHETYPE_BANDS.items()},
        "inverted_parameters": sorted(INVERTED_PARAMETERS),
        "observations": observations,
        "families": families,
        "joint_model": {
            "version": 1,
            "method": "configuration_conditioned_empirical_model_config_role_bundle_rank",
            "grouping": ["player_model", "config_id", "role"],
            "minimum_identified_parameters": 2,
            "minimum_distinct_games": 2,
            "latent_score": "equal mean of within-family-role empirical parameter percentiles",
            "inverted_parameters": sorted(INVERTED_PARAMETERS),
            "tie_break": "bundle_id lexical order",
            "draw_ladder": ["exact_config_signature", "coarse_config_signature", "role"],
            "sampling_prior": "distinct-game weighted empirical bundles; archetype label derived after draw",
            "missing_parameter_handling": "explicitly absent; opponent policy uses its existing default",
            "fit_partition_only": True,
        },
        "joint_bundles": dict(joint_bundles),
        "joint_bundle_observations": {
            "raw_segments": len(raw_bundles),
            "retained_segments": len(retained),
            "dropped_below_identification_or_game_support": len(raw_bundles) - len(retained),
            "by_family": {family: len(joint_bundles.get(family, [])) for family in families},
        },
        "notes": [
            "Quantiles are over per-(config_id, role) segment means, not raw actions, so a "
            "single heavily-replayed configuration cannot dominate a band.",
            "Schema-v1 marginal quantiles are retained as an explicit comparator. Schema-v2 "
            "sampling draws one role-compatible empirical parameter bundle, preserving its "
            "within-segment dependence and explicit missingness.",
            "accept_threshold is the interpolated share at which observed acceptance crosses 0.5 "
            "within a segment; segments without a crossing are excluded rather than imputed.",
        ],
    }

    out = ensure_dir(output_dir)
    write_json(out / "opponent_population.json", payload)
    missing = [f"{family}.{name}" for family, params in families.items() for name, value in params.items() if value is None]
    if missing:
        payload["unfitted_parameters"] = missing
        write_json(out / "opponent_population.json", payload)
    return payload


class OpponentPopulation:
    """Draws fitted joint bundles, with schema-v1 marginals as compatibility."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.families = payload.get("families", {})
        self.joint_bundles = payload.get("joint_bundles", {})
        self.bands = {name: tuple(band) for name, band in (payload.get("archetype_bands") or {}).items()}
        self.inverted = set(payload.get("inverted_parameters") or INVERTED_PARAMETERS)

    @classmethod
    def load(cls, path: str | Path | None) -> "OpponentPopulation | None":
        if not path:
            return None
        p = Path(path)
        if p.is_dir():
            p = p / "opponent_population.json"
        if not p.exists():
            return None
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def band(self, archetype: str) -> tuple[float, float]:
        return self.bands.get(archetype, DEFAULT_BAND)

    def sample_bundle(
        self,
        family: str,
        role: str,
        config: dict[str, Any],
        rng: Any,
    ) -> dict[str, Any] | None:
        """Sample the empirical joint population conditional on scenario config."""

        role_bundles = [bundle for bundle in (self.joint_bundles.get(family) or []) if bundle.get("role") == role]
        if not role_bundles:
            return None
        exact = config_signature(family, config)
        coarse = config_signature(family, config, coarse=True)
        eligible = [bundle for bundle in role_bundles if bundle.get("config_signature") == exact]
        level = "exact"
        if not eligible:
            eligible = [bundle for bundle in role_bundles if bundle.get("coarse_config_signature") == coarse]
            level = "coarse"
        if not eligible:
            eligible = role_bundles
            level = "role"
        weights = [max(1, int(bundle.get("weight", 1))) for bundle in eligible]
        selected = dict(rng.choices(eligible, weights=weights, k=1)[0])
        selected["draw_fallback_level"] = level
        percentile = float(selected.get("latent_percentile", 0.5))
        selected["derived_archetype"] = min(
            self.bands or {"historical_imitator": DEFAULT_BAND},
            key=lambda name: abs(percentile - sum(self.band(name)) / 2),
        )
        return selected

    def draw(self, family: str, parameter: str, archetype: str, rng: Any) -> float | None:
        """Sample `parameter` from the archetype's quantile window of real behavior."""

        table = (self.families.get(family) or {}).get(parameter)
        if not table:
            return None
        low, high = self.band(archetype)
        if parameter in self.inverted:
            # A high concession rate or accept margin means a softer opponent, so an
            # aggressive archetype must be read from the low end of the observation.
            low, high = 1.0 - high, 1.0 - low
        point = rng.uniform(low, high)
        key = f"{min(0.99, max(0.01, point)):.2f}"
        if key in table:
            return float(table[key])
        nearest = min(table, key=lambda candidate: abs(float(candidate) - point))
        return float(table[nearest])

    def parameters(
        self,
        family: str,
        archetype: str,
        rng: Any,
        *,
        role: str | None = None,
    ) -> dict[str, Any]:
        # Explicit schema-v1 marginal comparator. Production schema-v2 sampling
        # goes only through sample_bundle(family, role, config, rng).
        drawn: dict[str, float] = {}
        for parameter in sorted((self.families.get(family) or {}).keys()):
            value = self.draw(family, parameter, archetype, rng)
            if value is not None:
                drawn[parameter] = value
        return drawn


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Fit synthetic-opponent parameters to real GLEE behavior.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="models/opponent_population")
    add_split_arguments(parser)
    args = parser.parse_args(argv)
    payload = fit_opponent_population(
        args.data_dir,
        args.output_dir,
        split_mode=args.split_mode,
        split=args.split,
        holdout_fraction=args.holdout_fraction,
    )
    summary = {
        "events_scanned": payload["events_scanned"],
        "events_skipped_by_split": payload["events_skipped_by_split"],
        "provenance": payload["provenance"],
        "observations": payload["observations"],
        "unfitted_parameters": payload.get("unfitted_parameters", []),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
