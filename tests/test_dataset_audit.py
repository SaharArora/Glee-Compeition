from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from glee_eval.data.dataset_audit import audit_processed, audit_records, build_support_index, support_lookup
from glee_eval.storage.trajectories import write_jsonl


class DatasetAuditTests(unittest.TestCase):
    def test_tiny_dataset_is_not_empirical_foundation(self) -> None:
        games = [
            {
                "game_id": "g1",
                "game_family": "bargaining",
                "source": "fixture",
                "config_id": "c1",
                "configuration": {"game_args": {"money_to_divide": 100}},
                "terminal_outcome": {"result": "accept"},
                "player_1_payoff": 0.6,
                "player_2_payoff": 0.4,
                "player_1_model": "m1",
                "player_2_model": "m2",
            }
        ]
        events = [
            {
                "event_id": "e1",
                "game_id": "g1",
                "game_family": "bargaining",
                "source": "fixture",
                "config_id": "c1",
                "role": "player_1",
                "round": 1,
                "transcript_so_far": [],
                "action_type": "offer",
                "numeric_action": 60,
                "configuration": {"money_to_divide": 100},
                "private_information": {"delta_1": 1.0},
                "public_parameters": {"money_to_divide": 100},
                "terminal_outcome": {"result": "accept"},
                "player_payoff": 0.6,
                "opponent_payoff": 0.4,
            }
        ]
        report = audit_records(games, events)
        self.assertEqual(report["strategy_recommendation"]["verdict"], "toy_or_smoke_dataset")
        self.assertEqual(report["empirical_action_support"]["bargaining_offer_share_bins"]["0.6-0.7"], 1)

    def test_audit_processed_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "data" / "processed"
            write_jsonl(processed / "games.jsonl", [])
            write_jsonl(processed / "events.jsonl", [])
            report = audit_processed(root / "data", root / "reports")
            self.assertEqual(report["strategy_recommendation"]["verdict"], "no_processed_dataset")
            self.assertTrue((root / "reports" / "audit.json").exists())
            self.assertTrue((root / "reports" / "audit.md").exists())
            self.assertTrue((root / "reports" / "support_index.json").exists())

    def test_support_lookup_reports_coverage_for_state_action(self) -> None:
        events = [
            {
                "event_id": "e1",
                "game_id": "g1",
                "game_family": "negotiation",
                "role": "seller",
                "round": 1,
                "action_type": "offer",
                "numeric_action": 900,
                "configuration": {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6},
            },
            {
                "event_id": "e2",
                "game_id": "g2",
                "game_family": "negotiation",
                "role": "seller",
                "round": 1,
                "action_type": "offer",
                "numeric_action": 900,
                "configuration": {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6},
            },
        ]
        support_index = build_support_index(events)
        result = support_lookup(
            "negotiation",
            {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6},
            "seller",
            {"action_type": "offer", "numeric_action": 900, "structured": {"product_price": 900}},
            support_index=support_index,
            min_action_support=2,
        )
        self.assertEqual(result["action_n"], 2)
        self.assertGreater(result["coverage_score"], 0.7)


if __name__ == "__main__":
    unittest.main()
