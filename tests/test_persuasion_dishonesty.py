from __future__ import annotations

import unittest

from glee_eval.data.schemas import GameState
from glee_eval.diagnostics.persuasion_dishonesty import past_dishonesty_evidence, summarize_axis


def _state(transcript, *, round_number=3, public_parameters=None):
    return GameState(
        scenario_id="s", game_id="g", game_family="persuasion", role="buyer",
        round=round_number, horizon=8, public_parameters=public_parameters or {}, private_parameters={},
        visible_transcript=transcript, valid_action_schema={"kind": "buy_decision"},
    )


class PastDishonestyEvidenceTests(unittest.TestCase):
    def test_counts_a_prior_visible_lie(self) -> None:
        state = _state([
            {"round": 1, "role": "nature", "action_type": "nature_quality", "raw": {"round_quality": "low-quality"}},
            {"round": 1, "role": "seller", "action_type": "recommendation", "raw": {"decision": "yes"}},
            {"round": 2, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
            {"round": 2, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
        ])
        evidence = past_dishonesty_evidence(state)
        self.assertEqual(evidence["prior_yes_low"], 1)
        self.assertEqual(evidence["prior_yes_high"], 1)

    def test_current_and_future_quality_never_enter_counts(self) -> None:
        state = _state([
            {"round": 1, "role": "nature", "action_type": "nature_quality", "quality": "high-quality"},
            {"round": 1, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            {"round": 3, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
            {"round": 3, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
            {"round": 4, "role": "nature", "action_type": "nature_quality", "quality": "low-quality"},
            {"round": 4, "role": "seller", "action_type": "recommendation", "buy_no_buy": "yes"},
        ])
        evidence = past_dishonesty_evidence(state)
        self.assertEqual(evidence["prior_yes_total"], 1)
        self.assertEqual(evidence["prior_yes_low"], 0)

    def test_myopic_market_statistics_do_not_impute_seller_lies(self) -> None:
        evidence = past_dishonesty_evidence(_state([
            {"round": 3, "action_type": "market_statistics", "products_sold": 2, "high_quality_sold": 0}
        ]))
        self.assertFalse(evidence["observable"])
        self.assertIsNone(evidence["prior_yes_low"])

    def test_myopic_first_round_is_unobservable_even_before_statistics_exist(self) -> None:
        evidence = past_dishonesty_evidence(_state([], public_parameters={"is_myopic": True}))
        self.assertFalse(evidence["observable"])


def _row(game, *, lie, predicted, high, surplus, buy=True, model="holdout", config="holdout"):
    return {
        "game_id": game, "observable": True, "prior_yes_low": int(lie),
        "predicted": predicted, "was_high_quality": int(high), "realized_surplus": surplus,
        "value_destroying": int(surplus < 0), "agent_would_buy": buy,
        "model_partition": model, "config_partition": config,
        "pvc_regime": "p=.5|v=2|c=0", "round_bucket": "4-6",
        "memory_mode": "persistent", "seller_message_type": "text",
        "evidence_count_bucket": "1",
    }


class HoldoutSummaryTests(unittest.TestCase):
    def test_reach_and_holdout_summary_apply_preregistered_thresholds(self) -> None:
        rows = []
        for i in range(220):
            rows.append(_row(f"lie-{i % 35}", lie=True, predicted=.8, high=False, surplus=-1.0))
        for i in range(220):
            rows.append(_row(f"clean-{i}", lie=False, predicted=.8, high=True, surplus=.4))
        summary = summarize_axis(rows, "model")
        self.assertEqual(summary["reachable_agent_buy_decisions"], 220)
        self.assertEqual(summary["reachable_games"], 35)
        self.assertTrue(summary["passes_all_kill_criteria"])

    def test_non_holdout_rows_do_not_enter_summary(self) -> None:
        rows = [_row("fit", lie=True, predicted=.9, high=False, surplus=-1, model="fit")]
        summary = summarize_axis(rows, "model")
        self.assertEqual(summary["eligible_observable_yes_decisions"], 0)
        self.assertFalse(summary["passes_all_kill_criteria"])

    def test_matching_catches_config_mix_reversal(self) -> None:
        rows = []
        # Within both configs, lie rows are better calibrated and more valuable.
        # The unmatched aggregate points the other way only because lie rows are
        # concentrated in the hard config.
        specs = (
            ("hard", 300, 10, .4, .2, .2, -.2),
            ("easy", 10, 300, 1.0, .8, 1.2, .8),
        )
        for regime, lie_n, clean_n, lie_high, clean_high, lie_value, clean_value in specs:
            for i in range(lie_n):
                row = _row(
                    f"{regime}-lie-{i}", lie=True, predicted=.6,
                    high=i < lie_n * lie_high, surplus=lie_value,
                )
                row["pvc_regime"] = regime
                rows.append(row)
            for i in range(clean_n):
                row = _row(
                    f"{regime}-clean-{i}", lie=False, predicted=.6,
                    high=i < clean_n * clean_high, surplus=clean_value,
                )
                row["pvc_regime"] = regime
                rows.append(row)
        summary = summarize_axis(rows, "model")
        self.assertTrue(summary["unmatched_direction"]["positive_overconfidence_after_prior_lie"])
        self.assertTrue(summary["unmatched_direction"]["worse_value_outcomes_after_prior_lie"])
        self.assertLess(summary["matched"]["lie_minus_no_lie_overconfidence"], 0)
        self.assertGreater(summary["matched"]["lie_minus_no_lie_realized_surplus"], 0)
        self.assertFalse(summary["passes_all_kill_criteria"])


if __name__ == "__main__":
    unittest.main()
