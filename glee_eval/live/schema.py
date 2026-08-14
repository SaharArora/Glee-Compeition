"""Translate between the live GLEE competition schema and our internal one.

The live API and our offline dataset describe the same three games with different
names and units. Every one of these differences is a place where a silent
mistranslation costs real rating, and we have already been bitten twice by exactly
this class of bug offline (`raw.round_quality` vs `quality`, which made the agent
decline all 66,480 real buyer decisions). So the mapping is written out explicitly
rather than inferred:

    concept                     offline                    live
    bargaining offer            self_gain / other_gain     alice_gain / bob_gain
    bargaining history          transcript rows            game_state["last_offer"]
    bargaining exit             (none)                     decision "walkaway"
    bargaining horizon          max_rounds always present  absent when unbounded,
                                                           flagged by horizon_known
    negotiation role            role                       player_N_role
    negotiation values          seller_value / buyer_value player_N_value
    negotiation price           normalised by
                                product_price_order        absolute, no order
    negotiation exit            SellToJhon / BuyFromJhon   WalkAway
    negotiation rejection       bare decision              REQUIRES a counteroffer
    persuasion low value        c                          u
    persuasion quality          "high-quality"/"low-..."   "high"/"low"

Scale matters as much as naming. Live negotiation prices are absolute (they can be
in the tens of thousands) while the agent's rules are tuned in units where a
valuation is near 1.0 -- constants like "concede 0.04" are meaningless against a
price of 12,500. Everything is therefore normalised by the player's own valuation
on the way in and multiplied back on the way out.
"""

from __future__ import annotations

import math
from typing import Any

from glee_eval.data.schemas import GameState

# The server rejects a longer message as an *invalid move*, which burns one of a
# small number of attempts rather than being truncated for us.
MAX_MESSAGE_LEN = 2000

FAMILIES = ("bargaining", "negotiation", "persuasion")


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return default if (isinstance(value, float) and math.isnan(value)) else float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clamp_message(message: Any) -> str | None:
    """Trim to the server's cap. Never returns an over-length string."""

    if message is None:
        return None
    text = str(message)
    return text[:MAX_MESSAGE_LEN] if len(text) > MAX_MESSAGE_LEN else text


def action_type_of(game: dict[str, Any]) -> str:
    return str(_as_dict(game.get("valid_actions")).get("type") or "")


def _player_index(name: str) -> str:
    """"player_1" -> "1". Live player keys are player_1 / player_2."""

    return name.rsplit("_", 1)[-1] if name else ""


def _bargaining_state(game: dict[str, Any]) -> GameState:
    state = _as_dict(game.get("game_state"))
    me = str(state.get("current_player") or game.get("your_player") or "player_1")
    money = _num(state.get("money_to_divide"), 100.0) or 100.0

    # An unbounded game has no max_rounds at all. Feeding the agent a horizon of 0
    # would make every round look like the last one and collapse its accept floor,
    # so an explicit long horizon stands in for "no deadline".
    horizon_known = state.get("horizon_known")
    max_rounds = _num(state.get("max_rounds"))
    if max_rounds is None or horizon_known is False:
        horizon = 99
    else:
        horizon = int(max_rounds)

    config: dict[str, Any] = {
        "money_to_divide": money,
        "max_rounds": horizon,
        "complete_information": bool(state.get("complete_information")),
        "messages_allowed": bool(state.get("messages_allowed")),
    }
    private: dict[str, Any] = {}
    # delta_1/delta_2 are Alice/Bob; the opponent's is absent under incomplete
    # information. Accept the http_player spelling too, which uses delta_player_N.
    for index in ("1", "2"):
        value = _num(state.get(f"delta_{index}"), _num(state.get(f"delta_player_{index}")))
        if value is not None:
            config[f"delta_{index}"] = value
            private[f"delta_{index}"] = value

    last_offer = _as_dict(state.get("last_offer"))
    transcript: list[dict[str, Any]] = []
    if last_offer:
        proposer = str(last_offer.get("proposer") or "")
        p1 = _num(last_offer.get("player_1_gain"), 0.0) or 0.0
        p2 = _num(last_offer.get("player_2_gain"), 0.0) or 0.0
        proposer_gain, other_gain = (p1, p2) if proposer == "player_1" else (p2, p1)
        transcript.append(
            {
                "round": int(_num(last_offer.get("round"), state.get("round")) or 1),
                "role": proposer or ("player_1" if me == "player_2" else "player_2"),
                "action_type": "offer",
                "numeric_action": proposer_gain,
                "self_gain": proposer_gain,
                "other_gain": other_gain,
                "structured": {"self_gain": proposer_gain, "other_gain": other_gain},
                "free_text_message": last_offer.get("message"),
            }
        )

    return GameState(
        scenario_id=str(game.get("game_id") or "live"),
        game_id=str(game.get("game_id") or "live"),
        game_family="bargaining",
        role=me,
        round=int(_num(state.get("round"), 1) or 1),
        horizon=horizon,
        public_parameters=config,
        private_parameters=private,
        visible_transcript=transcript,
        valid_action_schema={"kind": "offer" if action_type_of(game) == "offer" else "decision"},
        metadata={"live": True, "horizon_known": horizon_known},
    )


def negotiation_scale(game: dict[str, Any]) -> float:
    """Divisor that puts live absolute prices onto the agent's ~1.0 scale.

    The player's own valuation is always visible, so it is the one quantity
    guaranteed to be available for this. Falls back to the last offered price, then
    to 1.0.
    """

    state = _as_dict(game.get("game_state"))
    me = str(state.get("current_player") or game.get("your_player") or "player_1")
    own = _num(state.get(f"{me}_value"))
    if own and own > 0:
        return float(own)
    price = _num(_as_dict(state.get("last_offer")).get("price"))
    if price and price > 0:
        return float(price)
    price = _num(state.get("product_price"))
    return float(price) if price and price > 0 else 1.0


def _negotiation_state(game: dict[str, Any]) -> GameState:
    state = _as_dict(game.get("game_state"))
    me = str(state.get("current_player") or game.get("your_player") or "player_1")
    other = "player_2" if me == "player_1" else "player_1"
    role = str(state.get(f"{me}_role") or ("seller" if me == "player_1" else "buyer"))
    other_role = "buyer" if role == "seller" else "seller"
    scale = negotiation_scale(game)

    horizon_known = state.get("horizon_known")
    max_rounds = _num(state.get("max_rounds"))
    horizon = 99 if (max_rounds is None or horizon_known is False) else int(max_rounds)

    config: dict[str, Any] = {
        # Prices are handed to the agent already normalised, so the order is 1.
        "product_price_order": 1.0,
        "max_rounds": horizon,
        "complete_information": bool(state.get("complete_information")),
        "messages_allowed": bool(state.get("messages_allowed")),
    }
    private: dict[str, Any] = {}
    own_value = _num(state.get(f"{me}_value"))
    if own_value is not None:
        private[f"{role}_value"] = own_value / scale
    other_value = _num(state.get(f"{other}_value"))
    if other_value is not None:
        # Only present under complete information; leaving it absent is what tells
        # the agent to fall back to its empirical prior.
        private[f"{other_role}_value"] = other_value / scale
        config[f"{other_role}_value"] = other_value / scale
        config[f"{role}_value"] = own_value / scale if own_value is not None else None

    last_offer = _as_dict(state.get("last_offer"))
    transcript: list[dict[str, Any]] = []
    if last_offer:
        price = _num(last_offer.get("price"))
        from_player = str(last_offer.get("from_player") or other)
        from_role = str(state.get(f"{from_player}_role") or other_role)
        if price is not None:
            transcript.append(
                {
                    "round": int(_num(last_offer.get("round"), state.get("round")) or 1),
                    "role": from_role,
                    "action_type": "offer",
                    "numeric_action": price / scale,
                    "structured": {"product_price": price / scale},
                    "free_text_message": last_offer.get("message"),
                }
            )

    return GameState(
        scenario_id=str(game.get("game_id") or "live"),
        game_id=str(game.get("game_id") or "live"),
        game_family="negotiation",
        role=role,
        round=int(_num(state.get("round"), 1) or 1),
        horizon=horizon,
        public_parameters={k: v for k, v in config.items() if v is not None},
        private_parameters=private,
        visible_transcript=transcript,
        valid_action_schema={"kind": "offer" if action_type_of(game) == "offer" else "decision"},
        metadata={"live": True, "negotiation_scale": scale, "horizon_known": horizon_known},
    )


def _persuasion_market_statistics(
    state: dict[str, Any],
    price: float,
    high: float | None,
    low: float | None,
) -> dict[str, Any] | None:
    """Recover the buyer's own purchase history from the running payoff totals.

    The live payload carries no per-round history -- only `seller_total_payoff` and
    `buyer_total_payoff`. Without this the buyer's belief update has nothing to
    read, so its posterior stays pinned at the prior for the whole game and it can
    never adapt to *this* seller. That is worse than any fixed estimate, because a
    truthful seller and a liar are indistinguishable to it.

    Persuasion is one buyer across all rounds and the seller is paid the price on
    every sale, so both counts are exactly recoverable:

        sold = seller_total / price
        buyer_total = h * (v - price) + (sold - h) * (u - price)
        =>  h = (buyer_total - sold * (u - price)) / (v - u)

    Returns None rather than guessing when the algebra is not determined -- no
    price, no distinct v/u, or nothing sold yet.
    """

    # Guard on the *raw* price, not the caller's coerced one. `_persuasion_state`
    # resolves price with `or 1.0`, so a zero or missing price arrives here as 1.0
    # and every guard on it silently passes -- which produced a products_sold of
    # 40000 from a 40000 payoff total.
    raw_price = _num(state.get("product_price"))
    if raw_price is None or raw_price <= 0 or price <= 0 or high is None or low is None or high == low:
        return None
    seller_total = _num(state.get("seller_total_payoff"))
    buyer_total = _num(state.get("buyer_total_payoff"))
    if seller_total is None or buyer_total is None:
        return None

    sold = int(round(seller_total / raw_price))
    # A buyer cannot have bought more units than the game has rounds. Anything
    # beyond that means the totals and the price disagree, so report nothing rather
    # than a fabricated history. Deliberately bounded by total_rounds and not by
    # rounds elapsed: the round field is the *current* round and off-by-one
    # reasoning there would reject legitimate histories.
    total_rounds = int(_num(state.get("total_rounds"), 0) or 0)
    if total_rounds and sold > total_rounds:
        return None
    if sold <= 0:
        # Nothing bought yet, so there is genuinely nothing to report. Emitting a
        # zero row would be honest but useless; omitting it keeps the agent on its
        # prior, which is the correct belief with no observations.
        return None
    high_quality = (buyer_total - sold * (low - price)) / (high - low)
    high_quality = int(round(min(max(high_quality, 0.0), float(sold))))
    return {
        "round": int(_num(state.get("round"), 1) or 1),
        "role": "market",
        "action_type": "market_statistics",
        "products_sold": sold,
        "high_quality_sold": high_quality,
        "derived_from": "seller_total_payoff and buyer_total_payoff",
    }


def _persuasion_state(game: dict[str, Any]) -> GameState:
    state = _as_dict(game.get("game_state"))
    action_type = action_type_of(game)
    role = "buyer" if action_type == "buyer_decision" else "seller"
    price = _num(state.get("product_price"), 1.0) or 1.0

    # Live `v` and `u` are absolute currency values for a high / low unit; the
    # agent works in multiples of the price, which is also how the offline `v`/`c`
    # config fields are expressed.
    high = _num(state.get("v"))
    low = _num(state.get("u"))
    config: dict[str, Any] = {
        "product_price": price,
        "p": _num(state.get("p"), 0.5),
        "total_rounds": int(_num(state.get("total_rounds"), 20) or 20),
        "seller_message_type": str(state.get("seller_message_type") or "binary"),
        "is_seller_know_cv": bool(state.get("is_seller_know_cv", True)),
        # The live buyer always remembers the whole interaction, so there is no
        # myopic reset to model here -- unlike the offline dataset.
        "is_myopic": False,
    }
    if high is not None:
        config["v"] = high / price if price else high
    if low is not None:
        config["c"] = low / price if price else low

    metadata: dict[str, Any] = {"live": True}
    quality = state.get("current_quality")
    if quality is not None:
        # Seller-only, and spelled "high"/"low" rather than "high-quality".
        metadata["quality"] = "high-quality" if str(quality).startswith("high") else "low-quality"

    transcript: list[dict[str, Any]] = []
    if role == "buyer":
        stats = _persuasion_market_statistics(state, price, high, low)
        if stats is not None:
            transcript.append(stats)

    seller_message = state.get("seller_message")
    if seller_message is not None and role == "buyer":
        decision = None
        text = str(seller_message).strip().lower()
        if config["seller_message_type"] == "binary" or text in {"yes", "no"}:
            decision = "yes" if text.startswith("y") else "no" if text.startswith("n") else None
        transcript.append(
            {
                "round": int(_num(state.get("round"), 1) or 1),
                "role": "seller",
                "action_type": "recommendation" if decision else "message",
                "buy_no_buy": decision,
                "structured": {"decision": decision} if decision else {},
                "free_text_message": str(seller_message),
            }
        )

    return GameState(
        scenario_id=str(game.get("game_id") or "live"),
        game_id=str(game.get("game_id") or "live"),
        game_family="persuasion",
        role=role,
        round=int(_num(state.get("round"), 1) or 1),
        horizon=int(config["total_rounds"]),
        public_parameters=config,
        private_parameters={},
        visible_transcript=transcript,
        valid_action_schema={
            "kind": "buy_decision" if role == "buyer" else "recommendation",
            "seller_message_type": config["seller_message_type"],
        },
        metadata=metadata,
    )


def to_game_state(game: dict[str, Any]) -> GameState:
    """Live game dict -> the GameState the agent reasons over."""

    family = str(game.get("game_family") or "")
    if family == "bargaining":
        return _bargaining_state(game)
    if family == "negotiation":
        return _negotiation_state(game)
    if family == "persuasion":
        return _persuasion_state(game)
    raise ValueError(f"Unsupported live game family: {family!r}")


# ----------------------------------------------------------------------------
# Actions back out
# ----------------------------------------------------------------------------


def _bargaining_action(game: dict[str, Any], action: Any) -> dict[str, Any]:
    state = _as_dict(game.get("game_state"))
    money = _num(state.get("money_to_divide"), 100.0) or 100.0
    me = str(state.get("current_player") or game.get("your_player") or "player_1")
    structured = _as_dict(getattr(action, "structured", None))

    if action_type_of(game) == "offer":
        self_gain = _num(structured.get("self_gain"), _num(getattr(action, "numeric_action", None)))
        if self_gain is None:
            self_gain = money / 2.0
        self_gain = max(0.0, min(money, float(self_gain)))
        # The two gains must sum to exactly money_to_divide, so the counterpart's
        # share is derived by subtraction rather than rounded independently.
        self_gain = round(self_gain, 2)
        other_gain = round(money - self_gain, 10)
        alice, bob = (self_gain, other_gain) if me == "player_1" else (other_gain, self_gain)
        payload: dict[str, Any] = {"alice_gain": alice, "bob_gain": bob}
        message = clamp_message(structured.get("message") or getattr(action, "message", None))
        if message and state.get("messages_allowed"):
            payload["message"] = message
        return payload

    decision = str(getattr(action, "accept_reject", None) or structured.get("decision") or "reject").lower()
    return {"decision": "accept" if decision.startswith("acc") else "reject"}


def _negotiation_action(game: dict[str, Any], action: Any) -> dict[str, Any]:
    state = _as_dict(game.get("game_state"))
    scale = negotiation_scale(game)
    structured = _as_dict(getattr(action, "structured", None))
    message = clamp_message(structured.get("message") or getattr(action, "message", None))

    def _price_payload(normalized: float | None, fallback: float) -> float:
        value = normalized if normalized is not None else fallback
        return round(float(value) * scale, 2)

    if action_type_of(game) == "offer":
        normalized = _num(structured.get("product_price"), _num(getattr(action, "numeric_action", None)))
        if normalized is not None and scale:
            # The agent already works in normalised units; numeric_action is the
            # normalised price multiplied by our synthetic order of 1.0.
            normalized = float(normalized)
        payload: dict[str, Any] = {"product_price": _price_payload(normalized, 1.0)}
        if message and state.get("messages_allowed"):
            payload["message"] = message
        return payload

    decision = str(getattr(action, "accept_reject", None) or structured.get("decision") or "RejectOffer")
    if decision == "AcceptOffer":
        return {"decision": "AcceptOffer"}
    if decision in {"SellToJhon", "BuyFromJhon", "WalkAway", "DealWithJhon"}:
        # Offline names the outside option per role; live has a single WalkAway.
        return {"decision": "WalkAway"}

    # A rejection must carry a counteroffer, except on the final round of a capped
    # game where the server takes none. Sending RejectOffer without one is an
    # invalid move, which burns a limited attempt.
    payload = {"decision": "RejectOffer"}
    max_rounds = _num(state.get("max_rounds"))
    round_number = _num(state.get("round"), 1) or 1
    final_round = max_rounds is not None and round_number >= max_rounds
    if not final_round:
        counter = _num(structured.get("counter_price"), _num(structured.get("product_price")))
        if counter is None:
            me = str(state.get("current_player") or game.get("your_player") or "player_1")
            role = str(state.get(f"{me}_role") or "seller")
            own = _num(state.get(f"{me}_value"), scale) or scale
            # Ask above our own value as a seller, below it as a buyer.
            counter_absolute = own * (1.15 if role == "seller" else 0.85)
            payload["product_price"] = round(counter_absolute, 2)
        else:
            payload["product_price"] = _price_payload(float(counter), 1.0)
    if message and state.get("messages_allowed"):
        payload["message"] = message
    return payload


def _persuasion_action(game: dict[str, Any], action: Any) -> dict[str, Any]:
    structured = _as_dict(getattr(action, "structured", None))
    decision = str(getattr(action, "buy_no_buy", None) or structured.get("decision") or "no").lower()
    yes = decision.startswith("y")

    if action_type_of(game) == "seller_message":
        message = clamp_message(structured.get("message") or getattr(action, "message", None))
        if not message:
            message = "I recommend buying this product." if yes else "I recommend passing on this product."
        return {"message": message}
    return {"decision": "yes" if yes else "no"}


def to_live_action(game: dict[str, Any], action: Any) -> dict[str, Any]:
    """Our AgentAction -> the action dict the live API expects."""

    family = str(game.get("game_family") or "")
    if family == "bargaining":
        return _bargaining_action(game, action)
    if family == "negotiation":
        return _negotiation_action(game, action)
    if family == "persuasion":
        return _persuasion_action(game, action)
    raise ValueError(f"Unsupported live game family: {family!r}")


def fallback_action(game: dict[str, Any]) -> dict[str, Any]:
    """A legal, conservative move for when anything at all has gone wrong.

    Submitting *something* legal always beats raising: the SDK swallows a strategy
    exception without submitting, which becomes a turn timeout and is scored at the
    5th percentile. These choices are deliberately passive rather than good.
    """

    family = str(game.get("game_family") or "")
    action_type = action_type_of(game)
    state = _as_dict(game.get("game_state"))

    if family == "bargaining":
        if action_type == "offer":
            money = _num(state.get("money_to_divide"), 100.0) or 100.0
            half = round(money / 2.0, 2)
            return {"alice_gain": half, "bob_gain": round(money - half, 10)}
        return {"decision": "reject"}

    if family == "negotiation":
        if action_type == "offer":
            me = str(state.get("current_player") or game.get("your_player") or "player_1")
            own = _num(state.get(f"{me}_value"), 1.0) or 1.0
            role = str(state.get(f"{me}_role") or "seller")
            return {"product_price": round(own * (1.1 if role == "seller" else 0.9), 2)}
        # WalkAway is worth zero, which is never worse than a trade we failed to
        # reason about, and unlike RejectOffer it needs no counteroffer to be legal.
        return {"decision": "WalkAway"}

    if family == "persuasion":
        if action_type == "seller_message":
            return {"message": "I recommend buying this product."}
        if action_type == "seller_recommendation":
            return {"decision": "yes"}
        return {"decision": "no"}

    return {"decision": "no"}
