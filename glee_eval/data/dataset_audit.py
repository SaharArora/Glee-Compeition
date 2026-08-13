from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from glee_eval.config import DEFAULT_DATA_DIR
from glee_eval.data.ingest import as_float
from glee_eval.storage.trajectories import ensure_dir, iter_jsonl, read_records, write_json


@dataclass(frozen=True)
class SupportResult:
    n: int
    action_n: int
    coverage_score: float
    action_bin: str
    bucket_key: str | None
    bucket_level: str | None
    density: float
    occupied_bins: int
    total_bins: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "action_n": self.action_n,
            "coverage_score": self.coverage_score,
            "action_bin": self.action_bin,
            "bucket_key": self.bucket_key,
            "bucket_level": self.bucket_level,
            "density": self.density,
            "occupied_bins": self.occupied_bins,
            "total_bins": self.total_bins,
        }


DEFAULT_MIN_ACTION_SUPPORT = 20
DEFAULT_MIN_CONTEXT_SUPPORT = 200


@dataclass(frozen=True)
class ContextSupportResult:
    """Support for a decision *context*, scored without a candidate action.

    `support_lookup` answers "have we seen this action here?", which needs the
    action to exist first. This answers the prior question "do we know anything
    about this situation at all?", so it can be consulted while the agent is
    still deciding what to do.
    """

    n: int
    density: float
    context_score: float
    bucket_key: str | None
    bucket_level: str | None
    found: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "density": self.density,
            "context_score": self.context_score,
            "bucket_key": self.bucket_key,
            "bucket_level": self.bucket_level,
            "found": self.found,
        }


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
        return False
    return True


def _field_rate(records: list[dict[str, Any]], field: str, *, require_nonempty: bool = False) -> dict[str, Any]:
    present = 0
    for record in records:
        if field not in record:
            continue
        if require_nonempty and not _present(record.get(field)):
            continue
        present += 1
    total = len(records)
    return {"present": present, "total": total, "rate": present / total if total else None}


def _counter(records: list[dict[str, Any]], field: str, *, limit: int | None = None) -> dict[str, int]:
    counts = Counter(str(record.get(field) if _present(record.get(field)) else "missing") for record in records)
    rows = counts.most_common(limit)
    return {key: count for key, count in rows}


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(values),
        "mean": mean(ordered),
        "median": median(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _bin(value: float, width: float = 0.1, low: float = 0.0, high: float = 1.5) -> str:
    if value < low:
        return f"<{low:.1f}"
    if value >= high:
        return f">={high:.1f}"
    start = int(((value - low) / width) + 1e-9) * width + low
    end = start + width
    return f"{start:.1f}-{end:.1f}"


def _round_bucket(round_number: Any, horizon: Any = None) -> str:
    round_int = int(as_float(round_number) or 0)
    horizon_int = int(as_float(horizon) or 0)
    if round_int <= 1:
        return "r1"
    if round_int == 2:
        return "r2"
    if round_int == 3:
        return "r3"
    if horizon_int and round_int >= max(1, horizon_int - 1):
        return "late"
    if round_int <= 5:
        return "r4_5"
    return "r6_plus"


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


def _horizon_from_config(family: str, config: dict[str, Any]) -> int | None:
    key = "total_rounds" if family == "persuasion" else "max_rounds"
    parsed = as_float(config.get(key))
    return int(parsed) if parsed is not None else None


def _coarse_config(family: str, config: dict[str, Any]) -> dict[str, Any]:
    if family == "bargaining":
        return {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "messages_allowed": config.get("messages_allowed"),
            "delta_1": _bin(as_float(config.get("delta_1")) or 0.0, width=0.05, low=0.0, high=1.0),
            "delta_2": _bin(as_float(config.get("delta_2")) or 0.0, width=0.05, low=0.0, high=1.0),
        }
    if family == "negotiation":
        seller_value = as_float(config.get("seller_value"))
        buyer_value = as_float(config.get("buyer_value"))
        surplus = None if seller_value is None or buyer_value is None else max(0.0, buyer_value - seller_value)
        return {
            "max_rounds": config.get("max_rounds"),
            "complete_information": config.get("complete_information"),
            "seller_value": _bin(seller_value or 0.0, width=0.1, low=0.0, high=1.5),
            "buyer_value": _bin(buyer_value or 0.0, width=0.1, low=0.0, high=1.5),
            "surplus": _bin(surplus or 0.0, width=0.1, low=0.0, high=1.0),
        }
    if family == "persuasion":
        return {
            "total_rounds": config.get("total_rounds"),
            "p": _bin(as_float(config.get("p")) or 0.0, width=0.1, low=0.0, high=1.0),
            "v": _bin(as_float(config.get("v")) or 0.0, width=0.1, low=0.0, high=2.0),
            "c": _bin(as_float(config.get("c")) or 0.0, width=0.1, low=0.0, high=1.5),
            "seller_message_type": config.get("seller_message_type"),
            "is_seller_know_cv": config.get("is_seller_know_cv"),
            "is_buyer_know_p": config.get("is_buyer_know_p"),
        }
    return {}


def _message_style(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return "none"
    lowered = text.lower()
    length = "short" if len(text) < 80 else "medium" if len(text) < 240 else "long"
    confidence = "hedged" if any(word in lowered for word in ["maybe", "might", "could", "uncertain", "possibly"]) else "confident"
    return f"{length}_{confidence}"


def _action_value_and_type(family: str, action: Any, config: dict[str, Any]) -> tuple[str, str] | None:
    if not isinstance(action, dict):
        action = {
            "action_type": getattr(action, "action_type", None),
            "numeric_action": getattr(action, "numeric_action", None),
            "structured": getattr(action, "structured", {}),
            "accept_reject": getattr(action, "accept_reject", None),
            "buy_no_buy": getattr(action, "buy_no_buy", None),
        }
    structured = _as_dict(action.get("structured"))
    action_type = str(action.get("action_type") or structured.get("action_type") or "")
    if family == "bargaining" and action_type == "offer":
        money = as_float(config.get("money_to_divide")) or 100.0
        numeric = as_float(action.get("numeric_action"))
        if numeric is None:
            numeric = as_float(structured.get("self_gain"))
        if numeric is None or money <= 0:
            return None
        return "offer", _bin(numeric / money, width=0.05, low=0.0, high=1.0)
    if family == "bargaining" and action_type == "decision":
        decision = action.get("accept_reject") or structured.get("decision")
        return "decision", str(decision or "unknown")
    if family == "negotiation" and action_type == "offer":
        order = as_float(config.get("product_price_order")) or 1_000_000.0
        numeric = as_float(action.get("numeric_action"))
        if numeric is None:
            numeric = as_float(structured.get("product_price"))
        if numeric is None or order <= 0:
            return None
        return "offer", _bin(numeric / order, width=0.05, low=0.0, high=1.5)
    if family == "negotiation" and action_type == "decision":
        decision = action.get("accept_reject") or structured.get("decision")
        return "decision", str(decision or "unknown")
    if family == "persuasion" and action_type in {"recommendation", "message"}:
        decision = action.get("buy_no_buy") or structured.get("decision")
        return "recommendation", str(decision or "unknown")
    if family == "persuasion" and action_type == "buy_decision":
        decision = action.get("buy_no_buy") or structured.get("decision")
        return "buy_decision", str(decision or "unknown")
    return None


def _event_action(event: dict[str, Any]) -> tuple[str, str] | None:
    family = str(event.get("game_family") or "")
    config = _as_dict(event.get("configuration") or event.get("public_parameters"))
    action_type = str(event.get("action_type") or "")
    raw = _as_dict(event.get("raw_record"))
    if family == "bargaining" and action_type == "offer":
        money = as_float(config.get("money_to_divide")) or 100.0
        numeric = as_float(event.get("numeric_action"))
        if numeric is None or money <= 0:
            return None
        return "offer", _bin(numeric / money, width=0.05, low=0.0, high=1.0)
    if family == "bargaining" and action_type == "decision":
        return "decision", str(raw.get("decision") or ("accept" if event.get("accepted") else "reject" if event.get("rejected") else "unknown"))
    if family == "negotiation" and action_type == "offer":
        order = as_float(config.get("product_price_order")) or 1_000_000.0
        numeric = as_float(event.get("numeric_action"))
        if numeric is None or order <= 0:
            return None
        return "offer", _bin(numeric / order, width=0.05, low=0.0, high=1.5)
    if family == "negotiation" and action_type == "decision":
        return "decision", str(raw.get("decision") or ("AcceptOffer" if event.get("accepted") else "RejectOffer" if event.get("rejected") else "unknown"))
    if family == "persuasion" and event.get("role") == "seller" and action_type in {"recommendation", "message"}:
        decision = raw.get("decision") or event.get("buy_no_buy") or raw.get("recommendation")
        return "recommendation", str(decision or "unknown")
    if family == "persuasion" and event.get("role") == "buyer" and action_type == "buy_decision":
        return "buy_decision", str(raw.get("decision") or event.get("buy_no_buy") or "unknown")
    return None


def _support_keys(family: str, config: dict[str, Any], role: str, action_type: str, round_bucket: str) -> list[tuple[str, str]]:
    exact = _canonical_json(config)
    coarse = _canonical_json(_coarse_config(family, config))
    return [
        ("exact", f"exact|{family}|{role}|{action_type}|{round_bucket}|{exact}"),
        ("coarse", f"coarse|{family}|{role}|{action_type}|{round_bucket}|{coarse}"),
        ("family_role_round", f"family_role_round|{family}|{role}|{action_type}|{round_bucket}"),
        ("family_action", f"family_action|{family}|{action_type}"),
    ]


def _support_total_bins(family: str, action_type: str) -> int:
    if family == "bargaining" and action_type == "offer":
        return 20
    if family == "negotiation" and action_type == "offer":
        return 30
    return 2


def build_support_index(events: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for event in events:
        family = str(event.get("game_family") or "")
        role = str(event.get("role") or "unknown")
        config = _as_dict(event.get("configuration") or event.get("public_parameters"))
        event_action = _event_action(event)
        if family not in {"bargaining", "negotiation", "persuasion"} or not event_action:
            continue
        action_type, action_bin = event_action
        round_bucket = _round_bucket(event.get("round"), _horizon_from_config(family, config))
        for level, key in _support_keys(family, config, role, action_type, round_bucket):
            bucket = buckets.setdefault(
                key,
                {
                    "level": level,
                    "family": family,
                    "role": role if level != "family_action" else None,
                    "action_type": action_type,
                    "round_bucket": round_bucket if level != "family_action" else None,
                    "config": config if level == "exact" else _coarse_config(family, config) if level == "coarse" else None,
                    "total_observations": 0,
                    "action_counts": {},
                    "total_bins": _support_total_bins(family, action_type),
                },
            )
            bucket["total_observations"] += 1
            bucket["action_counts"][action_bin] = int(bucket["action_counts"].get(action_bin, 0)) + 1
    for bucket in buckets.values():
        occupied = len([count for count in bucket["action_counts"].values() if count])
        total_bins = int(bucket.get("total_bins") or 1)
        bucket["occupied_bins"] = occupied
        bucket["density"] = occupied / total_bins if total_bins else 0.0
    low_coverage = sorted(
        (
            {
                "key": key,
                "family": bucket["family"],
                "role": bucket.get("role"),
                "action_type": bucket["action_type"],
                "round_bucket": bucket.get("round_bucket"),
                "total_observations": bucket["total_observations"],
                "density": bucket["density"],
                "occupied_bins": bucket["occupied_bins"],
                "total_bins": bucket["total_bins"],
            }
            for key, bucket in buckets.items()
            if bucket["level"] in {"exact", "coarse"} and (bucket["total_observations"] < 50 or bucket["density"] < 0.20)
        ),
        key=lambda row: (row["total_observations"], row["density"]),
    )
    return {
        "schema_version": 1,
        "bucket_count": len(buckets),
        "buckets": buckets,
        "summary": {
            "bucket_count": len(buckets),
            "low_coverage_bucket_count": len(low_coverage),
            "lowest_coverage_buckets": low_coverage[:100],
        },
    }


def _resolve_support_bucket(
    family: str,
    config: dict[str, Any],
    role: str,
    action_type: str,
    round_bucket: str,
    buckets: dict[str, Any],
    min_action_support: int,
) -> tuple[str, str, dict[str, Any]] | None:
    """Walk the bucket-specificity ladder, stopping at the first well-populated level.

    Shared by `support_lookup` and `context_support_lookup` so both read the same
    index through the same exact -> coarse -> family_role_round -> family_action
    fallback order.
    """

    fallback: tuple[str, str, dict[str, Any]] | None = None
    for level, key in _support_keys(family, config, role, action_type, round_bucket):
        bucket = buckets.get(key)
        if not bucket:
            continue
        if fallback is None:
            fallback = (level, key, bucket)
        if int(bucket.get("total_observations") or 0) >= min_action_support:
            return (level, key, bucket)
    return fallback


def context_support_lookup(
    family: str,
    config: dict[str, Any],
    role: str,
    action_type: str,
    state: Any = None,
    *,
    support_index: dict[str, Any] | None = None,
    min_action_support: int = DEFAULT_MIN_ACTION_SUPPORT,
    min_context_support: int = DEFAULT_MIN_CONTEXT_SUPPORT,
) -> dict[str, Any]:
    """Empirical support for a decision context, independent of any candidate action.

    `context_score` blends how many observations the resolved bucket holds with
    how much of the action space those observations occupy, so a bucket that is
    large but concentrated in one bin still scores as partially covered.
    """

    support_index = support_index or {"buckets": {}}
    buckets = support_index.get("buckets", {})
    round_number = getattr(state, "round", None) if state is not None else None
    horizon = getattr(state, "horizon", None) if state is not None else _horizon_from_config(family, config)
    round_bucket = _round_bucket(round_number, horizon)
    resolved = _resolve_support_bucket(family, config, role, action_type, round_bucket, buckets, min_action_support)
    if resolved is None:
        return ContextSupportResult(0, 0.0, 0.0, None, None, False).to_dict()
    level, key, bucket = resolved
    n = int(bucket.get("total_observations") or 0)
    density = float(bucket.get("density") or 0.0)
    volume_part = min(1.0, n / max(1, min_context_support))
    context_score = max(0.0, min(1.0, 0.5 * volume_part + 0.5 * density))
    return ContextSupportResult(n, density, context_score, key, level, True).to_dict()


def support_lookup(
    family: str,
    config: dict[str, Any],
    role: str,
    action: Any,
    state: Any = None,
    *,
    support_index: dict[str, Any] | None = None,
    min_action_support: int = DEFAULT_MIN_ACTION_SUPPORT,
) -> dict[str, Any]:
    support_index = support_index or {"buckets": {}}
    action_info = _action_value_and_type(family, action, config)
    if not action_info:
        return SupportResult(0, 0, 0.0, "unknown", None, None, 0.0, 0, 0).to_dict()
    action_type, action_bin = action_info
    round_number = getattr(state, "round", None) if state is not None else None
    horizon = getattr(state, "horizon", None) if state is not None else _horizon_from_config(family, config)
    round_bucket = _round_bucket(round_number, horizon)
    buckets = support_index.get("buckets", {})
    fallback = _resolve_support_bucket(family, config, role, action_type, round_bucket, buckets, min_action_support)
    if fallback is None:
        return SupportResult(0, 0, 0.0, action_bin, None, None, 0.0, 0, _support_total_bins(family, action_type)).to_dict()
    level, key, bucket = fallback
    action_n = int((bucket.get("action_counts") or {}).get(action_bin, 0))
    n = int(bucket.get("total_observations") or 0)
    density = float(bucket.get("density") or 0.0)
    support_part = min(1.0, action_n / max(1, min_action_support))
    coverage_score = max(0.0, min(1.0, 0.75 * support_part + 0.25 * density))
    return SupportResult(
        n=n,
        action_n=action_n,
        coverage_score=coverage_score,
        action_bin=action_bin,
        bucket_key=key,
        bucket_level=level,
        density=density,
        occupied_bins=int(bucket.get("occupied_bins") or 0),
        total_bins=int(bucket.get("total_bins") or 0),
    ).to_dict()


def _private_key_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        private = event.get("private_information") or {}
        if isinstance(private, str):
            try:
                private = json.loads(private)
            except json.JSONDecodeError:
                private = {}
        for key, value in (private or {}).items():
            if _present(value):
                counts[str(key)] += 1
    return dict(counts.most_common())


def _public_key_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for event in events:
        public = event.get("public_parameters") or event.get("configuration") or {}
        if isinstance(public, str):
            try:
                public = json.loads(public)
            except json.JSONDecodeError:
                public = {}
        for key, value in (public or {}).items():
            if _present(value):
                counts[str(key)] += 1
    return dict(counts.most_common())


def _message_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    messages = [str(event.get("free_text_message")) for event in events if _present(event.get("free_text_message"))]
    lengths = [float(len(message)) for message in messages]
    top_messages = Counter(messages).most_common(10)
    styles = Counter(_message_style(message) for message in messages)
    player_turns = [event for event in events if event.get("role") not in {"nature", "missing"}]
    return {
        "message_events": len(messages),
        "player_turns": len(player_turns),
        "message_rate_per_player_turn": len(messages) / len(player_turns) if player_turns else None,
        "length_chars": _summary(lengths),
        "unique_messages": len(set(messages)),
        "style_distribution": dict(styles.most_common()),
        "top_messages": [{"message": message, "count": count} for message, count in top_messages],
    }


def _support_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    bargaining_bins: Counter[str] = Counter()
    negotiation_bins: Counter[str] = Counter()
    persuasion_seller: Counter[str] = Counter()
    persuasion_buyer: Counter[str] = Counter()
    quality: Counter[str] = Counter()
    by_family_role_action: Counter[str] = Counter()

    for event in events:
        family = str(event.get("game_family") or "missing")
        role = str(event.get("role") or "missing")
        action_type = str(event.get("action_type") or "missing")
        by_family_role_action[f"{family}:{role}:{action_type}"] += 1

        if family == "bargaining" and action_type == "offer":
            numeric = as_float(event.get("numeric_action"))
            config = event.get("configuration") or {}
            money = as_float(config.get("money_to_divide")) or 1.0
            if numeric is not None:
                bargaining_bins[_bin(numeric / money, width=0.1, low=0.0, high=1.0)] += 1

        if family == "negotiation" and action_type == "offer":
            numeric = as_float(event.get("numeric_action"))
            config = event.get("configuration") or {}
            order = as_float(config.get("product_price_order")) or 1.0
            if numeric is not None:
                negotiation_bins[_bin(numeric / order, width=0.1, low=0.0, high=1.5)] += 1

        if family == "persuasion":
            raw = event.get("raw_record") or {}
            decision = raw.get("decision")
            if role == "seller" and decision in {"yes", "no"}:
                persuasion_seller[str(decision)] += 1
            if role == "buyer" and decision in {"yes", "no"}:
                persuasion_buyer[str(decision)] += 1
            if action_type == "nature_quality":
                quality[str(raw.get("round_quality") or "missing")] += 1

    return {
        "by_family_role_action": dict(by_family_role_action.most_common()),
        "bargaining_offer_share_bins": dict(sorted(bargaining_bins.items())),
        "negotiation_price_bins": dict(sorted(negotiation_bins.items())),
        "persuasion_seller_recommendations": dict(persuasion_seller.most_common()),
        "persuasion_buyer_decisions": dict(persuasion_buyer.most_common()),
        "persuasion_quality": dict(quality.most_common()),
    }


def _repeated_identity_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    p1_models = Counter(str(game.get("player_1_model")) for game in games if _present(game.get("player_1_model")))
    p2_models = Counter(str(game.get("player_2_model")) for game in games if _present(game.get("player_2_model")))
    p1_names = Counter(str(game.get("player_1_name")) for game in games if _present(game.get("player_1_name")))
    p2_names = Counter(str(game.get("player_2_name")) for game in games if _present(game.get("player_2_name")))
    return {
        "player_1_model_availability": _field_rate(games, "player_1_model", require_nonempty=True),
        "player_2_model_availability": _field_rate(games, "player_2_model", require_nonempty=True),
        "top_player_1_models": dict(p1_models.most_common(20)),
        "top_player_2_models": dict(p2_models.most_common(20)),
        "composition": {
            "human_labeled_games": sum(
                1
                for game in games
                if str(game.get("source") or "").startswith("human")
                or "human" in str(game.get("player_1_model") or "").lower()
                or "human" in str(game.get("player_2_model") or "").lower()
            ),
            "llm_labeled_games": sum(
                1
                for game in games
                if "llm" in str(game.get("source") or "").lower()
                or any(token in str(game.get(field) or "").lower() for field in ["player_1_model", "player_2_model"] for token in ["gpt", "claude", "gemini", "llama"])
            ),
            "bot_labeled_games": sum(
                1
                for game in games
                if any(token in str(game.get(field) or "").lower() for field in ["player_1_model", "player_2_model"] for token in ["bot", "agent", "heuristic"])
            ),
        },
        "repeated_public_names": {
            "player_1": {name: count for name, count in p1_names.most_common(20) if count > 1},
            "player_2": {name: count for name, count in p2_names.most_common(20) if count > 1},
        },
    }


def _turns_per_game(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(event.get("game_id")) for event in events if _present(event.get("game_id")))
    return _summary([float(value) for value in counts.values()])


def _schema_rates(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    game_fields = [
        "game_id",
        "game_family",
        "source",
        "config_id",
        "configuration",
        "terminal_outcome",
        "player_1_payoff",
        "player_2_payoff",
        "player_1_model",
        "player_2_model",
        "path",
    ]
    event_fields = [
        "event_id",
        "game_id",
        "game_family",
        "source",
        "config_id",
        "role",
        "round",
        "transcript_so_far",
        "action_type",
        "numeric_action",
        "free_text_message",
        "private_information",
        "public_parameters",
        "terminal_outcome",
        "player_payoff",
        "opponent_payoff",
    ]
    return {
        "game_fields": {
            field: _field_rate(games, field, require_nonempty=field in {"player_1_model", "player_2_model", "path"})
            for field in game_fields
        },
        "event_fields": {
            field: _field_rate(events, field, require_nonempty=field in {"numeric_action", "free_text_message"})
            for field in event_fields
        },
    }


def _strategy_verdict(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    game_count = len(games)
    event_count = len(events)
    has_messages = any(_present(event.get("free_text_message")) for event in events)
    has_private = any(_present(event.get("private_information")) for event in events)
    has_models = any(_present(game.get("player_1_model")) or _present(game.get("player_2_model")) for game in games)
    has_three_families = len({game.get("game_family") for game in games if _present(game.get("game_family"))}) >= 3

    if game_count == 0:
        verdict = "no_processed_dataset"
        budget = "Do not run large simulations. First ingest or obtain real GLEE records."
    elif game_count < 1000:
        verdict = "toy_or_smoke_dataset"
        budget = "Use simulation only for harness sanity checks and adversarial smoke tests. Do not treat synthetic rows as the main training dataset."
    elif game_count < 100000:
        verdict = "empirical_pilot_dataset"
        budget = "Use real data for priors and response-surface pilots. Keep simulation targeted to counterfactual and adversarial gaps."
    else:
        verdict = "empirical_foundation_candidate"
        budget = "Make real data the primary foundation. Simulation should be targeted stress testing, rare-event generation, and counterfactual policy evaluation."

    blockers = []
    if 0 < game_count < 1000:
        blockers.append("dataset_too_small_for_empirical_foundation")
    if not has_three_families:
        blockers.append("not_all_three_game_families_present")
    if not has_private:
        blockers.append("private_or_hidden_state_sparse_or_missing")
    if not has_messages:
        blockers.append("message_text_sparse_or_missing")
    if not has_models:
        blockers.append("player_or_model_identity_sparse_or_missing")
    if event_count == 0:
        blockers.append("no_turn_level_events")

    next_actions = [
        "Audit the largest real GLEE dataset you can access before scaling simulation.",
        "Use action-support bins to decide where offline response models are reliable.",
        "Use synthetic tournaments for smoke tests and adversarial search, not as the primary behavioral population.",
        "Only train behavioral or counterfactual models after confirming turn-level state, action, outcome, and hidden-state coverage.",
    ]

    return {
        "verdict": verdict,
        "simulation_budget": budget,
        "blockers": blockers,
        "next_actions": next_actions,
    }


def audit_records(games: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    support_index = build_support_index(events)
    return {
        "dataset_size": {
            "games": len(games),
            "events": len(events),
            "turns_per_game": _turns_per_game(events),
        },
        "distributions": {
            "games_by_family": _counter(games, "game_family"),
            "events_by_family": _counter(events, "game_family"),
            "games_by_source": _counter(games, "source"),
            "events_by_role": _counter(events, "role"),
            "events_by_action_type": _counter(events, "action_type"),
            "top_config_ids": _counter(games, "config_id", limit=25),
        },
        "schema_availability": _schema_rates(games, events),
        "identity": _repeated_identity_summary(games),
        "history_and_messages": _message_summary(events),
        "state_keys": {
            "public_parameter_keys": _public_key_counts(events),
            "private_information_keys": _private_key_counts(events),
        },
        "empirical_action_support": _support_summary(events),
        "empirical_action_support_by_state": support_index["summary"],
        "strategy_recommendation": _strategy_verdict(games, events),
    }


def _fmt_rate(row: dict[str, Any]) -> str:
    rate = row.get("rate")
    return "" if rate is None else f"{rate:.3f}"


def _counter_table(title: str, rows: dict[str, int], limit: int = 20) -> list[str]:
    lines = [f"## {title}", "", "| Value | Count |", "|---|---:|"]
    if not rows:
        lines.append("| none | 0 |")
    for key, count in list(rows.items())[:limit]:
        lines.append(f"| {key} | {count} |")
    lines.append("")
    return lines


def audit_markdown(report: dict[str, Any]) -> str:
    size = report["dataset_size"]
    recommendation = report["strategy_recommendation"]
    lines = [
        "# GLEE Dataset Audit",
        "",
        f"Verdict: `{recommendation['verdict']}`",
        "",
        recommendation["simulation_budget"],
        "",
        "## Size",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Games | {size['games']} |",
        f"| Events | {size['events']} |",
        f"| Mean turns/events per game | {size['turns_per_game'].get('mean')} |",
        "",
    ]

    blockers = recommendation.get("blockers") or []
    lines.extend(["## Blockers", ""])
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("No immediate schema blockers detected by this lightweight audit.")
    lines.append("")

    lines.extend(_counter_table("Games By Family", report["distributions"]["games_by_family"]))
    lines.extend(_counter_table("Events By Role", report["distributions"]["events_by_role"]))
    lines.extend(_counter_table("Events By Action Type", report["distributions"]["events_by_action_type"]))

    lines.extend(["## Essential Event Field Availability", "", "| Field | Present | Total | Rate |", "|---|---:|---:|---:|"])
    essential = ["game_id", "game_family", "role", "round", "action_type", "transcript_so_far", "private_information", "public_parameters", "terminal_outcome"]
    event_fields = report["schema_availability"]["event_fields"]
    for field in essential:
        row = event_fields[field]
        lines.append(f"| {field} | {row['present']} | {row['total']} | {_fmt_rate(row)} |")
    lines.append("")

    messages = report["history_and_messages"]
    lines.extend(
        [
            "## Messages",
            "",
            f"- Message events: {messages['message_events']}",
            f"- Message rate per player turn: {messages['message_rate_per_player_turn']}",
            f"- Unique messages: {messages['unique_messages']}",
            f"- Message style distribution: `{messages.get('style_distribution', {})}`",
            "",
        ]
    )

    support = report["empirical_action_support"]
    lines.extend(_counter_table("Bargaining Offer Share Support", support["bargaining_offer_share_bins"]))
    lines.extend(_counter_table("Negotiation Price Support", support["negotiation_price_bins"]))
    lines.extend(_counter_table("Persuasion Seller Recommendations", support["persuasion_seller_recommendations"]))
    lines.extend(_counter_table("Persuasion Buyer Decisions", support["persuasion_buyer_decisions"]))

    state_support = report.get("empirical_action_support_by_state", {})
    lines.extend(
        [
            "## State-Action Coverage",
            "",
            f"- Support buckets: {state_support.get('bucket_count', 'see support_index.json')}",
            f"- Low-coverage buckets: {state_support.get('low_coverage_bucket_count')}",
            "",
            "| Family | Role | Action | Round Bucket | Observations | Density |",
            "|---|---|---|---|---:|---:|",
        ]
    )
    for row in state_support.get("lowest_coverage_buckets", [])[:20]:
        lines.append(
            f"| {row.get('family')} | {row.get('role')} | {row.get('action_type')} | {row.get('round_bucket')} | "
            f"{row.get('total_observations')} | {row.get('density')} |"
        )
    lines.append("")

    lines.extend(["## Next Actions", ""])
    for item in recommendation["next_actions"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


AUDIT_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "game_id",
        "game_family",
        "source",
        "config_id",
        "role",
        "player",
        "round",
        "action_type",
        "numeric_action",
        "free_text_message",
        "private_information",
        "public_parameters",
        "configuration",
        "terminal_outcome",
        "player_payoff",
        "opponent_payoff",
        "raw_record",
        "accepted",
        "rejected",
        "bought",
        "player_1_model",
        "player_2_model",
    }
)

# The audit reads `transcript_so_far` only through its presence/non-emptiness
# rate, never its contents, but it is by far the largest field on an event. A
# one-element placeholder preserves every quantity the audit derives from it.
_TRANSCRIPT_PLACEHOLDER = "<omitted_by_audit_projection>"


def _project_event(event: dict[str, Any]) -> dict[str, Any]:
    projected = {key: value for key, value in event.items() if key in AUDIT_EVENT_FIELDS}
    transcript = event.get("transcript_so_far")
    length = len(transcript) if isinstance(transcript, (list, str, dict)) else 0
    projected["transcript_so_far"] = [_TRANSCRIPT_PLACEHOLDER] if length else transcript
    return projected


def read_audit_events(path: str | Path, *, project: bool = True) -> list[dict[str, Any]]:
    """Read turn-level events for the audit, projected down by default.

    On the full released GLEE dataset the raw events do not fit in memory
    (~21 GB of Python objects for ~1.2M events, dominated by the running
    transcript each event carries). Projecting to the fields the audit actually
    reads brings that to roughly a third with no change to any reported figure.
    Pass `project=False` to audit the unreduced records.
    """

    p = Path(path)
    if not project or p.suffix != ".jsonl":
        return read_records(p)
    return [_project_event(event) for event in iter_jsonl(p)]


def audit_processed(
    data_dir: str | Path = DEFAULT_DATA_DIR,
    output_dir: str | Path = "reports/dataset_audit",
    *,
    project_events: bool = True,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    games = read_records(data_dir / "processed" / "games.jsonl")
    events = read_audit_events(data_dir / "processed" / "events.jsonl", project=project_events)
    report = audit_records(games, events)
    report["event_projection"] = {
        "applied": bool(project_events),
        "kept_fields": sorted(AUDIT_EVENT_FIELDS),
        "reduced_fields": ["transcript_so_far"],
        "note": "transcript_so_far is replaced by a length-preserving placeholder; the audit only reads its presence rate.",
    }
    support_index = build_support_index(events)
    report["empirical_action_support_by_state"] = support_index["summary"]
    out = ensure_dir(output_dir)
    write_json(out / "audit.json", report)
    write_json(out / "support_index.json", support_index)
    (out / "audit.md").write_text(audit_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Audit processed GLEE data for empirical-first strategy readiness.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default="reports/dataset_audit")
    parser.add_argument(
        "--no-project-events",
        action="store_true",
        help="Audit unreduced event records (needs far more memory on the full dataset).",
    )
    args = parser.parse_args(argv)
    report = audit_processed(args.data_dir, args.output_dir, project_events=not args.no_project_events)
    print(json.dumps(report["strategy_recommendation"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
