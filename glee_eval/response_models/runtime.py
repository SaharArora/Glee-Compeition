from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Both ways the estimator can end up reporting a family-wide rate rather than a
# real bucket: "__global__" when that literal bucket exists in the table, and this
# when it falls through to `global_rate`. Callers rejecting one must reject both --
# the agent guarded only on "__global__" and so never caught the fall-through path.
GLOBAL_FALLBACK_KEY = "implicit_global"
GLOBAL_KEYS = frozenset({"__global__", GLOBAL_FALLBACK_KEY})


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

    @property
    def is_global_fallback(self) -> bool:
        """True when this is a family-wide rate rather than a real bucket estimate."""

        return self.key in GLOBAL_KEYS

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": self.probability,
            "is_global_fallback": self.is_global_fallback,
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


def _remaining_bin(round_number: int, horizon: int | None) -> str:
    """How much game is left. Retained, but OFF by default -- it did not help.

    The hypothesis was sound and the marginal statistics confirmed it: on real
    negotiation decisions, acceptance roughly triples between the early game and
    the final round at the *same* responder gain.

        gain      early    final
        zero      0.240    0.468
        small     0.225    0.699
        large     0.327    0.912

    So the pooled p=0.34-at-zero-gain figure really is a blend of 0.24 and 0.47.
    But that turned out to be a true statement about a bucket the model rarely
    uses, not a diagnosis of the model. The specific key levels already carry
    `round_bin`, whose "late" bucket captures most of this wherever there is enough
    data to reach them; the pooled level only takes over when there is not.

    Adding the conditioning therefore changed nothing worth having. On 41,601
    held-out real decisions from LLM families never seen in training:

        variant                       log loss    Brier      ECE
        pooled                         0.29400   0.08334   0.02640
        conditioned on remaining       0.29426   0.08349   0.02608

    and the paired payoff A/B on holdout failed the gate outright (+0.0002,
    t=0.81). Kept behind `include_remaining` so the experiment is one flag from
    being rerun if the key ladder changes, rather than deleted and rediscovered.
    """

    if not horizon or horizon <= 0:
        return "unknown"
    remaining = int(horizon) - int(round_number)
    if remaining <= 0:
        return "final"
    if remaining == 1:
        return "penultimate"
    if remaining <= 4:
        return "mid"
    return "early"


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


def negotiation_keys(
    event_or_state: Any,
    responder_role: str,
    normalized_price: float,
    responder_value: float | None = None,
    include_remaining: bool = False,
) -> list[str]:
    """Bucket keys for "will this responder accept this price?".

    Keyed primarily on the responder's own gain at that price -- `price -
    seller_value` for a seller, `buyer_value - price` for a buyer -- rather than on
    the absolute normalized price.

    Absolute price is confounded. It is denominated in value units, so it
    correlates with `buyer_value`, and high-`buyer_value` configs both permit
    higher prices and leave more room to accept. Keyed that way the table
    estimated P(accept | price observed) rather than P(accept | price we set), and
    the fitted acceptance probability *rose* with price across the whole working
    range (0.008 at 0.60-0.65 up to 0.228 at 1.05-1.10). Since the agent maximizes
    payoff * probability, a rising curve pushed the argmax straight to the ceiling:
    it asked for a median 100% of the available surplus and lost 0.040 payoff per
    game against the rule-based policy.

    The responder's gain is a difference, so it blocks that confound. It is not
    always observable -- as a seller under incomplete information we do not know
    the buyer's value -- so the absolute-price keys are retained as lower-priority
    fallbacks and the agent may pass its current belief as `responder_value`.
    """

    config = _config(event_or_state)
    price_bin = _bin(_clip(normalized_price, 0.0, 2.0), 0.05, 0.0, 1.5)
    round_bin = _round_bin(_round(event_or_state), _horizon(event_or_state))
    source = _source(event_or_state)
    seller_value = _as_float(config.get("seller_value"), None)
    buyer_value = _as_float(config.get("buyer_value"), None)
    surplus = None if seller_value is None or buyer_value is None else max(0.0, buyer_value - seller_value)
    surplus_bin = _bin(surplus, 0.10, 0.0, 1.0) if surplus is not None else "unknown"

    if responder_value is None:
        responder_value = seller_value if responder_role == "seller" else buyer_value
    gain = None
    if responder_value is not None:
        gain = normalized_price - responder_value if responder_role == "seller" else responder_value - normalized_price

    remaining_bin = _remaining_bin(_round(event_or_state), _horizon(event_or_state))

    keys: list[str] = []
    if gain is not None:
        # Symmetric around zero: negative gain means the price is worse than the
        # responder's own value, which is the decisive region.
        gain_bin = _bin(_clip(gain, -1.0, 1.0), 0.05, -1.0, 1.0)
        keys += [
            f"role={responder_role}|round={round_bin}|gain={gain_bin}|surplus={surplus_bin}|source={source}",
            f"role={responder_role}|round={round_bin}|gain={gain_bin}|surplus={surplus_bin}",
        ]
        if include_remaining:
            keys += [
                f"role={responder_role}|rem={remaining_bin}|gain={gain_bin}|surplus={surplus_bin}",
                f"role={responder_role}|rem={remaining_bin}|gain={gain_bin}",
            ]
        keys.append(f"role={responder_role}|gain={gain_bin}")
        if include_remaining:
            # Remaining rounds is kept in the pooled fallback too. Dropping it here
            # is what produced the blended estimate in the first place.
            keys.append(f"rem={remaining_bin}|gain={gain_bin}")
        keys.append(f"gain={gain_bin}")
    keys += [
        f"role={responder_role}|round={round_bin}|price={price_bin}|surplus={surplus_bin}|source={source}",
        f"role={responder_role}|round={round_bin}|price={price_bin}|surplus={surplus_bin}",
        f"role={responder_role}|round={round_bin}|price={price_bin}",
        f"role={responder_role}|price={price_bin}",
        f"price={price_bin}",
        "__global__",
    ]
    return keys


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
            key=GLOBAL_FALLBACK_KEY,
            fallback_level=len(keys),
        )

    def bargaining_acceptance(self, state: Any, responder_role: str, offered_share_to_responder: float) -> ResponseEstimate | None:
        return self.estimate("bargaining", bargaining_keys(state, responder_role, offered_share_to_responder))

    def negotiation_acceptance(
        self,
        state: Any,
        responder_role: str,
        normalized_price: float,
        responder_value: float | None = None,
    ) -> ResponseEstimate | None:
        return self.estimate("negotiation", negotiation_keys(state, responder_role, normalized_price, responder_value))

    def persuasion_buy(
        self,
        state: Any,
        recommendation: str,
        quality: str | None,
        message: str | None = None,
    ) -> ResponseEstimate | None:
        return self.estimate("persuasion", persuasion_keys(state, recommendation, quality, message))
