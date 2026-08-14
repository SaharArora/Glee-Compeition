from __future__ import annotations

import unittest

from glee_eval.diagnostics.language import message_features, message_stance
from glee_eval.live import fixtures
from glee_eval.live.strategy import LiveStrategy
from glee_eval.population.config_catalogue import ConfigCatalogue
from glee_eval.population.sampler import sample_scenario
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import MyAgent
from my_agents.message_composer import PersuasionMessageComposer, shadow_record

#: Features whose sign flipped between high- and low-quality rounds in step 3.
#: They proxy the seller's private intent rather than moving the buyer, so a
#: composed message must never carry one.
SIGN_FLIPPING = {"gain_frame", "discloses_value", "asks_question"}


def _present(text: str) -> set[str]:
    return {name for name, value in message_features(text).items() if value}


class ComposedFeatureTests(unittest.TestCase):
    """The composer's claim is that it carries specific measured features.

    Three drafts failed this: "worth buying" tripped `discloses_value`, "advise
    against" matched no discouragement pattern so the decline read as neutral, and
    a bare count carried no social proof at all. Asserting the vectors is what
    turns the docstring's claim into something checked.
    """

    def setUp(self) -> None:
        self.composer = PersuasionMessageComposer()

    def test_an_endorsement_is_confident_and_reads_as_an_endorsement(self) -> None:
        composed = self.composer.compose(True)

        self.assertIn("confident", _present(composed.text))
        self.assertEqual(message_stance(composed.features), "endorse")

    def test_a_decline_is_confident_and_reads_as_a_discouragement(self) -> None:
        composed = self.composer.compose(False)

        self.assertIn("confident", _present(composed.text))
        self.assertEqual(message_stance(composed.features), "discourage")

    def test_social_proof_is_carried_when_there_are_sales_behind_it(self) -> None:
        with_history = self.composer.compose(True, market_sold=6, market_high_quality=5)
        without_high = self.composer.compose(True, market_sold=4, market_high_quality=0)

        self.assertIn("social_proof", _present(with_history.text))
        self.assertIn("social_proof", _present(without_high.text))

    def test_no_social_proof_is_claimed_without_sales(self) -> None:
        """Claiming satisfied buyers with no sales would be a fabrication."""

        composed = self.composer.compose(True, market_sold=0)

        self.assertNotIn("social_proof", _present(composed.text))

    def test_no_composed_message_ever_hedges(self) -> None:
        for recommend in (True, False):
            for sold, high in ((0, 0), (4, 0), (9, 7)):
                text = self.composer.compose(recommend, market_sold=sold, market_high_quality=high).text
                self.assertNotIn("hedged", _present(text))

    def test_no_composed_message_carries_a_sign_flipping_feature(self) -> None:
        for recommend in (True, False):
            for sold, high in ((0, 0), (1, 0), (4, 0), (9, 7), (50, 30)):
                text = self.composer.compose(recommend, market_sold=sold, market_high_quality=high).text
                self.assertEqual(
                    _present(text) & SIGN_FLIPPING,
                    set(),
                    f"recommend={recommend} sold={sold} high={high}: {text!r}",
                )

    def test_messages_stay_short(self) -> None:
        for sold, high in ((0, 0), (9999, 5000)):
            text = self.composer.compose(True, market_sold=sold, market_high_quality=high).text
            self.assertNotIn("long_message", _present(text))

    def test_toggling_a_feature_off_removes_it(self) -> None:
        plain = PersuasionMessageComposer(use_social_proof=False, use_confidence=False)

        composed = plain.compose(True, market_sold=9, market_high_quality=7)

        self.assertNotIn("social_proof", _present(composed.text))
        self.assertEqual(composed.text, plain.baseline(True))

    def test_the_baseline_is_what_we_send_today(self) -> None:
        self.assertEqual(self.composer.baseline(True), "I recommend buying this product.")
        self.assertEqual(self.composer.baseline(False), "I recommend passing on this product.")


class ShadowModeTests(unittest.TestCase):
    """Shadow mode must decide and record without changing what is sent."""

    def test_shadow_record_carries_both_arms_with_features(self) -> None:
        record = shadow_record(PersuasionMessageComposer(), True, market_sold=5, market_high_quality=4)

        self.assertEqual(record["mode"], "shadow")
        self.assertIn("features", record["sent"])
        self.assertIn("features", record["would_send"])
        self.assertNotEqual(record["sent"]["text"], record["would_send"]["text"])

    def test_the_record_states_it_has_not_passed_the_gate(self) -> None:
        """It must not be mistakable for a change that cleared the real gate."""

        record = shadow_record(PersuasionMessageComposer(), True)

        self.assertEqual(record["gate_status"], "not_gate_passed_pending_real_data")

    def test_shadow_mode_leaves_the_transmitted_message_unchanged(self) -> None:
        shadow = MyAgent(seed=4, message_mode="shadow")
        plain = MyAgent(seed=4, message_mode="shadow")
        plain.message_composer = PersuasionMessageComposer(use_social_proof=False, use_confidence=False)

        scenario = sample_scenario("persuasion", seed=3, candidate_role="seller", catalogue=ConfigCatalogue({"families": {}}))
        messages = []
        for agent in (shadow, plain):
            episode = run_episode(scenario, agent)
            messages.append(
                [
                    record.action["structured"].get("message")
                    for record in episode.decision_records
                    if record.role == "seller"
                ]
            )

        self.assertEqual(messages[0], messages[1], "shadow mode must not alter the sent message")

    def test_live_mode_does_change_the_transmitted_message(self) -> None:
        scenario = sample_scenario("persuasion", seed=3, candidate_role="seller", catalogue=ConfigCatalogue({"families": {}}))

        sent = {}
        for mode in ("shadow", "live"):
            episode = run_episode(scenario, MyAgent(seed=4, message_mode=mode))
            sent[mode] = [
                record.action["structured"].get("message")
                for record in episode.decision_records
                if record.role == "seller"
            ]

        self.assertNotEqual(sent["shadow"], sent["live"])

    def test_the_experiment_record_is_attached_to_every_seller_action(self) -> None:
        scenario = sample_scenario("persuasion", seed=8, candidate_role="seller", catalogue=ConfigCatalogue({"families": {}}))

        episode = run_episode(scenario, MyAgent(seed=4))

        seller_actions = [r.action for r in episode.decision_records if r.role == "seller"]
        self.assertTrue(seller_actions)
        for action in seller_actions:
            self.assertIn("message_experiment", action["structured"])

    def test_shadow_mode_reaches_the_live_observation_log(self) -> None:
        strategy = LiveStrategy(MyAgent(seed=4), observation_log=None)

        # This fixture's round is low quality, so the agent declines; the point is
        # that whichever way it decides, shadow mode sends the *baseline* wording.
        action = strategy(fixtures.persuasion_seller_message())

        self.assertIn("message", action)
        composer = PersuasionMessageComposer()
        baselines = {composer.baseline(True), composer.baseline(False)}
        composed = {composer.compose(True).text, composer.compose(False).text}
        self.assertIn(action["message"], baselines)
        self.assertNotIn(action["message"], composed)

    def test_default_mode_is_shadow(self) -> None:
        self.assertEqual(MyAgent(seed=1).message_mode, "shadow")


if __name__ == "__main__":
    unittest.main()
