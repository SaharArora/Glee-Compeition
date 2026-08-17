from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from glee_eval.diagnostics.wave5d_competition_prep import (
    BEHAVIOR_TRACE,
    EXPOSED_OBSERVATIONS,
    EXPOSED_SUMMARY,
    HYPOTHESES,
    analyze_exposed_development,
    validate_evidence,
    verify_source_pins,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research/EVIDENCE/WAVE5D_COMPETITION_PREP.json"
ROUTE = ROOT / "research/ROUTES/WAVE5D_COMPETITION_PREP.md"
CHECKLISTS = ROOT / "research/ROUTES/WAVE5D_MORNING_CHECKLISTS.md"


class Wave5DCompetitionPrepTests(unittest.TestCase):
    def test_only_exact_already_exposed_ledger_reconstructs(self) -> None:
        analysis = analyze_exposed_development(ROOT)
        self.assertEqual(
            analysis["input_classification"],
            "previously_exposed_development_reuse_not_untouched_confirmation",
        )
        self.assertEqual(analysis["input_rows"], 900)

        with tempfile.TemporaryDirectory() as directory:
            replica = Path(directory)
            target = replica / EXPOSED_OBSERVATIONS
            target.parent.mkdir(parents=True)
            target.write_bytes((ROOT / EXPOSED_OBSERVATIONS).read_bytes() + b"\n")
            summary = replica / EXPOSED_SUMMARY
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_bytes((ROOT / EXPOSED_SUMMARY).read_bytes())
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                analyze_exposed_development(replica)

    def test_family_role_and_persuasion_tradeoff_are_exact(self) -> None:
        analysis = analyze_exposed_development(ROOT)
        cells = analysis["by_family_role"]
        self.assertEqual(set(cells), {
            "bargaining:player_1",
            "bargaining:player_2",
            "negotiation:buyer",
            "negotiation:seller",
            "persuasion:buyer",
            "persuasion:seller",
        })
        self.assertAlmostEqual(
            cells["bargaining:player_1"]["mean_factorial00_minus_jordan"],
            0.14542648228724525,
        )
        seller = analysis["persuasion_seller"]
        self.assertEqual(seller["n"], 137)
        self.assertEqual(seller["factorial00_losses"], 67)
        self.assertEqual(seller["factorial00_wins"], 0)
        self.assertEqual(seller["ties"], 70)
        self.assertTrue(seller["all_non_ties_favor_jordan"])
        self.assertAlmostEqual(seller["mean_jordan_minus_factorial00"], 0.0572992700729927)

    def test_source_and_decision_surface_pins_are_closed(self) -> None:
        pins = verify_source_pins(ROOT)
        self.assertEqual(len(pins), 3)
        self.assertEqual(len(BEHAVIOR_TRACE), 6)
        self.assertEqual(
            {(row["family"], tuple(row["roles"])) for row in BEHAVIOR_TRACE},
            {
                ("bargaining", ("player_1", "player_2")),
                ("negotiation", ("buyer", "seller")),
                ("persuasion", ("seller",)),
                ("persuasion", ("buyer",)),
            },
        )

    def test_exactly_two_unimplemented_falsifiable_hypotheses(self) -> None:
        self.assertEqual(len(HYPOTHESES), 2)
        self.assertEqual(
            {item["status"] for item in HYPOTHESES},
            {"hypothesis_only_unimplemented"},
        )
        for item in HYPOTHESES:
            for field in (
                "exact_code_delta",
                "theory",
                "eligible_cells",
                "failure_modes",
                "allowed_development_data",
                "untouched_confirmation",
                "offline_kill_check",
                "future_live_promotion_criterion",
            ):
                self.assertTrue(item[field], (item["id"], field))

    def test_durable_evidence_reconstructs_and_keeps_scientific_ceiling(self) -> None:
        validate_evidence(ROOT, EVIDENCE)
        payload = json.loads(EVIDENCE.read_text())
        self.assertEqual(
            payload["evidence_class"],
            "hypothesis_generation_from_previously_exposed_development_rows",
        )
        self.assertIn("no new payoff", payload["strict_evidence_ceiling"])
        self.assertIn("underidentified", payload["persuasion_seller_tradeoff"]["causal_status"])

    def test_morning_checklists_are_frozen_but_not_authorization(self) -> None:
        text = CHECKLISTS.read_text()
        self.assertIn("not authorized by Wave 5D", text)
        self.assertIn("f2a1bb5afe6f83c3a8a03201a0e5939f748ecda9", text)
        self.assertIn("bce578597dbfacf2ebca38399edb41a5dde2f936", text)
        self.assertIn("active_games==0", text)
        self.assertIn("--per-family-games 100 --concurrency 3", text)
        self.assertIn("--expected-per-family 100", text)
        self.assertIn("5,000 microusd", text)
        self.assertIn("exactly `$1.00`", text)
        self.assertIn("NO-GO_ADAPTER_ABSENT", text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("GLEE_API_KEY=\"", text)
        self.assertNotIn("OPENAI_API_KEY=\"", text)
        self.assertIn("hypothesis_only_unimplemented", ROUTE.read_text())


if __name__ == "__main__":
    unittest.main()
