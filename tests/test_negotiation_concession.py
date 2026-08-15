"""Negotiation counteroffers: who prices them, and whether they ever move.

Live game 9cf35978 ran 99 rounds against a seller and closed nothing. The buyer
sent an identical counteroffer of 6800.0 at rounds 1, 50, 97 and 98. Three
separate defects stacked to produce that, and each gets its own test here.
"""

from __future__ import annotations

import unittest

from glee_eval.live import fixtures
from glee_eval.live.schema import to_game_state, to_live_action
from glee_eval.live.strategy import LiveStrategy
from my_agents.jordan_strategic import MyAgent


def _buyer_game(round: int, *, max_rounds: int = 99, ask: float = 20000.0, own: float = 8000.0) -> dict:
    """A buyer facing a seller asking far above the buyer's own value."""

    game = fixtures.negotiation_decision(round=round, max_rounds=max_rounds, complete_information=False)
    game["game_state"].pop("player_1_value", None)  # seller value stays private
    game["game_state"]["player_2_value"] = own
    game["game_state"]["last_offer"] = {
        "price": ask,
        "message": None,
        "from_player": "player_1",
        "round": round,
    }
    return game


def _counter_prices(agent: MyAgent, rounds: tuple[int, ...]) -> list[float | None]:
    strategy = LiveStrategy(agent, observation_log=None)
    return [strategy(_buyer_game(r)).get("product_price") for r in rounds]


def _fixed(**kwargs) -> MyAgent:
    """An agent with all three rejected negotiation flags forced on.

    All three default to off because the promotion gate rejected them on
    `minimum_effect`. These tests describe what the flags do when enabled, so they
    must set them explicitly rather than inherit a default that says otherwise.
    """

    kwargs.setdefault("use_time_concession", True)
    kwargs.setdefault("guarantee_own_margin", True)
    kwargs.setdefault("debias_counterpart_value", True)
    return MyAgent(seed=1, **kwargs)


class CounterofferIsAgentPricedTests(unittest.TestCase):
    def test_agent_attaches_a_counter_price_when_it_rejects(self):
        """The adapter must not have to invent the counteroffer.

        A live rejection is only legal with a counteroffer attached. The agent
        previously returned a bare decision, so `_negotiation_action` fell through
        to its own last-resort guess on every single live rejection.
        """

        agent = _fixed()
        state = to_game_state(_buyer_game(round=5))
        structured = agent.decide(state).structured

        self.assertEqual(structured["decision"], "RejectOffer")
        self.assertIn("counter_price", structured)
        self.assertIn("counter_normalized_price", structured)

    def test_accepting_carries_no_counteroffer(self):
        """AcceptOffer and the outside option must not smuggle a price in."""

        agent = _fixed()
        # Seller asks below the buyer's value, so accepting is profitable.
        state = to_game_state(_buyer_game(round=98, ask=1000.0))
        structured = agent.decide(state).structured
        if structured["decision"] != "RejectOffer":
            self.assertNotIn("counter_price", structured)

    def test_adapter_fallback_decays_instead_of_repeating_one_price(self):
        """The last-resort path is still reachable, but no longer static.

        A fixed 15% of own value, resent every round, is what produced 98
        identical counteroffers. If the agent ever fails to price a counteroffer
        the fallback must at least concede as the clock runs out.
        """

        class _BarePrice:
            """An action that rejects without pricing anything."""

            structured = {"decision": "RejectOffer"}
            accept_reject = "RejectOffer"
            numeric_action = None
            message = None

        early = to_live_action(_buyer_game(round=1), _BarePrice())["product_price"]
        late = to_live_action(_buyer_game(round=98), _BarePrice())["product_price"]

        self.assertLess(early, late, "buyer fallback should bid up as rounds run out")
        self.assertLessEqual(late, 8000.0, "never bid above our own value")


class RejectedByTheGateTests(unittest.TestCase):
    """All three flags are off, and that is a recorded verdict, not an oversight.

    Guarded by a test so none can be flipped on later without someone having to
    delete an assertion that says why it is off.
    """

    def test_every_negotiation_flag_defaults_off(self):
        """All three were rejected -- individually, and again as one combined change.

        Combined they measured +0.0109 (t=+10.07) and passed every check on seed
        4242, then +0.0094 (t=+12.49) and failed `minimum_effect` on an independent
        confirmation run declared in advance. The marginal pass did not replicate.
        """

        agent = MyAgent(seed=1)
        self.assertFalse(agent.use_time_concession, "rejected: +0.0003 vs 0.0100 minimum effect")
        self.assertFalse(agent.guarantee_own_margin, "rejected: +0.0076 vs 0.0100 minimum effect")
        self.assertFalse(agent.debias_counterpart_value, "rejected: +0.0072 vs 0.0100 minimum effect")

    def test_the_counteroffer_plumbing_is_coupled_to_the_margin_guarantee(self):
        """The two cannot ship apart, and this is why.

        With the margin guarantee off, the agent's own counter price can land on
        exactly its reservation value -- worth zero. The adapter's own_value*0.85
        fallback is at least profitable. So attaching a counter price while the clip
        fix is off would be a live regression, not an improvement.
        """

        state = to_game_state(_buyer_game(round=5))
        off = MyAgent(seed=1, guarantee_own_margin=False).decide(state).structured
        self.assertEqual(off["decision"], "RejectOffer")
        self.assertNotIn("counter_price", off, "must defer to the adapter fallback while the clip fix is off")

        on = _fixed().decide(state).structured
        self.assertIn("counter_price", on)


class ConcessionCurveTests(unittest.TestCase):
    def test_counteroffer_moves_across_the_horizon(self):
        """The defect, stated as a test: the price used to be round-independent."""

        prices = _counter_prices(_fixed(), (1, 25, 50, 75, 90, 98))
        self.assertIsNone(next((p for p in prices if p is None), None), "expected offers, not a walk-away")
        self.assertGreater(len(set(prices)), 1, "counteroffer never changed across 98 rounds")

    def test_a_buyer_concedes_upward_and_never_past_its_own_value(self):
        prices = [p for p in _counter_prices(_fixed(), tuple(range(1, 99, 7))) if p is not None]
        self.assertEqual(prices, sorted(prices), "buyer concessions must be monotone, never retracted")
        for price in prices:
            self.assertLess(price, 8000.0, "bidding our full value earns zero surplus")

    def test_the_curve_is_convex_holding_margin_early(self):
        """Boulware, not linear: negotiation has no discounting, so speed is free.

        A deal in round 90 is worth exactly what the same deal was worth in round
        2, so there is no reason to pay for an early close -- only a reason not to
        run out of rounds.
        """

        agent = _fixed()
        state = to_game_state(_buyer_game(round=50))
        midpoint = agent._negotiation_concession_factor(state)
        self.assertGreater(midpoint, 0.5, "half the rounds gone should cost less than half the margin")

        first = agent._negotiation_concession_factor(to_game_state(_buyer_game(round=1)))
        last = agent._negotiation_concession_factor(to_game_state(_buyer_game(round=99)))
        self.assertAlmostEqual(first, 1.0)
        self.assertAlmostEqual(last, 0.0)

    def test_the_flag_restores_the_old_static_behaviour(self):
        """Kept switchable so the gate can measure it rather than assume it."""

        prices = _counter_prices(_fixed(use_time_concession=False), (1, 25, 50, 75, 90))
        self.assertEqual(len(set(prices)), 1, "with concession off the price should be static")


class NoTradeZoneClipTests(unittest.TestCase):
    """The clip window must never collapse onto our own reservation value."""

    def test_a_believed_no_trade_zone_does_not_force_a_zero_surplus_bid(self):
        """A seller asking 2.5x our value used to pin the bid at exactly our value.

        The buyer infers the seller's value from their ask, so a high ask makes
        `surplus_room` zero. The clip floor was `min(seller_value, buyer_value)`,
        which collapses to `buyer_value` once the believed cost exceeds our value
        -- a one-point window, so every legal bid was exactly what the good is
        worth to us. Accepted or not, that pays zero.
        """

        agent = _fixed()
        state = to_game_state(_buyer_game(round=1))
        beliefs = agent._negotiation_beliefs(state)
        self.assertEqual(beliefs["surplus_room"], 0.0, "fixture must reproduce the believed no-trade zone")
        self.assertGreater(beliefs["seller_value"], beliefs["buyer_value"])

        structured = agent.decide(state).structured
        self.assertLess(
            structured["counter_normalized_price"],
            beliefs["buyer_value"],
            "a bid at our own value earns zero even when accepted",
        )

    def test_a_seller_never_asks_below_its_own_cost(self):
        """Mirror of the buyer collapse: the old ceiling was max(seller, buyer).

        When the believed buyer value falls below our cost that window is
        [seller_value, seller_value], so the only legal ask was exactly our cost.
        """

        game = fixtures.negotiation_decision(round=40, max_rounds=99, complete_information=False, history=[])
        state_dict = game["game_state"]
        # Flip to the seller seat: we hold a cost, the buyer has lowballed us.
        state_dict.pop("player_2_value", None)
        state_dict["current_player"] = "player_1"
        state_dict["player_1_value"] = 9000
        state_dict["last_offer"] = {"price": 2000, "message": None, "from_player": "player_2", "round": 39}
        game["your_player"] = "player_1"

        state = to_game_state(game)
        self.assertEqual(state.role, "seller")

        agent = _fixed()
        beliefs = agent._negotiation_beliefs(state)
        self.assertLess(beliefs["buyer_value"], beliefs["seller_value"], "expected a believed no-trade zone")

        evidence = agent._negotiation_evidence(state, beliefs)
        control = agent._control(state, beliefs, evidence, "negotiation")
        price = agent._negotiation_offer_price(state, control)
        self.assertGreater(price, beliefs["seller_value"], "asking exactly our cost pays zero")


if __name__ == "__main__":
    unittest.main()
