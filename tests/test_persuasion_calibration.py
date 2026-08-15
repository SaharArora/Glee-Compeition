from __future__ import annotations

import unittest

from glee_eval.diagnostics.persuasion import (
    _calibration_slice,
    _grouped_calibration,
    _purchase_channel_stats,
)


def _event(history, round_number=4):
    return {"round": round_number, "transcript_so_far": history}


class EvidenceChannelAuditTests(unittest.TestCase):
    def test_purchase_counts_distinguish_yes_and_no_recommendations(self) -> None:
        history = [
            {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
            {"round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            {"round": 1, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": "yes"},
            {"round": 2, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
            {"round": 2, "role": "seller", "action_type": "recommendation", "buy_no_buy": "no"},
            {"round": 2, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": "yes"},
        ]

        stats = _purchase_channel_stats(_event(history))

        self.assertEqual(stats["prior_purchases"], 2)
        self.assertEqual(stats["prior_high_quality_purchases"], 1)
        self.assertEqual(stats["prior_purchases_after_yes"], 1)
        self.assertEqual(stats["prior_high_quality_after_yes"], 1)
        self.assertEqual(stats["prior_purchases_after_no"], 1)
        self.assertEqual(stats["prior_purchases_with_unknown_recommendation"], 0)
        self.assertEqual(stats["purchase_recommendation_alignment"], "contains_after_no")

    def test_current_round_outcome_is_excluded(self) -> None:
        current = [
            {"round": 4, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
            {"round": 4, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            {"round": 4, "role": "buyer", "action_type": "buy_decision", "buy_no_buy": "yes"},
        ]

        stats = _purchase_channel_stats(_event(current))

        self.assertEqual(stats["prior_purchases"], 0)
        self.assertEqual(stats["purchase_recommendation_alignment"], "no_purchases")

    def test_ingested_raw_shape_is_audited(self) -> None:
        history = [
            {"round": 1, "role": "nature", "action_type": "nature_quality", "raw": {"round_quality": "high-quality"}},
            {"round": 1, "role": "seller", "action_type": "recommendation", "raw": {"decision": "yes"}},
            {"round": 1, "role": "buyer", "action_type": "buy_decision", "raw": {"decision": "yes"}},
        ]

        stats = _purchase_channel_stats(_event(history))

        self.assertEqual(stats["prior_high_quality_after_yes"], 1)
        self.assertEqual(stats["purchase_recommendation_alignment"], "all_after_yes")

    def test_calibration_slices_report_brier_and_do_not_mix_channels(self) -> None:
        rows = [
            {"predicted": 0.6, "was_high_quality": 1, "evidence_channel": "market_statistics"},
            {"predicted": 0.8, "was_high_quality": 1, "evidence_channel": "transcript_history"},
            {"predicted": 0.7, "was_high_quality": 0, "evidence_channel": "transcript_history"},
        ]

        grouped = _grouped_calibration(rows, "evidence_channel", (0.0, 0.5, 1.0))

        self.assertEqual(grouped["market_statistics"]["n"], 1)
        self.assertEqual(grouped["transcript_history"]["n"], 2)
        self.assertAlmostEqual(_calibration_slice(rows, (0.0, 0.5, 1.0))["brier_score"], 0.23)


if __name__ == "__main__":
    unittest.main()
