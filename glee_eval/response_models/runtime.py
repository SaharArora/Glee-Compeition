from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResponseEstimate:
    probability: float
    support: int
    uncertainty: float
    support_quality: float
    key: str
    fallback_level: int

    @property
    def ood_penalty(self) -> float:
        return 1.0 - self.support_quality

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": self.probability,
            "support": self.support,
            "uncertainty": self.uncertainty,
            "support_quality": self.support_quality,
            "ood_penalty": self.ood_penalty,
            "key": self.key,
            "fallback_level": self.fallback_level,
        }


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text.replace("$", "").replace(",", ""))
    except ValueError:
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_bin(round_number: int, horizon: int | None = None) -> str:
    if round_number <= 1:
        return "r1"
    if round_number == 2:
        return "r2"
    if round_number == 3:
        return "r3"
    if horizon and horizon > 0 and round_number >= max(1, horizon - 1):
        return "late"
    if round_number <= 5:
        return "r4_5"
    return "r6_plus"


def _bin(value: float, width: float, low: float, high: float) -> str:
    if value < low:
        return f"<{low:.2f}"
    if value >= high:
        return f">={high:.2f}"
    start = int(((value - low) / width) + 1e-9) * width + low
    end = start + width
    return f"{start:.2f}-{end:.2f}"


def _bool_label(value: Any) -> str:
    return "true" if bool(value) else "false"


def _config(event_or_state: Any) -> dict[str, Any]:
    if isinstance(event_or_state, dict):
        return _as_dict(event_or_state.get("configuration") or event_or_state.get("public_parameters"))
    return _as_dict(getattr(event_or_state, "public_parameters", {}))


def _source(event_or_state: Any) -> str:
    if isinstance(event_or_state, dict):
        return str(event_or_state.get("source") or "unknown")
    metadata = getattr(event_or_state, "metadata", {}) or {}
    return str(metadata.get("source") or "synthetic")


def _horizon(event_or_state: Any) -> int:
    if isinstance(event_or_state, dict):
        config = _config(event_or_state)
        return int(_as_float(config.get("max_rounds") or config.get("total_rounds"), 0) or 0)
    return int(getattr(event_or_state, "horizon", 0) or 0)


def _round(event_or_state: Any) -> int:
    if isinstance(event_or_state, dict):
        return int(_as_float(event_or_state.get("round"), 0) or 0)
    return int(getattr(event_or_state, "round", 0) or 0)


def bargaining_keys(event_or_state: Any, responder_role: str, offered_share_to_responder: float) -> list[str]:
    config = _config(event_or_state)
    share_bin = _bin(_clip(offered_share_to_responder, 0.0, 1.2), 0.05, 0.0, 1.0)
    round_bin = _round_bin(_round(event_or_state), _horizon(event_or_state))
    source = _source(event_or_state)
    complete = _bool_label(config.get("complete_information"))
    messages = _bool_label(config.get("messages_allowed"))
    return [
        f"role={responder_role}|round={round_bin}|share={share_bin}|complete={complete}|messages={messages}|source={source}",
        f"role={responder_role}|round={round_bin}|share={share_bin}|complete={complete}|messages={messages}",
        f"role={responder_role}|round={round_bin}|share={share_bin}",
        f"role={responder_role}|share={share_bin}",
        f"share={share_bin}",
        "__global__",
    ]


def negotiation_keys(event_or_state: Any, responder_role: str, normalized_price: float) -> list[str]:
    config = _config(event_or_state)
    price_bin = _bin(_clip(normalized_price, 0.0, 2.0), 0.05, 0.0, 1.5)
    round_bin = _round_bin(_round(event_or_state), _horizon(event_or_state))
    source = _source(event_or_state)
    seller_value = _as_float(config.get("seller_value"), None)
    buyer_value = _as_float(config.get("buyer_value"), None)
    surplus = None if seller_value is None or buyer_value is None else max(0.0, buyer_value - seller_value)
    surplus_bin = _bin(surplus, 0.10, 0.0, 1.0) if surplus is not None else "unknown"
    return [
        f"role={responder_role}|round={round_bin}|price={price_bin}|surplus={surplus_bin}|source={source}",
        f"role={responder_role}|round={round_bin}|price={price_bin}|surplus={surplus_bin}",
        f"role={responder_role}|round={round_bin}|price={price_bin}",
        f"role={responder_role}|price={price_bin}",
        f"price={price_bin}",
        "__global__",
    ]


def message_style(message: str | None) -> str:
    text = (message or "").strip()
    if not text:
        return "none"
    lowered = text.lower()
    if len(text) < 80:
        length = "short"
    elif len(text) < 240:
        length = "medium"
    else:
        length = "long"
    confidence = "hedged" if any(word in lowered for word in ["maybe", "might", "could", "uncertain", "possibly"]) else "confident"
    return f"{length}_{confidence}"


def persuasion_keys(
    event_or_state: Any,
    recommendation: str,
    quality: str | None,
    message: str | None = None,
) -> list[str]:
    config = _config(event_or_state)
    rec = recommendation if recommendation in {"yes", "no"} else "unknown"
    q = quality if quality in {"high-quality", "low-quality"} else "unknown"
    round_bin = _round_bin(_round(event_or_state), _horizon(event_or_state))
    source = _source(event_or_state)
    p = _as_float(config.get("p"), None)
    p_bin = _bin(p, 0.10, 0.0, 1.0) if p is not None else "unknown"
    style = message_style(message)
    return [
        f"rec={rec}|quality={q}|round={round_bin}|p={p_bin}|style={style}|source={source}",
        f"rec={rec}|quality={q}|round={round_bin}|p={p_bin}|style={style}",
        f"rec={rec}|quality={q}|round={round_bin}|p={p_bin}",
        f"rec={rec}|quality={q}|round={round_bin}",
        f"rec={rec}|quality={q}",
        f"rec={rec}",
        "__global__",
    ]


class EmpiricalResponseModel:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.min_support = int(payload.get("min_support", 30) or 30)
        self.families = payload.get("families", {})

    @classmethod
    def load(cls, path: str | Path | None) -> "EmpiricalResponseModel | None":
        if not path:
            return None
        p = Path(path)
        if p.is_dir():
            p = p / "model.json"
        if not p.exists():
            return None
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def estimate(self, family: str, keys: list[str]) -> ResponseEstimate | None:
        family_model = self.families.get(family) or {}
        buckets = family_model.get("buckets") or {}
        for idx, key in enumerate(keys):
            row = buckets.get(key)
            if not row:
                continue
            return ResponseEstimate(
                probability=float(row.get("probability", family_model.get("global_rate", 0.5))),
                support=int(row.get("trials", 0) or 0),
                uncertainty=float(row.get("uncertainty", 0.5)),
                support_quality=float(row.get("support_quality", 0.0)),
                key=key,
                fallback_level=idx,
            )
        global_rate = family_model.get("global_rate")
        if global_rate is None:
            return None
        return ResponseEstimate(
            probability=float(global_rate),
            support=int(family_model.get("global_trials", 0) or 0),
            uncertainty=0.5,
            support_quality=0.0,
            key="implicit_global",
            fallback_level=len(keys),
        )

    def bargaining_acceptance(self, state: Any, responder_role: str, offered_share_to_responder: float) -> ResponseEstimate | None:
        return self.estimate("bargaining", bargaining_keys(state, responder_role, offered_share_to_responder))

    def negotiation_acceptance(self, state: Any, responder_role: str, normalized_price: float) -> ResponseEstimate | None:
        return self.estimate("negotiation", negotiation_keys(state, responder_role, normalized_price))

    def persuasion_buy(
        self,
        state: Any,
        recommendation: str,
        quality: str | None,
        message: str | None = None,
    ) -> ResponseEstimate | None:
        return self.estimate("persuasion", persuasion_keys(state, recommendation, quality, message))
