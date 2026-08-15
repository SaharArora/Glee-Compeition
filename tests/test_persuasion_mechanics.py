from __future__ import annotations

import math
import unittest
from dataclasses import replace
from types import SimpleNamespace

from glee_eval.data.ingest import terminal_persuasion
from glee_eval.data.transcripts import transcript_item_decision, transcript_item_quality
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.sampler import sample_scenario
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import (
    MyAgent,
    PersuasionDeceptiveSellerGuardCandidate,
    PersuasionPlattCandidate,
)


def _scenario(role: str, *, myopic: bool, rounds: int = 8, **overrides):
    scenario = sample_scenario("persuasion", seed=91, candidate_role=role, catalogue=ConfigCatalogue({"families": {}}))
    config = dict(scenario.public_parameters)
    config.update({"is_myopic": myopic, "total_rounds": rounds, "p": 0.5, "v": 1.4, "c": 0.0, "product_price": 100})
    config.update(overrides)
    return replace(scenario, public_parameters=config)


def _buyer_states(episode):
    return [record.visible_state for record in episode.decision_records if record.role == "buyer"]


class MyopicBuyerMemoryTests(unittest.TestCase):
    """A myopic buyer's conversation is wiped every round upstream.

    `PersuasionGame.end_round` calls `player_2.end_chat()` then `new_chat()` when
    `is_myopic`, so the buyer genuinely carries nothing between rounds -- only the
    aggregate statistics the game injects. About 49.4% of real persuasion games are
    myopic, so showing our buyer the full history over-informs it in half the
    family.
    """

    def test_a_myopic_buyer_never_sees_a_previous_round(self) -> None:
        episode = run_episode(_scenario("buyer", myopic=True), MyAgent(seed=1))

        for state in _buyer_states(episode):
            current = state["round"]
            stale = [
                item
                for item in state["visible_transcript"]
                if item.get("action_type") not in {"market_statistics"} and item.get("round") not in (None, current)
            ]
            self.assertEqual(stale, [], f"round {current} leaked earlier rounds: {stale}")

    def test_a_myopic_buyer_still_sees_this_round_seller_action(self) -> None:
        episode = run_episode(_scenario("buyer", myopic=True), MyAgent(seed=1))

        for state in _buyer_states(episode):
            seller_items = [item for item in state["visible_transcript"] if item.get("role") == "seller"]
            self.assertTrue(seller_items, "buyer must see the seller's message for the current round")

    def test_a_myopic_buyer_gets_the_aggregate_statistics_instead(self) -> None:
        """Upstream replaces history with sold/high-quality-sold counters."""

        episode = run_episode(_scenario("buyer", myopic=True), MyAgent(seed=1))

        later = [state for state in _buyer_states(episode) if state["round"] > 1]
        self.assertTrue(later)
        for state in later:
            stats = [item for item in state["visible_transcript"] if item.get("action_type") == "market_statistics"]
            self.assertEqual(len(stats), 1, "exactly one market-statistics summary expected")
            self.assertIn("products_sold", stats[0])
            self.assertIn("high_quality_sold", stats[0])

    def test_market_statistics_match_what_actually_happened(self) -> None:
        episode = run_episode(_scenario("buyer", myopic=True), MyAgent(seed=1))

        quality_by_round = {
            item["round"]: item.get("quality")
            for item in episode.full_transcript
            if item.get("action_type") == "nature_quality"
        }
        for state in _buyer_states(episode):
            stats = next(
                (item for item in state["visible_transcript"] if item.get("action_type") == "market_statistics"),
                None,
            )
            if stats is None:
                continue
            sold = sum(
                1
                for item in episode.full_transcript
                if item.get("action_type") == "buy_decision"
                and item.get("buy_no_buy") == "yes"
                and item["round"] < state["round"]
            )
            high = sum(
                1
                for item in episode.full_transcript
                if item.get("action_type") == "buy_decision"
                and item.get("buy_no_buy") == "yes"
                and item["round"] < state["round"]
                and quality_by_round.get(item["round"]) == "high-quality"
            )
            self.assertEqual(stats["products_sold"], sold)
            self.assertEqual(stats["high_quality_sold"], high)

    def test_a_non_myopic_buyer_keeps_the_full_history(self) -> None:
        episode = run_episode(_scenario("buyer", myopic=False), MyAgent(seed=1))

        last = _buyer_states(episode)[-1]
        rounds_seen = {item.get("round") for item in last["visible_transcript"]}
        self.assertGreater(len(rounds_seen), 1, "a persistent buyer should carry history")

    def test_the_seller_keeps_full_history_even_when_the_buyer_is_myopic(self) -> None:
        """Only player_2's chat is reset upstream; the seller's buffer is never wiped."""

        episode = run_episode(_scenario("seller", myopic=True), MyAgent(seed=1))

        seller_states = [r.visible_state for r in episode.decision_records if r.role == "seller"]
        last = seller_states[-1]
        rounds_seen = {item.get("round") for item in last["visible_transcript"]}
        self.assertGreater(len(rounds_seen), 1)

    def test_the_buyer_still_never_sees_the_current_round_quality(self) -> None:
        for myopic in (True, False):
            episode = run_episode(_scenario("buyer", myopic=myopic), MyAgent(seed=1))
            for state in _buyer_states(episode):
                leaked = [
                    item
                    for item in state["visible_transcript"]
                    if item.get("action_type") == "nature_quality" and item.get("round") == state["round"]
                ]
                self.assertEqual(leaked, [], f"quality leaked with is_myopic={myopic}")


class PersuasionValueConventionTests(unittest.TestCase):
    """`v` is the high-quality value and `c` the low one.

    Upstream's docstring claims the opposite, but the asserts (`0 <= c <= 1`,
    `1 <= v`) and the logic (`product_worth = self.v if is_quality else self.c`)
    both say v is high. Pinning it here so the docstring cannot mislead a later
    reader into swapping them.
    """

    def _terminal(self, worth: float) -> dict:
        config = {
            "game_type": "persuasion",
            "player_1_args": {"public_name": "Alice"},
            "player_2_args": {"public_name": "Bob"},
            "game_args": {"product_price": 100, "total_rounds": 2, "p": 0.5, "v": 1.4, "c": 0.0},
        }
        rows = [
            {"player": "Nature", "round": 1, "round_quality": "high-quality", "product_worth": worth},
            {"player": "Alice", "round": 1, "decision": "yes"},
            {"player": "Bob", "round": 1, "decision": "yes"},
        ]
        return terminal_persuasion(rows, config)

    def test_buying_above_price_is_a_gain_for_the_buyer(self) -> None:
        terminal = self._terminal(140.0)

        self.assertGreater(terminal["player_2_payoff"], 0.0)
        self.assertEqual(terminal["sales"], 1)

    def test_buying_below_price_is_a_loss_for_the_buyer(self) -> None:
        terminal = self._terminal(0.0)

        self.assertLess(terminal["player_2_payoff"], 0.0)

    def test_the_seller_is_paid_the_price_regardless_of_quality(self) -> None:
        self.assertEqual(self._terminal(140.0)["player_1_payoff"], self._terminal(0.0)["player_1_payoff"])


if __name__ == "__main__":
    unittest.main()


class TranscriptShapeTests(unittest.TestCase):
    """Real and synthetic transcript rows carry the same facts under different keys.

    Reading only the synthetic key is silent on real data -- it yields None, the
    belief update learns nothing, and the posterior sits at the prior. That is what
    made the agent decline all 66,480 real buyer decisions.
    """

    def test_quality_is_read_from_either_shape(self) -> None:
        synthetic = {"action_type": "nature_quality", "quality": "high-quality"}
        ingested = {"action_type": "nature_quality", "raw": {"round_quality": "high-quality"}}

        self.assertEqual(transcript_item_quality(synthetic), "high-quality")
        self.assertEqual(transcript_item_quality(ingested), "high-quality")

    def test_decision_is_read_from_either_shape(self) -> None:
        synthetic = {"buy_no_buy": "yes"}
        structured = {"structured": {"decision": "yes"}}
        ingested = {"raw": {"decision": "yes"}}

        for row in (synthetic, structured, ingested):
            self.assertEqual(transcript_item_decision(row), "yes")

    def test_missing_or_empty_rows_return_none(self) -> None:
        for row in (None, {}, {"raw": {}}, {"structured": {}}):
            self.assertIsNone(transcript_item_quality(row))
            self.assertIsNone(transcript_item_decision(row))

    def test_the_agent_learns_from_an_ingested_shape_transcript(self) -> None:
        """The regression itself: a real-shaped history must move the posterior."""

        agent = MyAgent(seed=1)
        base = dict(
            role="buyer", round=4, horizon=8, game_family="persuasion",
            private_parameters={}, valid_action_schema={"kind": "buy_decision"},
            metadata={}, game_id="g", scenario_id="s",
            public_parameters={"p": 0.5, "v": 1.4, "c": 0.0, "product_price": 100},
        )
        # Three rounds in which the seller recommended a product that was high quality.
        history = []
        for r in (1, 2, 3):
            history.append({"round": r, "role": "nature", "action_type": "nature_quality",
                            "raw": {"round_quality": "high-quality"}})
            history.append({"round": r, "role": "seller", "action_type": "recommendation",
                            "raw": {"decision": "yes"}})
            history.append({"round": r, "role": "buyer", "action_type": "buy_decision",
                            "raw": {"decision": "yes"}})
        history.append({"round": 4, "role": "seller", "action_type": "recommendation",
                        "raw": {"decision": "yes"}})

        informed = agent._persuasion_beliefs(SimpleNamespace(**{**base, "visible_transcript": history}))
        naive = agent._persuasion_beliefs(SimpleNamespace(**{**base, "visible_transcript": []}))

        self.assertGreater(informed["seller_honesty"], naive["seller_honesty"])
        self.assertGreater(informed["posterior_quality_given_yes"], naive["posterior_quality_given_yes"])

    def test_a_consistently_lying_seller_lowers_the_posterior(self) -> None:
        agent = MyAgent(seed=1)
        base = dict(
            role="buyer", round=4, horizon=8, game_family="persuasion",
            private_parameters={}, valid_action_schema={"kind": "buy_decision"},
            metadata={}, game_id="g", scenario_id="s",
            public_parameters={"p": 0.5, "v": 1.4, "c": 0.0, "product_price": 100},
        )
        history = []
        for r in (1, 2, 3):
            history.append({"round": r, "role": "nature", "action_type": "nature_quality",
                            "raw": {"round_quality": "low-quality"}})
            history.append({"round": r, "role": "seller", "action_type": "recommendation",
                            "raw": {"decision": "yes"}})
        history.append({"round": 4, "role": "seller", "action_type": "recommendation",
                        "raw": {"decision": "yes"}})

        beliefs = agent._persuasion_beliefs(SimpleNamespace(**{**base, "visible_transcript": history}))
        naive = agent._persuasion_beliefs(SimpleNamespace(**{**base, "visible_transcript": []}))

        self.assertLess(beliefs["seller_honesty"], naive["seller_honesty"])
        self.assertLess(beliefs["posterior_quality_given_yes"], naive["posterior_quality_given_yes"])


class ColdStartExplorationTests(unittest.TestCase):
    """Rejected by the gate at +0.0051 against a 0.0100 minimum, so off by default."""

    def _state(self, transcript, sold=0, high=0, p=0.5, v=1.25, rounds=20, round_number=2):
        return SimpleNamespace(
            role="buyer", round=round_number, horizon=rounds, game_family="persuasion",
            public_parameters={"p": p, "v": v, "c": 0.0, "product_price": 100, "total_rounds": rounds},
            private_parameters={}, valid_action_schema={"kind": "buy_decision"},
            visible_transcript=transcript, metadata={}, game_id="g", scenario_id="s",
        )

    def _yes_only(self):
        return [{"round": 2, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"}]

    def test_exploration_is_off_by_default(self) -> None:
        self.assertFalse(MyAgent(seed=1).persuasion_explore)

    def test_disabled_agent_declines_a_high_break_even_config(self) -> None:
        agent = MyAgent(seed=1, persuasion_explore=False)
        state = self._state(self._yes_only())
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertEqual(agent._persuasion_buy_decision(state, control), "no")

    def test_enabled_agent_explores_when_there_is_no_transcript_channel(self) -> None:
        agent = MyAgent(seed=1, persuasion_explore=True)
        state = self._state(self._yes_only())
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertEqual(beliefs["transcript_observations"], 0.0)
        self.assertEqual(agent._persuasion_buy_decision(state, control), "yes")

    def test_it_does_not_explore_when_history_is_available_for_free(self) -> None:
        """A persistent buyer learns by reading; paying to learn is pure cost there."""

        transcript = self._yes_only() + [
            {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
            {"round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
        ]
        agent = MyAgent(seed=1, persuasion_explore=True)
        state = self._state(transcript)
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertGreater(beliefs["transcript_observations"], 0.0)
        self.assertIsNone(agent._persuasion_explore_buy(state, control))

    def test_it_stops_once_the_budget_is_spent(self) -> None:
        transcript = self._yes_only() + [
            {"round": 1, "role": "market", "action_type": "market_statistics",
             "products_sold": 9, "high_quality_sold": 4},
        ]
        agent = MyAgent(seed=1, persuasion_explore=True)
        state = self._state(transcript)
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertIsNone(agent._persuasion_explore_buy(state, control))

    def test_it_does_not_explore_in_the_back_half_of_a_game(self) -> None:
        agent = MyAgent(seed=1, persuasion_explore=True)
        state = self._state(self._yes_only(), round_number=18)
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertIsNone(agent._persuasion_explore_buy(state, control))

    def test_it_refuses_when_a_single_buy_is_too_expensive(self) -> None:
        """v barely above 1 makes a blind buy nearly a total loss."""

        agent = MyAgent(seed=1, persuasion_explore=True, max_exploration_loss=0.10)
        state = self._state(self._yes_only(), v=1.01)
        beliefs = agent._persuasion_beliefs(state)
        control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

        self.assertIsNone(agent._persuasion_explore_buy(state, control))


class PersuasionPlattCandidateTests(unittest.TestCase):
    """Predictively successful, but default-off pending the payoff gate."""

    @staticmethod
    def _state(recommendation="yes"):
        return SimpleNamespace(
            role="buyer", round=1, horizon=20, game_family="persuasion",
            public_parameters={"p": 0.5, "v": 1.5, "c": 0.0, "product_price": 100, "total_rounds": 20},
            private_parameters={}, valid_action_schema={"kind": "buy_decision"},
            visible_transcript=[{
                "round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": recommendation,
            }],
            metadata={}, game_id="g", scenario_id="s",
        )

    @staticmethod
    def _control(agent, state):
        beliefs = agent._persuasion_beliefs(state)
        return agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

    def test_candidate_is_off_by_default(self) -> None:
        self.assertFalse(MyAgent(seed=1).use_persuasion_platt)
        self.assertTrue(PersuasionPlattCandidate(seed=1).use_persuasion_platt)

    def test_raw_posterior_is_retained_when_candidate_is_enabled(self) -> None:
        state = self._state()
        baseline = MyAgent(seed=1)
        candidate = MyAgent(seed=1, use_persuasion_platt=True)
        baseline_beliefs = baseline._persuasion_beliefs(state)
        candidate_beliefs = candidate._persuasion_beliefs(state)

        self.assertEqual(
            candidate_beliefs["posterior_quality_given_yes_raw"],
            baseline_beliefs["posterior_quality_given_yes"],
        )
        self.assertEqual(
            candidate_beliefs["posterior_quality_given_yes"],
            baseline_beliefs["posterior_quality_given_yes"],
        )
        self.assertGreater(
            candidate_beliefs["posterior_quality_given_yes_platt"],
            candidate_beliefs["posterior_quality_given_yes_raw"],
        )

    def test_candidate_changes_only_the_post_yes_buy_probability(self) -> None:
        state = self._state("yes")
        baseline = MyAgent(seed=1)
        candidate = MyAgent(seed=1, use_persuasion_platt=True)
        baseline_control = self._control(baseline, state)
        candidate_control = self._control(candidate, state)

        self.assertEqual(baseline._persuasion_buy_decision(state, baseline_control), "no")
        self.assertEqual(candidate._persuasion_buy_decision(state, candidate_control), "yes")
        self.assertEqual(candidate_control.beliefs["persuasion_platt_applied"], 1.0)
        self.assertEqual(
            candidate_control.beliefs["posterior_quality_given_yes_raw"],
            baseline_control.beliefs["posterior_quality_given_yes_raw"],
        )

    def test_no_recommendation_still_declines_without_applying_candidate(self) -> None:
        state = self._state("no")
        candidate = MyAgent(seed=1, use_persuasion_platt=True)
        control = self._control(candidate, state)

        self.assertEqual(candidate._persuasion_buy_decision(state, control), "no")
        self.assertNotIn("persuasion_platt_applied", control.beliefs)


class PersuasionDeceptiveSellerGuardTests(unittest.TestCase):
    @staticmethod
    def _state(*, lie=True, myopic=False):
        history = []
        if lie:
            history.extend([
                {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
                {"round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            ])
        else:
            history.extend([
                {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
                {"round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            ])
        if myopic:
            history = [{"round": 2, "action_type": "market_statistics", "products_sold": 1, "high_quality_sold": 0}]
        history.append({
            "round": 2, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes",
        })
        return SimpleNamespace(
            role="buyer", round=2, horizon=8, game_family="persuasion",
            public_parameters={"p": .5, "v": 2.0, "c": 0.0, "product_price": 100, "is_myopic": myopic},
            private_parameters={}, valid_action_schema={"kind": "buy_decision"},
            visible_transcript=history, metadata={}, game_id="g", scenario_id="s",
        )

    @staticmethod
    def _control(agent, state):
        beliefs = agent._persuasion_beliefs(state)
        return agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")

    def test_guard_is_off_by_default_and_gate_candidate_is_isolated(self) -> None:
        baseline = MyAgent(seed=1)
        candidate = PersuasionDeceptiveSellerGuardCandidate(
            seed=1, use_persuasion_platt=True, persuasion_explore=True,
        )
        self.assertFalse(baseline.use_deceptive_seller_guard)
        self.assertTrue(candidate.use_deceptive_seller_guard)
        self.assertFalse(candidate.use_persuasion_platt)
        self.assertFalse(candidate.persuasion_explore)

    def test_exact_declared_bound_applies_after_one_visible_lie(self) -> None:
        state = self._state(lie=True)
        candidate = PersuasionDeceptiveSellerGuardCandidate(seed=1)
        control = self._control(candidate, state)
        q = control.beliefs["posterior_quality_given_yes_raw"]
        expected = max(0.0, q - math.sqrt(q * (1.0 - q) / 5.0))

        self.assertAlmostEqual(control.beliefs["posterior_quality_given_yes_deceptive_guard"], expected)
        self.assertEqual(candidate._persuasion_buy_decision(state, control), "no")
        self.assertAlmostEqual(control.beliefs["posterior_quality_used_for_buy"], expected)
        self.assertEqual(control.beliefs["deceptive_seller_guard_applied"], 1.0)
        self.assertEqual(control.beliefs["posterior_quality_given_yes_raw"], q)

    def test_no_lie_history_is_behaviorally_unchanged(self) -> None:
        state = self._state(lie=False)
        baseline = MyAgent(seed=1)
        candidate = PersuasionDeceptiveSellerGuardCandidate(seed=1)
        base_control = self._control(baseline, state)
        candidate_control = self._control(candidate, state)

        self.assertEqual(
            baseline._persuasion_buy_decision(state, base_control),
            candidate._persuasion_buy_decision(state, candidate_control),
        )
        self.assertEqual(candidate_control.beliefs["deceptive_seller_guard_applied"], 0.0)

    def test_myopic_history_is_behaviorally_unchanged(self) -> None:
        state = self._state(lie=True, myopic=True)
        baseline = MyAgent(seed=1)
        candidate = PersuasionDeceptiveSellerGuardCandidate(seed=1)
        base_control = self._control(baseline, state)
        candidate_control = self._control(candidate, state)

        self.assertEqual(
            baseline._persuasion_buy_decision(state, base_control),
            candidate._persuasion_buy_decision(state, candidate_control),
        )
        self.assertEqual(candidate_control.beliefs["deceptive_seller_guard_applied"], 0.0)
