from __future__ import annotations

import json
from typing import Any


CONFIG_FIELDS: dict[str, tuple[str, ...]] = {
    "bargaining": ("money_to_divide", "max_rounds", "complete_information", "messages_allowed", "delta_1", "delta_2"),
    "negotiation": ("seller_value", "buyer_value", "product_price_order", "max_rounds", "complete_information", "messages_allowed"),
    "persuasion": ("p", "v", "c", "product_price", "total_rounds", "is_seller_know_cv", "is_buyer_know_p", "seller_message_type", "is_myopic", "allow_buyer_message"),
}

CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "bargaining": {"messages_allowed": False, "complete_information": True},
    "negotiation": {"messages_allowed": False, "complete_information": True},
    "persuasion": {"is_seller_know_cv": True, "is_buyer_know_p": True, "seller_message_type": "text", "allow_buyer_message": False, "is_myopic": False, "total_rounds": 20, "v": 0},
}


def canonical_config(family: str, config: dict[str, Any]) -> dict[str, Any]:
    fields = CONFIG_FIELDS.get(family, ())
    defaults = CONFIG_DEFAULTS.get(family, {})
    return {field: config.get(field, defaults.get(field)) for field in fields}


def canonical_config_key(family: str, config: dict[str, Any]) -> str:
    return json.dumps(canonical_config(family, config), sort_keys=True, separators=(",", ":"), default=str)
