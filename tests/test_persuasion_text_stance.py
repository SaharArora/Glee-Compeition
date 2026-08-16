from __future__ import annotations

import unittest
from types import SimpleNamespace

from glee_eval.data.transcripts import persuasion_text_intent
from glee_eval.live import fixtures
from glee_eval.live.schema import to_game_state
from my_agents.jordan_strategic import MyAgent, PersuasionTextStanceCandidate


# Frozen confirmation+volume live corpus. Counts are buyer decisions, not merely
# unique strings, so this fixture also guards the preregistered 101/79 replay.
LIVE_TEXT_TEMPLATES = (
    (31, "yes", "I checked this unit myself and it's high quality — at this price I'd strongly recommend it."),
    (28, "no", "This unit is below our usual quality this round."),
    (16, "yes", "I recommend buying this product."),
    (12, "yes", "This unit is high quality -- recommended."),
    (11, "yes", "Today's unit is the real thing — high quality, and I'll stand behind that. At this price, buying is the right call."),
    (10, "no", "Honestly, today's product is not up to my usual standard. I'd understand if you sit this round out."),
    (10, "yes", "I can recommend this one without reservation: it's a high-quality unit and worth the price. I'd buy it."),
    (9, "no", "This one is nothing special. At this price I'd understand a pass."),
    (9, "no", "I'll be straight with you — this one isn't my best unit. You may want to pass today."),
    (8, "yes", "Strong round on my read, this is a buy."),
    (7, "yes", "Solid pick this round, honestly. Worth it."),
    (7, "no", "Being straight with you: I'd pass on this one."),
    (6, "yes", "This one's genuinely strong this round, I'd buy it. Clear value here."),
    (6, "no", "Not this round. Better to wait for a better one."),
    (6, "no", "I'd hold off this round, not a strong one."),
    (4, "no", "I do not recommend buying this product."),
)


def _state(*, text: str, structured: str | None = None, message_type: str = "text"):
    item = {
        "round": 1,
        "role": "seller",
        "action_type": "recommendation" if structured else "message",
        "buy_no_buy": structured,
        "structured": {"decision": structured} if structured else {},
        "free_text_message": text,
    }
    return SimpleNamespace(
        role="buyer", round=1, horizon=20, game_family="persuasion",
        public_parameters={
            "p": 0.8, "v": 2.0, "c": 0.0, "product_price": 100,
            "total_rounds": 20, "seller_message_type": message_type,
        },
        private_parameters={}, valid_action_schema={"kind": "buy_decision"},
        visible_transcript=[item], metadata={}, game_id="g", scenario_id="s",
    )


def _decision(agent, state):
    beliefs = agent._persuasion_beliefs(state)
    control = agent._control(state, beliefs, agent._persuasion_evidence(state, beliefs), "persuasion")
    return agent._persuasion_buy_decision(state, control)


class PersuasionTextIntentTests(unittest.TestCase):
    def test_all_frozen_live_templates_and_replay_counts(self) -> None:
        replay = {"yes": 0, "no": 0}
        for count, expected, message in LIVE_TEXT_TEMPLATES:
            with self.subTest(message=message):
                self.assertEqual(persuasion_text_intent(message), expected)
            replay[expected] += count

        self.assertEqual(replay, {"yes": 101, "no": 79})
        self.assertEqual(sum(replay.values()), 180)

    def test_live_translation_replay_preserves_all_frozen_raw_messages(self) -> None:
        replayed = 0
        for count, expected, message in LIVE_TEXT_TEMPLATES:
            game = fixtures.persuasion_buyer_decision()
            game["game_state"]["seller_message_type"] = "text"
            game["game_state"]["seller_message"] = message
            item = to_game_state(game).visible_transcript[-1]

            self.assertEqual(item["free_text_message"], message)
            self.assertIsNone(item["buy_no_buy"])
            self.assertEqual(persuasion_text_intent(item["free_text_message"]), expected)
            replayed += count

        self.assertEqual(replayed, 180)

    def test_negation_and_historical_pass_language_are_ordered_safely(self) -> None:
        self.assertEqual(persuasion_text_intent("I do not recommend buying this product."), "no")
        self.assertEqual(
            persuasion_text_intent(
                "I recommend buying this product. Your prior passes revealed nothing; buy now."
            ),
            "yes",
        )
        self.assertIsNone(persuasion_text_intent("The buyer passed previously; here are the available facts."))

    def test_ambiguous_or_conflicting_text_does_not_create_a_buy(self) -> None:
        for message in ("Ordinary unit this round.", "Maybe.", "", None):
            with self.subTest(message=message):
                self.assertIsNone(persuasion_text_intent(message))
        self.assertEqual(
            persuasion_text_intent("I recommend buying this product, but I do not recommend buying this product."),
            "no",
        )


class PersuasionTextStanceCandidateTests(unittest.TestCase):
    def test_candidate_is_default_off_and_has_an_isolated_entry_point(self) -> None:
        baseline = MyAgent(seed=1)
        candidate = PersuasionTextStanceCandidate(
            seed=1, use_persuasion_platt=True, persuasion_explore=True,
            use_deceptive_seller_guard=True,
        )
        self.assertFalse(baseline.use_persuasion_text_stance)
        self.assertTrue(candidate.use_persuasion_text_stance)
        self.assertFalse(candidate.use_persuasion_platt)
        self.assertFalse(candidate.persuasion_explore)
        self.assertFalse(candidate.use_deceptive_seller_guard)

    def test_missing_structured_stance_uses_text_only_for_candidate(self) -> None:
        state = _state(text="I recommend buying this product.")
        self.assertEqual(_decision(MyAgent(seed=1), state), "no")
        self.assertEqual(_decision(PersuasionTextStanceCandidate(seed=1), state), "yes")
        self.assertEqual(state.visible_transcript[0]["free_text_message"], "I recommend buying this product.")
        self.assertIsNone(state.visible_transcript[0]["buy_no_buy"])

    def test_structured_stance_has_precedence_over_conflicting_text(self) -> None:
        state = _state(text="I recommend buying this product.", structured="no")
        self.assertEqual(_decision(PersuasionTextStanceCandidate(seed=1), state), "no")

    def test_binary_missing_stance_is_unchanged(self) -> None:
        state = _state(text="I recommend buying this product.", message_type="binary")
        self.assertEqual(_decision(MyAgent(seed=1), state), "no")
        self.assertEqual(_decision(PersuasionTextStanceCandidate(seed=1), state), "no")

    def test_negative_and_ambiguous_text_keep_safe_decline(self) -> None:
        candidate = PersuasionTextStanceCandidate(seed=1)
        self.assertEqual(_decision(candidate, _state(text="I'd hold off this round, not a strong one.")), "no")
        self.assertEqual(_decision(candidate, _state(text="Ordinary unit this round.")), "no")

    def test_ambiguous_current_text_does_not_reuse_a_prior_round_buy(self) -> None:
        state = _state(text="Ordinary unit this round.")
        state.round = 2
        state.visible_transcript.insert(0, {
            "round": 1, "role": "seller", "action_type": "message",
            "buy_no_buy": None, "structured": {},
            "free_text_message": "I recommend buying this product.",
        })
        state.visible_transcript[-1]["round"] = 2

        self.assertEqual(_decision(PersuasionTextStanceCandidate(seed=1), state), "no")

    def test_parsed_historical_yes_updates_revealed_high_and_low_evidence(self) -> None:
        state = _state(text="Ordinary unit this round.")
        state.round = 3
        state.visible_transcript = [
            {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
            {"round": 1, "role": "seller", "action_type": "message", "buy_no_buy": None,
             "structured": {}, "free_text_message": "I recommend buying this product."},
            {"round": 1, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": "yes"},
            {"round": 2, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
            {"round": 2, "role": "seller", "action_type": "message", "buy_no_buy": None,
             "structured": {}, "free_text_message": "This is a buy."},
            {"round": 2, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": "yes"},
            {"round": 3, "role": "seller", "action_type": "message", "buy_no_buy": None,
             "structured": {}, "free_text_message": "Ordinary unit this round."},
        ]
        baseline = MyAgent(seed=1)._persuasion_beliefs(state)
        candidate = PersuasionTextStanceCandidate(seed=1)._persuasion_beliefs(state)

        self.assertEqual(baseline["prior_visible_yes_on_high"], 0.0)
        self.assertEqual(baseline["prior_visible_yes_on_low"], 0.0)
        self.assertEqual(baseline["transcript_observations"], 0.0)
        self.assertEqual(candidate["prior_visible_yes_on_high"], 1.0)
        self.assertEqual(candidate["prior_visible_yes_on_low"], 1.0)
        self.assertEqual(candidate["transcript_observations"], 2.0)
        self.assertNotEqual(
            candidate["posterior_quality_given_yes"], baseline["posterior_quality_given_yes"]
        )


if __name__ == "__main__":
    unittest.main()
