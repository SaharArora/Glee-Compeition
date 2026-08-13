from __future__ import annotations

import itertools
import unittest
from types import SimpleNamespace

from my_agents.baseline import MyAgent as BaselineAgent
from my_agents.jordan_strategic import MyAgent

FAMILY_SCHEMAS = [
    ("bargaining", "player_1", "offer"),
    ("bargaining", "player_2", "decision"),
    ("negotiation", "seller", "offer"),
    ("negotiation", "buyer", "decision"),
    ("persuasion", "seller", "recommendation"),
    ("persuasion", "buyer", "buy_decision"),
]

MALFORMED_SCALARS = [None, "", "not-a-number", float("nan"), -5, 0]


def _state(**overrides):
    base = dict(
        role="player_1",
        round=1,
        horizon=6,
        game_family="bargaining",
        public_parameters={},
        private_parameters={},
        valid_action_schema={"kind": "offer"},
        visible_transcript=[],
        metadata={},
        game_id="g",
        scenario_id="s",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class MalformedStateTests(unittest.TestCase):
    """A bad field must degrade the decision, never kill it.

    None of these arise from our own runner, which is exactly why they were
    reachable: the test suite and a 200-game synthetic tournament only ever feed
    the agent well-formed state.
    """

    def test_every_family_survives_a_malformed_round_or_horizon(self) -> None:
        agent = MyAgent(seed=1)
        for (family, role, kind), value in itertools.product(FAMILY_SCHEMAS, MALFORMED_SCALARS):
            for field in ("round", "horizon"):
                with self.subTest(family=family, kind=kind, field=field, value=repr(value)):
                    action = agent.decide(_state(**{
                        "game_family": family,
                        "role": role,
                        "valid_action_schema": {"kind": kind},
                        field: value,
                    }))
                    self.assertIsNotNone(action.action_type)

    def test_every_family_survives_an_empty_config(self) -> None:
        agent = MyAgent(seed=1)
        for family, role, kind in FAMILY_SCHEMAS:
            with self.subTest(family=family, kind=kind):
                action = agent.decide(_state(game_family=family, role=role, valid_action_schema={"kind": kind}))
                self.assertIsNotNone(action.action_type)

    def test_malformed_config_scalars_do_not_raise(self) -> None:
        agent = MyAgent(seed=1)
        keys = ["money_to_divide", "seller_value", "buyer_value", "product_price_order", "p", "v", "c", "product_price"]
        for (family, role, kind), value in itertools.product(FAMILY_SCHEMAS, MALFORMED_SCALARS):
            config = {key: value for key in keys}
            with self.subTest(family=family, kind=kind, value=repr(value)):
                action = agent.decide(_state(
                    game_family=family, role=role, valid_action_schema={"kind": kind}, public_parameters=config
                ))
                self.assertIsNotNone(action.action_type)

    def test_non_dict_transcript_entries_are_ignored(self) -> None:
        agent = MyAgent(seed=1)
        transcript = [None, "junk", 42, [], {"role": "player_1", "action_type": "offer", "self_gain": 55.0}]
        for family, role, kind in FAMILY_SCHEMAS:
            with self.subTest(family=family, kind=kind):
                action = agent.decide(_state(
                    game_family=family, role=role, valid_action_schema={"kind": kind}, visible_transcript=transcript
                ))
                self.assertIsNotNone(action.action_type)

    def test_missing_transcript_attribute_is_tolerated(self) -> None:
        agent = MyAgent(seed=1)
        action = agent.decide(_state(visible_transcript=None))
        self.assertEqual(action.action_type, "offer")

    def test_unknown_family_returns_a_legal_shaped_action(self) -> None:
        action = MyAgent(seed=1).decide(_state(game_family="chess"))
        self.assertEqual(action.action_type, "unknown")

    def test_baseline_agent_also_survives_the_same_probes(self) -> None:
        agent = BaselineAgent(seed=1)
        for (family, role, kind), value in itertools.product(FAMILY_SCHEMAS, [None, float("nan")]):
            with self.subTest(family=family, kind=kind, value=repr(value)):
                try:
                    agent.decide(_state(
                        game_family=family, role=role, valid_action_schema={"kind": kind}, round=value
                    ))
                except Exception as exc:  # pragma: no cover - reported, not asserted away
                    self.fail(f"baseline crashed on {family}/{kind} round={value!r}: {type(exc).__name__}: {exc}")


class PersuasionRecommendationLookupTests(unittest.TestCase):
    """The buyer must find the seller's recommendation, not the last row."""

    def _decision(self, transcript: list[dict]) -> str:
        return MyAgent(seed=1).decide(_state(
            game_family="persuasion",
            role="buyer",
            valid_action_schema={"kind": "buy_decision"},
            public_parameters={"p": 0.9, "v": 1.4, "c": 0.0},
            visible_transcript=transcript,
        )).buy_no_buy

    def test_a_trailing_buyer_message_no_longer_hides_a_yes(self) -> None:
        with_message = self._decision([
            {"role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            {"role": "buyer", "action_type": "message", "message": "thinking"},
        ])
        without_message = self._decision([
            {"role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
        ])

        self.assertEqual(with_message, without_message)

    def test_a_no_recommendation_is_still_honoured_through_a_trailing_row(self) -> None:
        self.assertEqual(
            self._decision([
                {"role": "seller", "action_type": "recommendation", "buy_no_buy": "no"},
                {"role": "buyer", "action_type": "message", "message": "ok"},
            ]),
            "no",
        )

    def test_the_most_recent_seller_action_wins(self) -> None:
        self.assertEqual(
            self._decision([
                {"role": "seller", "action_type": "recommendation", "buy_no_buy": "no"},
                {"role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            ]),
            "yes",
        )

    def test_no_seller_action_defaults_to_not_buying(self) -> None:
        self.assertEqual(self._decision([{"role": "nature", "action_type": "nature_quality"}]), "no")


if __name__ == "__main__":
    unittest.main()
