from __future__ import annotations

import unittest

from glee_eval.diagnostics.language import (
    FEATURES,
    _stratified_difference,
    message_features,
    message_stance,
)


class FeatureExtractionTests(unittest.TestCase):
    def test_hedging_is_detected_in_its_common_forms(self) -> None:
        for text in (
            "I can't guarantee the quality.",
            "It might be high quality.",
            "This could be a good product, possibly.",
        ):
            self.assertTrue(message_features(text)["hedged"], text)

    def test_social_proof_is_detected(self) -> None:
        self.assertTrue(message_features("Many of my previous buyers were happy.")["social_proof"])
        self.assertFalse(message_features("This product costs $10,000.")["social_proof"])

    def test_value_and_probability_disclosure_are_separate(self) -> None:
        features = message_features("There is a 50% chance it is high quality, valued at $12,500.")

        self.assertTrue(features["discloses_probability"])
        self.assertTrue(features["discloses_value"])

    def test_long_message_uses_the_real_median(self) -> None:
        self.assertFalse(message_features("short")["long_message"])
        self.assertTrue(message_features("x" * 300)["long_message"])

    def test_every_declared_feature_is_produced(self) -> None:
        features = message_features("Anything at all.")

        self.assertEqual(set(features), set(FEATURES))
        for value in features.values():
            self.assertIn(value, (0, 1))

    def test_empty_and_missing_messages_are_safe(self) -> None:
        for text in ("", None):
            features = message_features(text)
            self.assertEqual(set(features), set(FEATURES))


class StanceTests(unittest.TestCase):
    """Stance is a control variable, so a miss contaminates strata."""

    def test_our_own_decline_template_is_read_as_discouragement(self) -> None:
        """The regression: requiring a literal "pass on" read this as an endorsement."""

        self.assertEqual(message_stance(message_features("I recommend passing on this product.")), "discourage")

    def test_endorsement_and_discouragement_are_distinguished(self) -> None:
        self.assertEqual(message_stance(message_features("I recommend buying this product.")), "endorse")
        self.assertEqual(message_stance(message_features("I would not buy this one.")), "discourage")

    def test_discouragement_wins_over_a_co_occurring_endorsement_word(self) -> None:
        text = "I usually recommend our products, but I would pass on this one."

        self.assertEqual(message_stance(message_features(text)), "discourage")

    def test_a_message_with_neither_is_neutral(self) -> None:
        self.assertEqual(message_stance(message_features("This product costs $10,000.")), "neutral")


class StratifiedDifferenceTests(unittest.TestCase):
    def _rows(self, effect: float, strata: int = 4, per_cell: int = 50) -> list[dict]:
        rows = []
        for s in range(strata):
            base = 0.3 + 0.1 * s  # different baseline per stratum
            for present in (0, 1):
                rate = base + (effect if present else 0.0)
                buys = round(rate * per_cell)
                for i in range(per_cell):
                    rows.append(
                        {
                            "bought": 1 if i < buys else 0,
                            "stratum": f"s{s}",
                            "features": {"feat": present},
                        }
                    )
        return rows

    def test_it_recovers_a_known_effect(self) -> None:
        result = _stratified_difference(self._rows(0.2), "feat", ("stratum",))

        self.assertTrue(result["estimable"])
        self.assertAlmostEqual(result["effect_on_purchase_rate"], 0.2, places=2)
        self.assertEqual(result["strata_used"], 4)

    def test_a_stratum_with_no_variation_is_dropped_and_counted(self) -> None:
        rows = self._rows(0.2)
        rows += [{"bought": 1, "stratum": "constant", "features": {"feat": 1}} for _ in range(30)]

        result = _stratified_difference(rows, "feat", ("stratum",))

        self.assertEqual(result["strata_used"], 4)
        self.assertEqual(result["strata_dropped"], 1)

    def test_baseline_differences_between_strata_do_not_leak_into_the_effect(self) -> None:
        """Pooling raw rates instead of within-stratum differences would bias this."""

        result = _stratified_difference(self._rows(0.0), "feat", ("stratum",))

        self.assertAlmostEqual(result["effect_on_purchase_rate"], 0.0, places=2)

    def test_nothing_estimable_is_reported_rather_than_returning_zero(self) -> None:
        rows = [{"bought": 1, "stratum": "a", "features": {"feat": 1}} for _ in range(20)]

        result = _stratified_difference(rows, "feat", ("stratum",))

        self.assertFalse(result["estimable"])
        self.assertNotIn("effect_on_purchase_rate", result)


if __name__ == "__main__":
    unittest.main()
