from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.live.episodes import main, reconstruct_live_episodes


def _row(game_id: str, family: str, player: str, phase: str, state: dict, action: dict) -> dict:
    return {"game_id": game_id, "game_family": family, "your_player": player,
            "phase": phase, "game_state": state, "action": action}


class LiveEpisodeTests(unittest.TestCase):
    def _convert(self, rows: list[dict]):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "observations.jsonl"
            source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            return reconstruct_live_episodes(source)

    def test_opponent_terminal_gap_is_not_coerced(self) -> None:
        rows = [_row("b1", "bargaining", "player_1", "offer",
                     {"round": 12, "max_rounds": 12, "money_to_divide": 100},
                     {"alice_gain": 50, "bob_gain": 50})]
        episodes, summary = self._convert(rows)
        self.assertEqual(episodes[0]["terminal_status"], "indeterminate")
        self.assertIsNone(episodes[0]["normalized_payoff"])
        self.assertEqual(episodes[0]["missing_fields"], ["terminal_result"])
        self.assertEqual(summary["comparable_payoff_status"], "unavailable")

    def test_persuasion_final_no_is_exact(self) -> None:
        rows = [_row("p-no", "persuasion", "player_2", "buyer_decision",
                     {"round": 20, "total_rounds": 20, "product_price": 100,
                      "player_2_role": "buyer", "buyer_total_payoff": 200},
                     {"decision": "no"})]
        episodes, summary = self._convert(rows)
        self.assertEqual(episodes[0]["terminal_status"], "reconstructed")
        self.assertEqual(episodes[0]["normalized_payoff"], 0.1)
        self.assertEqual(episodes[0]["payoff_bounds"], [0.1, 0.1])
        self.assertEqual(summary["comparable_payoff_status"], "available")

    def test_persuasion_final_yes_has_bounds_but_is_indeterminate(self) -> None:
        rows = [_row("p-yes", "persuasion", "player_2", "buyer_decision",
                     {"round": 20, "total_rounds": 20, "product_price": 100,
                      "player_2_role": "buyer", "buyer_total_payoff": 200, "u": 0, "v": 400},
                     {"decision": "yes"})]
        episodes, summary = self._convert(rows)
        self.assertEqual(episodes[0]["terminal_status"], "indeterminate")
        self.assertIsNone(episodes[0]["normalized_payoff"])
        self.assertEqual(episodes[0]["payoff_bounds"], [0.05, 0.25])
        self.assertEqual(episodes[0]["missing_fields"], ["terminal_product_quality"])
        self.assertEqual(summary["families"]["persuasion"]["comparable_payoff_status"], "unavailable")

    def test_cli_writes_one_row_per_game_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "observations.jsonl", Path(tmp) / "out"
            row = _row("n1", "negotiation", "player_1", "decision",
                       {"round": 2, "max_rounds": 10}, {"decision": "WalkAway"})
            source.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
            main(["--observations", str(source), "--output-dir", str(output)])
            self.assertEqual(len((output / "episodes.jsonl").read_text().splitlines()), 1)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["games"], 1)
            self.assertEqual(summary["families"]["negotiation"]["terminal_status_counts"], {"reconstructed": 1})

    def test_negotiation_accept_reconstructs_raw_but_not_comparable_payoff(self) -> None:
        rows = [_row("n-accept", "negotiation", "player_1", "decision",
                     {"round": 2, "max_rounds": 10, "player_1_role": "seller",
                      "player_1_value": 80, "last_offer": {"price": 95}},
                     {"decision": "AcceptOffer"})]
        episodes, summary = self._convert(rows)
        self.assertEqual(episodes[0]["terminal_status"], "reconstructed")
        self.assertEqual(episodes[0]["raw_payoff"], 15)
        self.assertIsNone(episodes[0]["normalized_payoff"])
        self.assertEqual(episodes[0]["missing_fields"], ["product_price_order"])
        self.assertEqual(summary["comparable_payoff_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
