from __future__ import annotations

import unittest

from glee_eval.adapters.candidate_agent import CandidateAgent
from glee_eval.data.schemas import AgentAction, GameState, Scenario, compact_id
from glee_eval.data.transcripts import persuasion_text_intent
from glee_eval.tournament.runner import run_episode


def _action(state: GameState, decision: str) -> AgentAction:
    return AgentAction(
        action_id=compact_id(state.game_id, state.round, decision),
        actor_role=state.role,
        round=state.round,
        raw_text=decision,
        action_type="recommendation" if state.role == "seller" else "buy_decision",
        buy_no_buy=decision,
        structured={"decision": decision},
    )


class _BlindBuyer(CandidateAgent):
    agent_id = "blind"

    def decide(self, state: GameState) -> AgentAction:
        seller = next((item for item in reversed(state.visible_transcript) if item.get("role") == "seller"), {})
        decision = seller.get("buy_no_buy") or (seller.get("structured") or {}).get("decision") or "no"
        return _action(state, decision)


class _TextIntentBuyer(CandidateAgent):
    agent_id = "text-intent"

    def decide(self, state: GameState) -> AgentAction:
        seller = next((item for item in reversed(state.visible_transcript) if item.get("role") == "seller"), {})
        decision = (
            seller.get("buy_no_buy")
            or (seller.get("structured") or {}).get("decision")
            or persuasion_text_intent(seller.get("free_text_message"))
            or "no"
        )
        return _action(state, decision)


class _Seller(CandidateAgent):
    agent_id = "seller"

    def decide(self, state: GameState) -> AgentAction:
        return _action(state, "yes")


def _scenario(role: str, channel: str) -> Scenario:
    return Scenario(
        scenario_id=f"text-contract-{role}-{channel}",
        game_family="persuasion",
        config_id="config",
        public_parameters={
            "total_rounds": 4,
            "p": 1.0,
            "v": 2.0,
            "c": 0.0,
            "product_price": 100,
            "seller_message_type": channel,
            "is_seller_know_cv": True,
            "is_myopic": False,
        },
        candidate_role=role,
        opponent_role="seller" if role == "buyer" else "buyer",
        opponent_spec={
            "archetype": "rational",
            "game_family": "persuasion",
            "parameters": {"honesty": 1.0, "yes_on_low_rate": 0.0, "trust_prior": 1.0},
            "seed": 7,
        },
        seed=11,
    )


class TournamentTextContractTests(unittest.TestCase):
    def test_candidate_buyer_sees_text_without_latent_stance(self) -> None:
        episode = run_episode(_scenario("buyer", "text"), _BlindBuyer())
        seller_rows = [row for row in episode.full_transcript if row.get("role") == "seller"]
        self.assertTrue(seller_rows)
        for row in seller_rows:
            self.assertEqual(row["action_type"], "message")
            self.assertIsNone(row["buy_no_buy"])
            self.assertEqual(row["structured"], {})
            self.assertEqual(row["free_text_message"], "I recommend buying this product.")

    def test_ordinary_paired_payoff_path_has_text_buyer_reach(self) -> None:
        scenario = _scenario("buyer", "text")
        baseline = run_episode(scenario, _BlindBuyer())
        candidate = run_episode(scenario, _TextIntentBuyer())
        self.assertEqual(baseline.candidate_payoff, 0.0)
        self.assertGreater(candidate.candidate_payoff, baseline.candidate_payoff)

    def test_binary_candidate_buyer_path_is_unchanged(self) -> None:
        scenario = _scenario("buyer", "binary")
        baseline = run_episode(scenario, _BlindBuyer())
        candidate = run_episode(scenario, _TextIntentBuyer())
        self.assertEqual(candidate.candidate_payoff, baseline.candidate_payoff)
        seller_rows = [row for row in baseline.full_transcript if row.get("role") == "seller"]
        self.assertTrue(all(row.get("buy_no_buy") == "yes" for row in seller_rows))

    def test_candidate_seller_text_trajectory_keeps_latent_stance(self) -> None:
        episode = run_episode(_scenario("seller", "text"), _Seller())
        seller_rows = [row for row in episode.full_transcript if row.get("role") == "seller"]
        self.assertTrue(all(row.get("buy_no_buy") == "yes" for row in seller_rows))
        self.assertTrue(all(row.get("structured", {}).get("decision") == "yes" for row in seller_rows))


if __name__ == "__main__":
    unittest.main()
