from __future__ import annotations

import unittest

from glee_eval.adapters.candidate_agent import load_agent
from glee_eval.population.sampler import sample_scenario
from glee_eval.tournament.runner import run_episode


class JordanStrategicAgentTests(unittest.TestCase):
    def test_jordan_agent_runs_all_families(self) -> None:
        agent = load_agent("my_agents.jordan_strategic:MyAgent", seed=3)
        for family in ["bargaining", "negotiation", "persuasion"]:
            scenario = sample_scenario(family, seed=100 + len(family))
            episode = run_episode(scenario, agent)
            self.assertEqual(episode.scenario.game_family, family)
            self.assertTrue(episode.decision_records)

    def test_persuasion_buyer_does_not_see_current_quality(self) -> None:
        agent = load_agent("my_agents.jordan_strategic:MyAgent", seed=7)
        scenario = sample_scenario("persuasion", seed=123, candidate_role="buyer")
        episode = run_episode(scenario, agent)
        buyer_records = [record for record in episode.decision_records if record.role == "buyer"]
        self.assertTrue(buyer_records)
        for record in buyer_records:
            current_round = record.round
            visible = record.visible_state["visible_transcript"]
            leaked = [
                item
                for item in visible
                if item.get("action_type") == "nature_quality" and item.get("round") == current_round
            ]
            self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
