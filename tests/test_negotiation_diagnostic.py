from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from glee_eval.diagnostics.negotiation import negotiation_diagnostic
from glee_eval.storage.trajectories import write_jsonl


class NegotiationDiagnosticTests(unittest.TestCase):
    def test_negotiation_diagnostic_ranks_candidate_causes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "data"
            config = {"seller_value": 0.7, "buyer_value": 1.1, "product_price_order": 1000, "max_rounds": 6}
            write_jsonl(
                data_dir / "processed" / "games.jsonl",
                [
                    {
                        "game_id": "n1",
                        "game_family": "negotiation",
                        "configuration": {"game_args": config},
                        "terminal_outcome": {"result": "AcceptOffer", "normalized_price": 0.75, "agreement_round": 1},
                        "player_1_payoff": 0.05,
                        "player_2_payoff": 0.35,
                    }
                ],
            )

            report = negotiation_diagnostic(data_dir=data_dir, output_dir=root / "diag", support_index={"buckets": {}})

            self.assertTrue(report["ranked_candidate_causes"])
            self.assertTrue((root / "diag" / "negotiation_diagnostic.md").exists())


if __name__ == "__main__":
    unittest.main()
