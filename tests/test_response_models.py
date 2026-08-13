from __future__ import annotations

import tempfile
import unittest
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
