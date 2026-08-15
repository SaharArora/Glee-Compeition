from __future__ import annotations

import unittest

from glee_eval.diagnostics.persuasion import (
    _calibration_slice,
    _evaluate_platt_axis,
    _game_cluster_bootstrap,
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


class PlattEvaluationTests(unittest.TestCase):
    @staticmethod
    def _rows():
        rows = []
        for partition in ("fit", "holdout"):
            # Raw 0.2 is under-confident for a 0.4 event; raw 0.8 is
            # under-confident for a 0.9 event.  The same fixed construction in
            # fit and holdout gives the preregistered map signal to recover.
            for raw, positives, total in ((0.2, 4, 10), (0.8, 9, 10)):
                for index in range(total):
                    rows.append(
                        {
                            "predicted": raw,
                            "was_high_quality": int(index < positives),
                            "game_id": f"{partition}-{raw}-{index}",
                            "model_partition": partition,
                            "config_partition": partition,
                        }
                    )
        return rows

    def test_platt_candidate_reports_both_declared_endpoints(self) -> None:
        result = _evaluate_platt_axis(
            self._rows(), "model", bootstrap_seed=7, bootstrap_replicates=200
        )

        self.assertEqual(result["fit_n"], 20)
        self.assertEqual(result["holdout_n"], 20)
        self.assertLess(result["brier_delta"]["mean"], 0.0)
        self.assertLess(result["log_loss_delta"]["mean"], 0.0)
        # Twenty one-row clusters are deliberately too few for the confidence
        # bound to clear zero even though both point estimates improve.
        self.assertFalse(result["success"])

    def test_game_cluster_bootstrap_is_deterministic(self) -> None:
        games = {
            "a": (2, -0.2, -0.4),
            "b": (1, -0.05, -0.1),
            "c": (3, -0.3, -0.6),
        }

        first = _game_cluster_bootstrap(games, seed=11, replicates=50)
        second = _game_cluster_bootstrap(games, seed=11, replicates=50)

        self.assertEqual(first, second)
        self.assertLess(first["brier"][1], 0.0)
        self.assertLess(first["log_loss"][1], 0.0)


if __name__ == "__main__":
    unittest.main()
