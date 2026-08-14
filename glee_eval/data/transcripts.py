"""Single source of truth for reading a running transcript off an ingested event.

These accessors were previously private to `response_models/train.py`. They are
fiddly -- transcript items carry their payload under `raw`, `raw_record` or
`structured` depending on family, and bargaining gains are keyed by player public
name -- and getting them subtly wrong yields empty extractions rather than errors.
Anything that needs to read a transcript should import from here rather than
re-deriving the access pattern.
"""

from __future__ import annotations

import json
from typing import Any

from glee_eval.data.ingest import as_float


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def slug_player(player: str | None) -> str:
    return str(player or "").strip().lower().replace(" ", "_")


def transcript_items(event: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = event.get("transcript_so_far") or []
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except json.JSONDecodeError:
            return []
    return [item for item in transcript if isinstance(item, dict)]


def last_transcript_action(event: dict[str, Any], action_type: str) -> dict[str, Any] | None:
    for item in reversed(transcript_items(event)):
        if item.get("action_type") == action_type:
            return item
    return None


def same_round_transcript_item(
    event: dict[str, Any],
    *,
    role: str | None = None,
    action_type: str | None = None,
) -> dict[str, Any] | None:
    round_number = int(as_float(event.get("round")) or 0)
    for item in reversed(transcript_items(event)):
        if int(as_float(item.get("round")) or 0) != round_number:
            continue
        if role is not None and item.get("role") != role:
            continue
        if action_type is not None and item.get("action_type") != action_type:
            continue
        return item
    return None


def bargaining_share_to_responder(offer: dict[str, Any], responder_role: str, money: float) -> float | None:
    """Fraction of the pot an offer leaves to `responder_role`."""

    if not offer or money <= 0:
        return None
    raw = as_dict(offer.get("raw") or offer.get("raw_record"))

    if offer.get("role") == responder_role and offer.get("self_gain") is not None:
        value = as_float(offer.get("self_gain"))
        return None if value is None else value / money
    if offer.get("role") != responder_role and offer.get("other_gain") is not None:
        value = as_float(offer.get("other_gain"))
        return None if value is None else value / money

    gain_keys = [key for key in raw if key.endswith("_gain") and as_float(raw.get(key)) is not None]
    if not gain_keys:
        return None
    proposer_key = f"{slug_player(raw.get('player') or offer.get('player'))}_gain"
    if offer.get("role") == responder_role and proposer_key in gain_keys:
        key = proposer_key
    else:
        key = next((candidate for candidate in gain_keys if candidate != proposer_key), None)
    if key is None:
        role_key = "alice_gain" if responder_role in {"player_1", "seller"} else "bob_gain"
        key = role_key if role_key in gain_keys else gain_keys[0]
    value = as_float(raw.get(key))
    return None if value is None else value / money


def bargaining_offer_self_share(event: dict[str, Any]) -> float | None:
    if event.get("game_family") != "bargaining" or event.get("action_type") != "offer":
        return None
    config = as_dict(event.get("configuration") or event.get("public_parameters"))
    money = as_float(config.get("money_to_divide")) or 100.0
    numeric = as_float(event.get("numeric_action"))
    if numeric is None or money <= 0:
        return None
    return numeric / money


def negotiation_normalized_price(event: dict[str, Any]) -> float | None:
    if event.get("game_family") != "negotiation" or event.get("action_type") != "offer":
        return None
    config = as_dict(event.get("configuration") or event.get("public_parameters"))
    order = as_float(config.get("product_price_order")) or 1_000_000.0
    price = as_float(event.get("numeric_action"))
    if price is None or order <= 0:
        return None
    return price / order


def persuasion_round_quality(event: dict[str, Any]) -> str | None:
    """Quality nature drew this round, as recorded on the transcript.

    Requires both `role="nature"` and the `nature_quality` action type, and the
    label lives under `quality` or `raw.round_quality`.
    """

    nature = same_round_transcript_item(event, role="nature", action_type="nature_quality")
    if not nature:
        return None
    raw = as_dict(nature.get("raw") or nature.get("raw_record"))
    quality = nature.get("quality") or raw.get("round_quality")
    return str(quality) if quality else None


def transcript_item_quality(item: dict[str, Any] | None) -> str | None:
    """Quality label on a transcript row, whichever shape it is in.

    Synthetic rows carry `quality` directly; ingested real rows carry it under
    `raw.round_quality`. Reading only the first silently yields None on every real
    transcript, which is not an error anyone notices -- it just makes a belief
    update learn nothing.
    """

    if not item:
        return None
    raw = as_dict(item.get("raw") or item.get("raw_record"))
    value = item.get("quality") or raw.get("round_quality")
    return str(value) if value else None


def transcript_item_decision(item: dict[str, Any] | None) -> str | None:
    """Yes/no decision on a transcript row, across synthetic and ingested shapes."""

    if not item:
        return None
    raw = as_dict(item.get("raw") or item.get("raw_record"))
    structured = as_dict(item.get("structured"))
    value = item.get("buy_no_buy") or structured.get("decision") or raw.get("decision")
    return str(value) if value else None


def persuasion_recommendation(seller_item: dict[str, Any] | None) -> str | None:
    if not seller_item:
        return None
    raw = as_dict(seller_item.get("raw") or seller_item.get("raw_record") or seller_item.get("structured"))
    value = seller_item.get("buy_no_buy") or raw.get("decision") or raw.get("recommendation")
    return str(value) if value else None
