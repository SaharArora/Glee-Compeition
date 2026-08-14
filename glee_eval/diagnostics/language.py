"""Does *how* a persuasion seller writes correlate with whether the buyer buys?

Step 3 of the persuasion plan, and deliberately an analysis rather than an
architecture. The point is to find out whether language leverage exists in the
real data at all before any engineering is spent on a communication layer.

The measurement problem is that in text mode there is no separate recommendation
field -- the message *is* the signal -- so raw correlations between style and
purchase mostly restate "sellers who endorse the product get more sales". Two
things are therefore held fixed:

* **realized quality**, which nature draws exogenously, and
* **the stance the message takes** (endorse / discourage / neutral), derived from
  the text so that style can be compared within one stance.

Optionally also the seller's model identity, because writing style is strongly
tied to which LLM produced it, and a naive pooled estimate would partly measure
"gemini sells better than llama".

What comes out is a *stratified association*, not a causal effect. Sellers choose
their words, so a feature can proxy for private intent -- a seller about to
oversell a low-quality item may hedge more. Causal machinery is deferred by
design, and nothing here should be read as an intervention estimate.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.data.transcripts import persuasion_round_quality, same_round_transcript_item, transcript_item_decision
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, write_json


# Feature vocabulary. Kept as transparent keyword rules rather than a learned
# classifier so that a reader can audit exactly what each feature counts, and so
# the result cannot be an artifact of an opaque embedding.
_PATTERNS: dict[str, tuple[str, ...]] = {
    "hedged": (
        r"can'?t guarantee", r"cannot guarantee", r"no guarantee", r"\bmay\b", r"\bmight\b",
        r"\bcould be\b", r"\bpossibly\b", r"\bperhaps\b", r"\buncertain\b", r"\bnot sure\b",
    ),
    "confident": (
        r"\bguarantee[ds]?\b", r"\bcertainly\b", r"\bdefinitely\b", r"\babsolutely\b",
        r"\bassure\b", r"\bconfident\b", r"\bstrongly\b", r"\bexcellent\b",
    ),
    "social_proof": (
        r"previous buyers", r"past buyers", r"many buyers", r"other buyers", r"customers",
        r"others have", r"track record", r"buyers have",
    ),
    "discloses_probability": (r"\d+\s*%", r"\bchance\b", r"\bprobability\b", r"\blikelihood\b"),
    "discloses_value": (r"\$\s*[\d,]+", r"valued at", r"\bworth\b"),
    "endorses": (
        r"\brecommend\b", r"\bencourage\b", r"\bsuggest\b", r"worth buying", r"good (?:deal|opportunity|buy)",
        r"you should buy", r"great value",
    ),
    # Stance is a *control* variable, so a miss here contaminates the strata rather
    # than merely adding noise. The stems are deliberately loose: an earlier version
    # required the literal "pass on" and so read "I recommend passing on this
    # product" -- our own template -- as an endorsement.
    "discourages": (
        r"\bdo not recommend\b", r"\bdon'?t recommend\b", r"\bnot recommend\b", r"\bwould not\b",
        r"\bwouldn'?t\b", r"\bpass(?:ing|es)? on\b", r"\bavoid\b", r"\bskip\b", r"\bnot worth\b",
        r"\bhold off\b", r"\bwait for\b", r"\bnot advise\b", r"\bdiscourage\b", r"\brefrain\b",
        r"\bbetter (?:to )?(?:wait|skip|pass)\b", r"\bdo not buy\b", r"\bdon'?t buy\b",
        r"\bnot (?:a )?good (?:deal|buy|value)\b", r"\blow[- ]quality\b.*\bnot\b",
    ),
    "loss_frame": (r"miss out", r"\bmiss\b", r"\blose\b", r"\brisk\b", r"\bdon'?t miss\b"),
    "gain_frame": (r"\bopportunity\b", r"\bbenefit\b", r"\bgain\b", r"\bsave\b", r"\badvantage\b"),
    "reciprocity": (r"\bhonest\b", r"\btransparent\b", r"\btrust\b", r"\bfair\b", r"\bupfront\b", r"\bopen with you\b"),
    "asks_question": (r"\?",),
}
_COMPILED = {name: [re.compile(pattern, re.IGNORECASE) for pattern in patterns] for name, patterns in _PATTERNS.items()}

FEATURES = tuple(sorted(_PATTERNS)) + ("long_message",)

# Median real message length is 253 characters.
_LONG_MESSAGE_CHARS = 253


def message_features(message: str) -> dict[str, int]:
    text = str(message or "")
    features = {name: int(any(pattern.search(text) for pattern in patterns)) for name, patterns in _COMPILED.items()}
    features["long_message"] = int(len(text) > _LONG_MESSAGE_CHARS)
    return features


def message_stance(features: dict[str, int]) -> str:
    """The economic content of the message: what it tells the buyer to do."""

    if features.get("discourages"):
        return "discourage"
    if features.get("endorses"):
        return "endorse"
    return "neutral"


def _stratified_difference(rows: list[dict[str, Any]], feature: str, strata_keys: tuple[str, ...]) -> dict[str, Any]:
    """Buy-rate difference for `feature`, pooled across strata by inverse variance.

    Strata with the feature entirely present or entirely absent carry no
    information about it and are dropped; the count is reported so a result that
    rests on very few strata is visible.
    """

    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in strata_keys)].append(row)

    numerator = 0.0
    denominator = 0.0
    variance_numerator = 0.0
    used_strata = 0
    dropped_strata = 0
    covered = 0
    for group in groups.values():
        present = [row for row in group if row["features"][feature]]
        absent = [row for row in group if not row["features"][feature]]
        if not present or not absent:
            dropped_strata += 1
            continue
        used_strata += 1
        covered += len(group)
        n1, n0 = len(present), len(absent)
        p1 = sum(row["bought"] for row in present) / n1
        p0 = sum(row["bought"] for row in absent) / n0
        weight = (n1 * n0) / (n1 + n0)
        numerator += weight * (p1 - p0)
        denominator += weight
        variance_numerator += (weight ** 2) * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)

    if denominator <= 0:
        return {"feature": feature, "estimable": False, "strata_used": 0, "strata_dropped": dropped_strata}
    effect = numerator / denominator
    standard_error = math.sqrt(variance_numerator) / denominator if variance_numerator > 0 else 0.0
    prevalence = sum(row["features"][feature] for row in rows) / len(rows) if rows else 0.0
    return {
        "feature": feature,
        "estimable": True,
        "prevalence": prevalence,
        "effect_on_purchase_rate": effect,
        "standard_error": standard_error,
        "z": effect / standard_error if standard_error > 0 else None,
        "ci95_low": effect - 1.96 * standard_error,
        "ci95_high": effect + 1.96 * standard_error,
        "strata_used": used_strata,
        "strata_dropped": dropped_strata,
        "rows_in_used_strata": covered,
    }


def analyze_language(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/persuasion_language",
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    events_path = Path(data_dir) / "processed" / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"Missing processed events file: {events_path}")

    rows: list[dict[str, Any]] = []
    scanned = 0
    skipped = 0
    for event in iter_jsonl(events_path):
        if event.get("game_family") != "persuasion" or event.get("role") != "buyer":
            continue
        if event.get("bought") is None:
            continue
        scanned += 1
        if limit and len(rows) >= limit:
            break
        config = event.get("configuration") or event.get("public_parameters") or {}
        if str(config.get("seller_message_type") or "") != "text":
            continue
        seller = same_round_transcript_item(event, role="seller")
        message = (seller or {}).get("free_text_message") or ((seller or {}).get("raw") or {}).get("message")
        quality = persuasion_round_quality(event)
        if not message or quality not in {"high-quality", "low-quality"}:
            skipped += 1
            continue
        features = message_features(str(message))
        p = as_float(config.get("p"))
        rows.append(
            {
                "bought": 1 if event.get("bought") else 0,
                "quality": quality,
                "stance": message_stance(features),
                "p_bin": "unknown" if p is None else f"{round(float(p), 1):.1f}",
                "round_bin": "early" if int(as_float(event.get("round")) or 0) <= 3 else "later",
                "seller_model": str(event.get("player_1_model") or "unknown"),
                "is_myopic": bool(config.get("is_myopic")),
                "features": features,
            }
        )

    base_strata = ("quality", "stance", "p_bin")
    model_strata = base_strata + ("seller_model",)

    def _table(strata: tuple[str, ...]) -> list[dict[str, Any]]:
        return sorted(
            (_stratified_difference(rows, feature, strata) for feature in FEATURES),
            key=lambda item: -abs(item.get("effect_on_purchase_rate") or 0.0),
        )

    stance_rates = {}
    for stance in ("endorse", "neutral", "discourage"):
        subset = [row for row in rows if row["stance"] == stance]
        stance_rates[stance] = {
            "n": len(subset),
            "purchase_rate": (sum(row["bought"] for row in subset) / len(subset)) if subset else None,
        }

    report = {
        "schema_version": 1,
        "buyer_decisions_scanned": scanned,
        "text_mode_rows_used": len(rows),
        "rows_skipped": skipped,
        "overall_purchase_rate": (sum(row["bought"] for row in rows) / len(rows)) if rows else None,
        "purchase_rate_by_stance": stance_rates,
        "controls": {
            "base": list(base_strata),
            "with_seller_model": list(model_strata),
        },
        "stratified_by_quality_stance_prior": _table(base_strata),
        "stratified_also_by_seller_model": _table(model_strata),
        "notes": [
            "Effects are differences in buyer purchase rate between messages that do and do "
            "not carry the feature, pooled across strata by inverse variance.",
            "Stance is derived from the text because text-mode games have no separate "
            "recommendation field; controlling for it is what separates style from content.",
            "These are associations, not causal effects. A seller chooses their words, so a "
            "feature can proxy for private intent rather than move the buyer.",
        ],
    }
    out = ensure_dir(output_dir)
    write_json(out / "persuasion_language.json", report)
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Does message style correlate with real purchase outcomes?")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/persuasion_language")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    report = analyze_language(args.data_dir, args.output_dir, limit=args.limit)
    print(json.dumps({k: v for k, v in report.items() if k != "notes"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
