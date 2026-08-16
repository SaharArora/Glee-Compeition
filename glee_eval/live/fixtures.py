"""Synthetic payloads shaped like the documented live schema.

Built by hand from the glee-sdk 0.0.5 README tables rather than captured from a
real game, because no API key exists yet. They are therefore a statement of what
we *believe* the server sends, and their value is that a mismatch shows up as a
failing test the moment a real payload contradicts them -- see the observation log
in `strategy.py`, which exists to catch exactly that.
"""

from __future__ import annotations

from typing import Any


def bargaining_offer(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-barg-1",
        "game_family": "bargaining",
        "your_player": "player_1",
        "phase": "offer",
        "opponent": {"type": "hidden", "name": None},
        "game_state": {
            "phase": "offer",
            "current_player": "player_1",
            "proposer": "player_1",
            "round": 1,
            "max_rounds": 12,
            "horizon_known": True,
            "money_to_divide": 10000,
            "delta_1": 0.95,
            "delta_2": 0.8,
            "last_offer": None,
            "history": [],
            "messages_allowed": True,
            "complete_information": True,
        },
        "valid_actions": {
            "type": "offer",
            "fields": {
                "alice_gain": "number (must sum with bob_gain to money_to_divide)",
                "bob_gain": "number",
                "message": "string (optional)",
            },
        },
        "prompt": "You are Alice. Make an offer.",
    }
    game["game_state"].update(overrides)
    return game


def bargaining_decision(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-barg-2",
        "game_family": "bargaining",
        "your_player": "player_2",
        "phase": "decision",
        "opponent": {"type": "agent", "name": "someone"},
        "game_state": {
            "phase": "decision",
            "current_player": "player_2",
            "proposer": "player_1",
            "round": 2,
            "max_rounds": 12,
            "horizon_known": True,
            "money_to_divide": 10000,
            "delta_2": 0.9,
            "last_offer": {
                "player_1_gain": 6000,
                "player_2_gain": 4000,
                "message": "Fair split.",
                "proposer": "player_1",
                "round": 2,
            },
            "history": [{"round": 1, "proposer": "player_2",
                         "offer": {"player_1_gain": 5000, "player_2_gain": 5000, "message": "Half?"},
                         "decision": "reject"}],
            "messages_allowed": True,
            "complete_information": False,
        },
        "valid_actions": {
            "type": "decision",
            "fields": {"decision": "'accept', 'reject', or 'walkaway'"},
        },
        "prompt": "Alice offered you 4000.",
    }
    game["game_state"].update(overrides)
    return game


def negotiation_offer(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-nego-1",
        "game_family": "negotiation",
        "your_player": "player_1",
        "phase": "offer",
        "opponent": {"type": "hidden", "name": None},
        "game_state": {
            "phase": "offer",
            "current_player": "player_1",
            "player_1_role": "seller",
            "player_2_role": "buyer",
            "player_1_value": 8000,
            "round": 1,
            "max_rounds": 10,
            "horizon_known": True,
            "last_offer": None,
            "history": [],
            "messages_allowed": True,
            "complete_information": False,
        },
        "valid_actions": {
            "type": "offer",
            "fields": {"product_price": "number", "message": "string (optional)"},
        },
        "prompt": "You are the seller. Name a price.",
    }
    game["game_state"].update(overrides)
    return game


def negotiation_decision(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-nego-2",
        "game_family": "negotiation",
        "your_player": "player_2",
        "phase": "decision",
        "opponent": {"type": "agent", "name": "someone"},
        "game_state": {
            "phase": "decision",
            "current_player": "player_2",
            "player_1_role": "seller",
            "player_2_role": "buyer",
            "player_2_value": 12000,
            "round": 3,
            "max_rounds": 10,
            "horizon_known": True,
            "last_offer": {"price": 11000, "message": "Best I can do.", "from_player": "player_1", "round": 3},
            "history": [{"round": 1,
                         "offer": {"price": 13000, "message": "Opening ask.", "from_player": "player_1"},
                         "decision": "RejectOffer",
                         "counteroffer": {"price": 10000, "message": "My counter.", "from_player": "player_2"},
                         "decided_by": "player_2"}],
            "messages_allowed": True,
            "complete_information": False,
        },
        "valid_actions": {
            "type": "decision",
            "fields": {
                "decision": "'AcceptOffer', 'RejectOffer', or 'WalkAway'",
                "product_price": "number (required if RejectOffer - your counteroffer)",
                "message": "string (optional)",
            },
        },
        "prompt": "The seller asks 11000.",
    }
    game["game_state"].update(overrides)
    return game


def persuasion_seller_recommendation(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-pers-1",
        "game_family": "persuasion",
        "your_player": "player_1",
        "phase": "seller_message",
        "opponent": {"type": "hidden", "name": None},
        "game_state": {
            "phase": "seller_message",
            "current_player": "player_1",
            "product_price": 10000,
            "p": 0.5,
            "v": 12500,
            "u": 0,
            "current_quality": "high",
            "seller_message_type": "binary",
            "round": 3,
            "total_rounds": 20,
            "seller_total_payoff": 20000,
            "buyer_total_payoff": 5000,
            "is_seller_know_cv": True,
            "history": [
                {"round": 1, "seller_message": "yes", "buyer_decision": "yes", "bought": True,
                 "quality": "high", "seller_payoff": 10000, "buyer_payoff": 2500},
                {"round": 2, "seller_message": "no", "buyer_decision": "no", "bought": False,
                 "quality": None, "seller_payoff": 0, "buyer_payoff": 0},
            ],
        },
        "valid_actions": {"type": "seller_recommendation", "fields": {"decision": "'yes' or 'no'"}},
        "prompt": "This round's product is high quality.",
    }
    game["game_state"].update(overrides)
    return game


def persuasion_seller_message(**overrides: Any) -> dict[str, Any]:
    game = persuasion_seller_recommendation(seller_message_type="text", current_quality="low")
    game["game_id"] = "g-pers-2"
    game["valid_actions"] = {"type": "seller_message", "fields": {"message": "string"}}
    game["game_state"].update(overrides)
    return game


def persuasion_buyer_decision(**overrides: Any) -> dict[str, Any]:
    game = {
        "game_id": "g-pers-3",
        "game_family": "persuasion",
        "your_player": "player_2",
        "phase": "buyer_decision",
        "opponent": {"type": "agent", "name": "someone"},
        "game_state": {
            "phase": "buyer_decision",
            "current_player": "player_2",
            "product_price": 10000,
            "p": 0.5,
            "v": 12500,
            "u": 0,
            "seller_message": "yes",
            "seller_message_type": "binary",
            "round": 3,
            "total_rounds": 20,
            "seller_total_payoff": 20000,
            "buyer_total_payoff": 5000,
            "is_seller_know_cv": True,
            "history": [
                {"round": 1, "seller_message": "yes", "buyer_decision": "yes", "bought": True,
                 "quality": "high", "seller_payoff": 10000, "buyer_payoff": 2500},
                {"round": 2, "seller_message": "no", "buyer_decision": "no", "bought": False,
                 "quality": None, "seller_payoff": 0, "buyer_payoff": 0},
            ],
        },
        "valid_actions": {"type": "buyer_decision", "fields": {"decision": "'yes' or 'no'"}},
        "prompt": "The seller recommends buying.",
    }
    game["game_state"].update(overrides)
    return game


def sample_games() -> list[dict[str, Any]]:
    """One payload per documented phase of every family."""

    return [
        bargaining_offer(),
        bargaining_decision(),
        negotiation_offer(),
        negotiation_decision(),
        persuasion_seller_recommendation(),
        persuasion_seller_message(),
        persuasion_buyer_decision(),
    ]
