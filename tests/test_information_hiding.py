from __future__ import annotations

import unittest
from dataclasses import replace

from glee_eval.population.sampler import sample_scenario
from glee_eval.tournament.runner import run_episode


def _incomplete(family: str, seed: int, candidate_role: str | None = None, **overrides):
    scenario = sample_scenario(family, seed=seed, candidate_role=candidate_role)
    config = dict(scenario.public_parameters)
    config.update(overrides)
    return replace(scenario, public_parameters=config)


class NegotiationInformationHidingTests(unittest.TestCase):
    """Under complete_information=False neither side may see the other's value."""

    def test_incomplete_information_hides_the_counterpart_value(self) -> None:
        scenario = _incomplete("negotiation", 21, complete_information=False)

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            public = record.visible_state["public_parameters"]
            private = record.visible_state["private_parameters"]
            self.assertNotIn("seller_value", public, "seller_value leaked into public parameters")
            self.assertNotIn("buyer_value", public, "buyer_value leaked into public parameters")
            own = "seller_value" if record.role == "seller" else "buyer_value"
            other = "buyer_value" if record.role == "seller" else "seller_value"
            self.assertIn(own, private)
            self.assertNotIn(other, private, f"{other} leaked to the {record.role}")

    def test_complete_information_still_shows_both_values(self) -> None:
        scenario = _incomplete("negotiation", 21, complete_information=True)

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            private = record.visible_state["private_parameters"]
            self.assertIn("seller_value", private)
            self.assertIn("buyer_value", private)


class BargainingInformationHidingTests(unittest.TestCase):
    def test_incomplete_information_hides_the_counterpart_discount(self) -> None:
        scenario = _incomplete("bargaining", 22, complete_information=False)

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            public = record.visible_state["public_parameters"]
            private = record.visible_state["private_parameters"]
            self.assertNotIn("delta_1", public)
            self.assertNotIn("delta_2", public)
            own = "delta_1" if record.role == "player_1" else "delta_2"
            other = "delta_2" if record.role == "player_1" else "delta_1"
            self.assertIn(own, private)
            self.assertNotIn(other, private)


class PersuasionInformationHidingTests(unittest.TestCase):
    def test_seller_without_cv_knowledge_does_not_see_v_or_c(self) -> None:
        scenario = _incomplete("persuasion", 23, is_seller_know_cv=False)

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            public = record.visible_state["public_parameters"]
            self.assertNotIn("v", public)
            self.assertNotIn("c", public)
            if record.role == "seller":
                self.assertNotIn("v", record.visible_state["private_parameters"])
                self.assertNotIn("c", record.visible_state["private_parameters"])

    def test_buyer_without_p_knowledge_does_not_see_p(self) -> None:
        scenario = _incomplete("persuasion", 24, is_buyer_know_p=False)

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            self.assertNotIn("p", record.visible_state["public_parameters"])
            if record.role == "buyer":
                self.assertNotIn("p", record.visible_state["private_parameters"])

    def test_buyer_never_sees_the_current_round_quality(self) -> None:
        scenario = _incomplete("persuasion", 25, candidate_role="buyer")

        episode = run_episode(scenario, __import__("my_agents.jordan_strategic", fromlist=["MyAgent"]).MyAgent(seed=1))

        for record in episode.decision_records:
            if record.role != "buyer":
                continue
            self.assertNotIn("quality", record.visible_state.get("metadata") or {})


if __name__ == "__main__":
    unittest.main()
