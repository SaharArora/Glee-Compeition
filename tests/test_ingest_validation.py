from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.data.ingest import ingest, parse_game_dir, terminal_bargaining, terminal_negotiation, terminal_persuasion


def write_game(root: Path, source: str, family: str, game_id: str, config: dict, csv_text: str) -> Path:
    game_dir = root / "Data" / source / family / game_id[0] / game_id[1] / game_id[2] / game_id
    game_dir.mkdir(parents=True)
    (game_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (game_dir / "game.csv").write_text(csv_text, encoding="utf-8")
    return game_dir


class IngestValidationTests(unittest.TestCase):
    def test_bargaining_payoff_reconstruction(self) -> None:
        config = {
            "game_type": "bargaining",
            "player_1_args": {"public_name": "Alice"},
            "player_2_args": {"public_name": "Bob"},
            "game_args": {"money_to_divide": 100, "max_rounds": 6, "delta_1": 0.9, "delta_2": 1.0},
        }
        rows = [
            {"alice_gain": "60", "bob_gain": "40", "player": "Alice", "round": "1", "decision": ""},
            {"alice_gain": "", "bob_gain": "", "player": "Bob", "round": "1", "decision": "accept"},
        ]
        terminal = terminal_bargaining(rows, config)
        self.assertEqual(terminal["result"], "accept")
        self.assertAlmostEqual(terminal["player_1_payoff"], 0.6)
        self.assertAlmostEqual(terminal["player_2_payoff"], 0.4)

    def test_negotiation_payoff_reconstruction(self) -> None:
        config = {
            "game_type": "negotiation",
            "player_1_args": {"public_name": "Alice"},
            "player_2_args": {"public_name": "Bob"},
            "game_args": {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000},
        }
        rows = [
            {"product_price": "900", "player": "Alice", "round": "1", "decision": ""},
            {"product_price": "", "player": "Bob", "round": "1", "decision": "AcceptOffer"},
        ]
        terminal = terminal_negotiation(rows, config)
        self.assertEqual(terminal["result"], "AcceptOffer")
        self.assertAlmostEqual(terminal["player_1_payoff"], 0.2)
        self.assertAlmostEqual(terminal["player_2_payoff"], 0.2)

    def test_persuasion_payoff_reconstruction(self) -> None:
        config = {
            "game_type": "persuasion",
            "player_1_args": {"public_name": "Alice"},
            "player_2_args": {"public_name": "Bob"},
            "game_args": {"product_price": 100, "total_rounds": 2, "v": 1.2, "c": 0.0},
        }
        rows = [
            {"round_quality": "high-quality", "product_worth": "120", "player": "Nature", "round": "1"},
            {"player": "Alice", "round": "1", "decision": "yes"},
            {"player": "Bob", "round": "1", "decision": "yes"},
            {"round_quality": "low-quality", "product_worth": "0", "player": "Nature", "round": "2"},
            {"player": "Alice", "round": "2", "decision": "no"},
            {"player": "Bob", "round": "2", "decision": "no"},
        ]
        terminal = terminal_persuasion(rows, config)
        self.assertEqual(terminal["sales"], 1)
        self.assertAlmostEqual(terminal["player_1_payoff"], 0.5)
        self.assertAlmostEqual(terminal["player_2_payoff"], 0.1)

    def test_parse_and_ingest_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {
                "game_type": "bargaining",
                "experiment_name": "fixture",
                "player_1_args": {"public_name": "Alice", "model_name": "m1"},
                "player_2_args": {"public_name": "Bob", "model_name": "m2"},
                "game_args": {"money_to_divide": 100, "max_rounds": 2, "complete_information": True, "messages_allowed": False, "delta_1": 1.0, "delta_2": 1.0},
            }
            game_dir = write_game(
                root,
                "llm_vs_llm",
                "bargaining",
                "ABC123",
                config,
                "alice_gain,bob_gain,player,round,decision\n60,40,Alice,1,\n,,Bob,1,accept\n",
            )
            game, events = parse_game_dir(game_dir, root)
            self.assertEqual(game["game_family"], "bargaining")
            self.assertEqual(len(events), 2)
            result = ingest(glee_root=root, output_dir=root / "out", limit=1)
            self.assertEqual(result.report["games_parsed"], 1)
            self.assertEqual(result.report["events_parsed"], 2)


if __name__ == "__main__":
    unittest.main()

