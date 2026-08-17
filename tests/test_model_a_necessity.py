from __future__ import annotations

import math
import unittest

from glee_eval.diagnostics.model_a_necessity import (
    _advance_decision,
    _calibration_fit,
    empirical_crps,
    log_loss,
)


class ModelANecessityMetricTests(unittest.TestCase):
    def test_empirical_crps_matches_pairwise_definition(self) -> None:
        samples = [0.1, 0.4, 0.9]
        observed = 0.5
        direct = sum(abs(value - observed) for value in samples) / len(samples)
        direct -= 0.5 * sum(abs(left - right) for left in samples for right in samples) / len(samples) ** 2
        self.assertAlmostEqual(empirical_crps(samples, observed), direct, places=15)

    def test_log_loss_is_finite_at_probability_boundaries(self) -> None:
        self.assertTrue(math.isfinite(log_loss(0.0, False)))
        self.assertTrue(math.isfinite(log_loss(1.0, True)))

    def test_calibration_recovers_identity_map(self) -> None:
        rows = []
        for probability, positives, total in ((0.2, 20, 100), (0.5, 50, 100), (0.8, 80, 100)):
            rows.extend({"predicted": probability, "outcome": index < positives} for index in range(total))
        fitted = _calibration_fit(rows)
        self.assertAlmostEqual(float(fitted["intercept"]), 0.0, places=8)
        self.assertAlmostEqual(float(fitted["slope"]), 1.0, places=8)

    def test_advance_rule_requires_same_defect_signature(self) -> None:
        released = {
            "source": "released_actor_model_holdout",
            "family": "bargaining",
            "role": "player_1",
            "channel": "offer",
            "interpretable": True,
            "mae": 0.09,
            "central_80_coverage": 0.60,
        }
        live = {**released, "source": "live_terminal_complete", "mae": 0.04, "central_80_coverage": 0.65}
        verdict = _advance_decision([], [released, live])
        self.assertEqual(verdict["status"], "model_a_campaign_warranted")
        self.assertIn(
            ["bargaining", "player_1", "offer", "coverage_low"],
            verdict["replicated_defect_signatures"],
        )

    def test_opposite_discrete_calibration_does_not_replicate(self) -> None:
        common = {
            "family": "negotiation",
            "role": "buyer",
            "channel": "accept",
            "interpretable": True,
        }
        rows = [
            {**common, "source": "released_actor_model_holdout", "calibration_in_the_large": 0.10},
            {**common, "source": "live_terminal_complete", "calibration_in_the_large": -0.10},
        ]
        verdict = _advance_decision(rows, [])
        self.assertEqual(verdict["status"], "deferred_no_demonstrated_incremental_need")


if __name__ == "__main__":
    unittest.main()
