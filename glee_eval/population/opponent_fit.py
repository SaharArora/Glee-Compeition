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
from statistics import mean
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
) -> dict[str, Any]:
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    barg_shares: dict[tuple[str, str], list[float]] = defaultdict(list)
    barg_concessions: list[float] = []
    barg_curve: dict[str, dict[float, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    neg_prices: dict[tuple[str, str], list[float]] = defaultdict(list)
    neg_concessions: list[float] = []
    neg_margins: dict[str, list[float]] = defaultdict(list)
    pers_truth: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_yes_on_low: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    pers_trust: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    last_share: dict[tuple[str, str], float] = {}
    last_price: dict[tuple[str, str], float] = {}
    scanned = 0

    for event in iter_jsonl(events_path):
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
                barg_shares[(config_id, role)].append(share)
                previous = last_share.get(game_role)
                if previous is not None:
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
                neg_prices[(config_id, role)].append(price)
                previous = last_price.get(game_role)
                if previous is not None:
                    neg_concessions.append(previous - price if role == "seller" else price - previous)
                last_price[game_role] = price
            elif event.get("action_type") == "decision" and str(raw.get("decision") or "") == "AcceptOffer":
                offer = last_transcript_action(event, "offer")
                order = as_float(config.get("product_price_order")) or 1_000_000.0
                accepted_price = as_float((offer or {}).get("numeric_action"))
                if accepted_price is None:
                    accepted_price = as_float(as_dict((offer or {}).get("raw")).get("product_price"))
                own = as_float(config.get("seller_value" if role == "seller" else "buyer_value"))
                if accepted_price is not None and own is not None and order > 0:
                    normalized = accepted_price / order
                    margin = normalized - own if role == "seller" else own - normalized
                    neg_margins[config_id].append(margin)

        elif family == "persuasion":
            if role == "seller" and event.get("action_type") in {"recommendation", "message"}:
                quality = persuasion_round_quality(event)
                recommendation = persuasion_recommendation(event) or (raw.get("decision") if raw else None)
                if quality and recommendation in {"yes", "no"}:
                    truthful = int((recommendation == "yes") == (quality == "high-quality"))
                    bucket = pers_truth[config_id]
                    bucket[0] += truthful
                    bucket[1] += 1
                    if quality == "low-quality":
                        low = pers_yes_on_low[config_id]
                        low[0] += int(recommendation == "yes")
                        low[1] += 1
            elif role == "buyer" and event.get("action_type") == "buy_decision":
                seller_item = same_round_transcript_item(event, role="seller")
                recommendation = persuasion_recommendation(seller_item)
                bought = raw.get("decision") or event.get("buy_no_buy")
                if recommendation == "yes" and bought in {"yes", "no"}:
                    bucket = pers_trust[config_id]
                    bucket[0] += int(bought == "yes")
                    bucket[1] += 1

    def _rates(counts: dict[str, list[int]]) -> list[float]:
        return [hits / total for hits, total in counts.values() if total >= 10]

    barg_thresholds = [value for value in (_threshold_crossing(curve) for curve in barg_curve.values()) if value is not None]

    families: dict[str, Any] = {
        "bargaining": {
            "target_share": _quantiles([mean(values) for values in barg_shares.values() if values]),
            "concession_rate": _quantiles([value for value in barg_concessions if -0.5 <= value <= 0.5]),
            "accept_threshold": _quantiles(barg_thresholds),
        },
        "negotiation": {
            "aspiration_price": _quantiles([mean(values) for values in neg_prices.values() if values]),
            "concession_rate": _quantiles([value for value in neg_concessions if -0.5 <= value <= 0.5]),
            "accept_margin": _quantiles([value for values in neg_margins.values() for value in values]),
        },
        "persuasion": {
            "honesty": _quantiles(_rates(pers_truth)),
            "yes_on_low_rate": _quantiles(_rates(pers_yes_on_low)),
            "trust_prior": _quantiles(_rates(pers_trust)),
        },
    }

    observations = {
        "bargaining_offer_segments": len(barg_shares),
        "bargaining_concession_observations": len(barg_concessions),
        "bargaining_threshold_segments": len(barg_thresholds),
        "negotiation_offer_segments": len(neg_prices),
        "negotiation_concession_observations": len(neg_concessions),
        "negotiation_accepted_margin_observations": sum(len(v) for v in neg_margins.values()),
        "persuasion_seller_segments": len(pers_truth),
        "persuasion_buyer_segments": len(pers_trust),
    }

    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_dir": str(data_dir),
        "events_scanned": scanned,
        "min_segment_observations": _MIN_BUCKET,
        "archetype_bands": {name: list(band) for name, band in ARCHETYPE_BANDS.items()},
        "inverted_parameters": sorted(INVERTED_PARAMETERS),
        "observations": observations,
        "families": families,
        "notes": [
            "Quantiles are over per-(config_id, role) segment means, not raw actions, so a "
            "single heavily-replayed configuration cannot dominate a band.",
            "An archetype is a quantile window of observed behavior, not a fitted latent type. "
            "The learned latent-type model (Model B) is still deferred.",
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
    """Draws opponent parameters from fitted quantiles, by archetype band."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.families = payload.get("families", {})
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

    def parameters(self, family: str, archetype: str, rng: Any) -> dict[str, float]:
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
    args = parser.parse_args(argv)
    payload = fit_opponent_population(args.data_dir, args.output_dir)
    summary = {
        "events_scanned": payload["events_scanned"],
        "observations": payload["observations"],
        "unfitted_parameters": payload.get("unfitted_parameters", []),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
