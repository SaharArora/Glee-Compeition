from __future__ import annotations

import unittest

from glee_eval.adapters.candidate_agent import HeuristicAgent
from glee_eval.data.schemas import GameState
from glee_eval.opponents.policies import PolicyFactory
from glee_eval.population.sampler import sample_scenario
from glee_eval.probes.extract import extract_probes
from glee_eval.tournament.runner import run_episode, run_tournament


class TournamentProbeTests(unittest.TestCase):
    def test_policy_returns_legal_bargaining_offer(self) -> None:
        state = GameState(
            scenario_id="s",
            game_id="g",
            game_family="bargaining",
            role="player_1",
            round=1,
            horizon=6,
            public_parameters={"money_to_divide": 100},
            private_parameters={},
            visible_transcript=[],
            valid_action_schema={"kind": "offer"},
        )
        policy = PolicyFactory.create("bargaining", {"archetype": "fairness_sensitive", "seed": 1, "parameters": {}})
        action = policy.decide(state)
        self.assertEqual(action.action_type, "offer")
        self.assertGreater(action.numeric_action or 0, 0)

    def test_all_families_run(self) -> None:
        agent = HeuristicAgent()
        for family in ["bargaining", "negotiation", "persuasion"]:
            scenario = sample_scenario(family, seed=123)
            episode = run_episode(scenario, agent)
            self.assertEqual(episode.scenario.game_family, family)
            self.assertTrue(episode.full_transcript)

    def test_tournament_is_deterministic(self) -> None:
        one = run_tournament(agent_spec="heuristic", families=["negotiation"], games=5, seed=7, output_dir="/tmp/glee_eval_test_one")
        two = run_tournament(agent_spec="heuristic", families=["negotiation"], games=5, seed=7, output_dir="/tmp/glee_eval_test_two")
        self.assertEqual(one["metrics"], two["metrics"])

    def test_extract_probes(self) -> None:
        events = [
            {
                "game_id": "g1",
                "game_family": "bargaining",
                "role": "player_1",
                "round": 1,
                "configuration": {"max_rounds": 2},
                "public_parameters": {"money_to_divide": 100},
                "private_information": {},
                "transcript_so_far": [],
                "action_type": "offer",
                "numeric_action": 60,
                "source": "fixture",
                "config_id": "c",
                "terminal_outcome": {"result": "accept"},
            }
        ]
        probes = extract_probes(events)
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0].game_family, "bargaining")


if __name__ == "__main__":
    unittest.main()

