from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace

from glee_eval.response_models.runtime import negotiation_keys
from pathlib import Path

from glee_eval.population.sampler import sample_scenario
from glee_eval.response_models.runtime import EmpiricalResponseModel
from glee_eval.response_models.train import train_response_models
from glee_eval.storage.trajectories import write_jsonl
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import JordanStrategicAgent


def _event(**kwargs):
    base = {
        "source": "fixture",
        "config_id": "c1",
        "private_information": {},
        "public_parameters": {},
        "terminal_outcome": {},
        "transcript_so_far": [],
    }
    base.update(kwargs)
    return base


class ResponseModelTests(unittest.TestCase):
    def test_train_response_models_and_load_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            events = [
                _event(
                    game_id="b1",
                    event_id="b1-0",
                    game_family="bargaining",
                    role="player_2",
                    round=1,
                    action_type="decision",
                    accepted=True,
                    rejected=False,
                    configuration={"money_to_divide": 100, "max_rounds": 6},
                    transcript_so_far=[
                        {
                            "role": "player_1",
                            "player": "Alice",
                            "round": 1,
                            "action_type": "offer",
                            "raw": {"player": "Alice", "alice_gain": "55", "bob_gain": "45"},
                        }
                    ],
                ),
                _event(
                    game_id="n1",
                    event_id="n1-0",
                    game_family="negotiation",
                    role="buyer",
                    round=1,
                    action_type="decision",
                    accepted=True,
                    rejected=False,
                    configuration={"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6},
                    transcript_so_far=[
                        {
                            "role": "seller",
                            "player": "Alice",
                            "round": 1,
                            "action_type": "offer",
                            "raw": {"player": "Alice", "product_price": "900"},
                        }
                    ],
                ),
                _event(
                    game_id="p1",
                    event_id="p1-0",
                    game_family="persuasion",
                    role="buyer",
                    round=1,
                    action_type="buy_decision",
                    bought=True,
                    configuration={"p": 0.6, "v": 1.2, "c": 0.0, "total_rounds": 20},
                    transcript_so_far=[
                        {
                            "role": "nature",
                            "round": 1,
                            "action_type": "nature_quality",
                            "raw": {"round_quality": "high-quality"},
                        },
                        {
                            "role": "seller",
                            "round": 1,
                            "action_type": "recommendation",
                            "raw": {"decision": "yes", "message": "I strongly recommend buying."},
                        },
                    ],
                ),
            ]
            write_jsonl(data_dir / "processed" / "events.jsonl", events)

            result = train_response_models(data_dir=data_dir, output_dir=root / "models", min_support=1)

            self.assertEqual(result["summary"]["examples_total"], 3)
            model = EmpiricalResponseModel.load(root / "models")
            self.assertIsNotNone(model)
            self.assertIn("bargaining", model.payload["families"])
            self.assertIn("population_structure", model.payload)
            bucket = next(iter(model.payload["families"]["bargaining"]["buckets"].values()))
            self.assertIn("theory_residual", bucket)
            self.assertTrue((root / "models" / "training_report.md").exists())

    def test_jordan_agent_runs_with_response_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            events = [
                _event(
                    game_id="b1",
                    event_id="b1-0",
                    game_family="bargaining",
                    role="player_2",
                    round=1,
                    action_type="decision",
                    accepted=True,
                    rejected=False,
                    configuration={"money_to_divide": 100, "max_rounds": 6},
                    transcript_so_far=[
                        {
                            "role": "player_1",
                            "player": "Alice",
                            "round": 1,
                            "action_type": "offer",
                            "raw": {"player": "Alice", "alice_gain": "55", "bob_gain": "45"},
                        }
                    ],
                )
            ]
            write_jsonl(data_dir / "processed" / "events.jsonl", events)
            train_response_models(data_dir=data_dir, output_dir=root / "models", min_support=1)
            agent = JordanStrategicAgent(seed=2, response_model_path=str(root / "models"))
            scenario = sample_scenario("bargaining", seed=12)
            episode = run_episode(scenario, agent)

            self.assertTrue(episode.decision_records)
            self.assertEqual(agent.response_model.payload["version"], 1)


if __name__ == "__main__":
    unittest.main()


class NegotiationKeyDeconfoundingTests(unittest.TestCase):
    """Keys must be built on the responder's own gain, not absolute price."""

    def _state(self, seller_value, buyer_value, order=1.0, round_number=1, horizon=10):
        return SimpleNamespace(
            round=round_number,
            horizon=horizon,
            public_parameters={
                "seller_value": seller_value,
                "buyer_value": buyer_value,
                "product_price_order": order,
            },
            metadata={},
        )

    def test_gain_keys_lead_the_ladder_when_the_value_is_known(self) -> None:
        keys = negotiation_keys(self._state(0.8, 1.2), "buyer", 1.0)

        self.assertTrue(keys[0].startswith("role=buyer|round=r1|gain="))
        self.assertIn("__global__", keys)

    def test_absolute_price_keys_remain_as_fallbacks(self) -> None:
        keys = negotiation_keys(self._state(0.8, 1.2), "buyer", 1.0)

        self.assertTrue(any("|price=" in key for key in keys))
        gain_index = min(i for i, key in enumerate(keys) if "gain=" in key)
        price_index = min(i for i, key in enumerate(keys) if "price=" in key)
        self.assertLess(gain_index, price_index, "gain keys must be tried first")

    def test_no_gain_keys_when_the_responder_value_is_unknown(self) -> None:
        state = SimpleNamespace(
            round=1, horizon=10, public_parameters={"product_price_order": 1.0}, metadata={}
        )

        keys = negotiation_keys(state, "buyer", 1.0)

        self.assertFalse(any("gain=" in key for key in keys))
        self.assertTrue(any("price=" in key for key in keys))

    def test_an_explicit_belief_can_supply_the_responder_value(self) -> None:
        state = SimpleNamespace(
            round=1, horizon=10, public_parameters={"product_price_order": 1.0}, metadata={}
        )

        keys = negotiation_keys(state, "buyer", 1.0, responder_value=1.2)

        self.assertTrue(any("gain=" in key for key in keys))

    def test_equal_gain_under_different_absolute_prices_shares_a_bucket(self) -> None:
        """This is the whole point: the confound was price correlating with value."""

        low = negotiation_keys(self._state(0.6, 1.0), "buyer", 0.90)
        high = negotiation_keys(self._state(1.1, 1.5), "buyer", 1.40)

        low_gain = next(key for key in low if key.startswith("gain="))
        high_gain = next(key for key in high if key.startswith("gain="))
        self.assertEqual(low_gain, high_gain)

    def test_seller_and_buyer_gains_point_in_opposite_directions(self) -> None:
        state = self._state(0.8, 1.2)
        cheap = negotiation_keys(state, "seller", 0.85)
        dear = negotiation_keys(state, "seller", 1.15)

        self.assertNotEqual(
            next(key for key in cheap if key.startswith("gain=")),
            next(key for key in dear if key.startswith("gain=")),
        )
