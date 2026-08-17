from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from collections import OrderedDict
from dataclasses import replace

from glee_eval.experiments import factorial_report, preoutcome_manifest
from glee_eval.experiments.factorial import FACTORIAL_ARMS, run_factorial
from glee_eval.experiments.factorial_report import (
    FactorialReportContract,
    build_factorial_report,
    canonical_hash,
    derive_factorial_eligibility,
    validate_synthetic_factorial_report,
)
from glee_eval.experiments.preoutcome_manifest import (
    OUTCOME_ADMISSION_SCHEMA,
    PreOutcomeManifestContract,
    build_preoutcome_manifest,
    scenario_design_sha256,
    support_masks_sha256,
    validate_outcome_admission,
    validate_synthetic_preoutcome_manifest,
)
from glee_eval.experiments.receiver_itt import receiver_envelope_itt_payoff
from glee_eval.experiments.wave5d_paper_design import (
    DESIGNS,
    Design,
    design_envelope,
    effective_sample_size,
    mde_grid,
    minimum_detectable_effect,
    planning_evidence,
    required_clusters,
)
from tests.test_factorial_evaluator import _NoopAgent, _scenario


RECEIVER = {
    "schema": "glee.research.controlled_receiver_contract.v1",
    "environment_id": "wave5d-synthetic-receiver-only",
    "candidate_text_delivered": True,
    "receiver_consumes_candidate_text": True,
    "evidence_class": "infrastructure_only_non_evidence",
    "output_contract": {
        "parser_id": "strict_json_decision_v1",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string", "enum": ["buy", "pass", "refuse"]}
            },
            "required": ["decision"],
        },
        "decision_field": "decision",
        "allowed_decisions": ["buy", "pass"],
        "refusal_decisions": ["refuse"],
    },
}
ARTIFACTS = {
    "schema": "glee.research.factorial_baseline_artifacts.v1",
    "response_model": {"path": "/synthetic/model.json", "sha256": "a" * 64},
    "support_index": {"path": "/synthetic/support.json", "sha256": "b" * 64},
    "receiver_contract": RECEIVER,
}
MODEL_C = {
    "min_support": 30,
    "families": {
        "persuasion": {
            "buckets": {
                "rec=yes": {
                    "probability": 0.7,
                    "trials": 100,
                    "support_quality": 1.0,
                }
            }
        }
    },
}


class _ArtifactNoopAgent(_NoopAgent):
    def factorial_artifact_provenance(self):
        return copy.deepcopy(ARTIFACTS)


def _factories():
    return OrderedDict(
        (arm, lambda context: _ArtifactNoopAgent(context)) for arm in FACTORIAL_ARMS
    )


def _text_scenario(family: str, seed: int, role: str):
    scenario = _scenario(family, seed, role)
    if family != "persuasion":
        return scenario
    public = copy.deepcopy(scenario.public_parameters)
    public["seller_message_type"] = "text"
    return replace(scenario, public_parameters=public)


def _admission(manifest_row: dict, *, missing: bool) -> dict:
    arms = []
    for index, arm in enumerate(FACTORIAL_ARMS):
        is_missing = missing and index == 0
        receiver = {
            "schema": "glee.research.controlled_receiver_envelope.v1",
            "status": "missing" if is_missing else "ok",
            "attempts": 1,
            "request_sha256": "c" * 64,
            "response_sha256": None if is_missing else "d" * 64,
            "parsed_output": None if is_missing else {"decision": "buy"},
            "applied_environment_action": "no" if is_missing else "yes",
            "ordinary_environment_continued": True,
            "terminal_candidate_payoff": 0.25,
        }
        arms.append(
            {
                "arm": arm,
                "included_in_intent_to_treat": True,
                "receiver_envelope": receiver,
                "receiver_itt_payoff": receiver_envelope_itt_payoff(receiver),
            }
        )
    return {
        "schema": OUTCOME_ADMISSION_SCHEMA,
        "manifest_row_sha256": manifest_row["row_sha256"],
        "arms": arms,
    }


class Wave5DPaperDesignTests(unittest.TestCase):
    def test_wave5c_a300_accounting_is_reconstructed_exactly(self) -> None:
        result = design_envelope(DESIGNS[0])
        self.assertEqual(result["paired_scenario_rows"], 3600)
        self.assertEqual(result["agent_episodes"], 14400)
        self.assertEqual(result["primary_eligible_paired_rows"], 600)
        self.assertEqual(result["primary_independent_clusters"], 300)
        self.assertEqual(result["confirmatory_nominal_requests"], 48000)
        self.assertEqual(result["whole_route_nominal_requests"], 48100)
        self.assertEqual(result["whole_route_max_attempts"], 96200)
        self.assertEqual(result["primary_cost_usd"]["nominal"], "203.174400")
        self.assertEqual(result["primary_cost_usd"]["retry_cap"], "406.348800")
        self.assertEqual(result["fallback_cost_usd"]["nominal"], "40.6348800")
        self.assertEqual(result["fallback_cost_usd"]["retry_cap"], "81.2697600")
        self.assertEqual(
            result["idealized_receiver_service_time"]["seconds_by_attempt_latency"]["30"],
            {"nominal_seconds": 45120, "retry_cap_seconds": 90210},
        )
        self.assertFalse(result["retry_cap_completes_within_12h_at_30s"])

    def test_clustered_effective_n_and_mde_are_monotone(self) -> None:
        independent = effective_sample_size(
            clusters=300,
            replicates=2,
            intraclass_correlation=0.0,
            information_loss=0.0,
        )
        central = effective_sample_size(
            clusters=300,
            replicates=2,
            intraclass_correlation=0.5,
            information_loss=0.1,
        )
        adverse = effective_sample_size(
            clusters=300,
            replicates=2,
            intraclass_correlation=0.75,
            information_loss=0.2,
        )
        self.assertEqual(independent, 600.0)
        self.assertEqual(central, 360.0)
        self.assertLess(adverse, central)
        self.assertAlmostEqual(
            minimum_detectable_effect(contrast_sd=0.2, effective_n=central),
            0.03410622955037141,
        )
        self.assertGreater(
            minimum_detectable_effect(contrast_sd=0.2, effective_n=adverse),
            minimum_detectable_effect(contrast_sd=0.2, effective_n=central),
        )
        grid = mde_grid(DESIGNS[0])
        self.assertEqual(len(grid), 96)
        self.assertEqual(required_clusters(
            target_effect=0.01,
            contrast_sd=0.2,
            replicates=2,
            intraclass_correlation=0.5,
            information_loss=0.1,
        ), 3490)

    def test_smaller_designs_preserve_exact_factorial_accounting(self) -> None:
        evidence = planning_evidence()
        expected = {
            "A300": (3600, 14400, 48100, 0.03410622955037141),
            "A200": (2400, 9600, 32100, 0.04177142972432164),
            "A140": (1680, 6720, 22500, 0.049926407859310316),
            "A100": (1200, 4800, 16100, 0.05907372243585031),
        }
        for row in evidence["designs"]:
            design_id = row["design"]["design_id"]
            paired, episodes, requests, mde = expected[design_id]
            self.assertEqual(row["paired_scenario_rows"], paired)
            self.assertEqual(row["agent_episodes"], episodes)
            self.assertEqual(row["whole_route_nominal_requests"], requests)
            self.assertAlmostEqual(row["central_planning_case"]["mde"], mde)
        self.assertFalse(evidence["boundaries"]["treatment_outcomes_used"])
        self.assertFalse(evidence["boundaries"]["receiver_capability_outputs_used"])
        self.assertFalse(evidence["boundaries"]["production_pins_set"])

    def test_invalid_planning_inputs_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            design_envelope(Design("bad", 1))
        with self.assertRaises(ValueError):
            effective_sample_size(
                clusters=1,
                replicates=2,
                intraclass_correlation=1.1,
                information_loss=0.0,
            )
        with self.assertRaises(ValueError):
            minimum_detectable_effect(contrast_sd=0.0, effective_n=100.0)

    def test_cli_reconstructs_complete_outcome_blind_grid(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "glee_eval.experiments.wave5d_paper_design"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload, planning_evidence())
        self.assertEqual(len(payload["a300_mde_grid"]), 96)
        self.assertEqual(
            payload["evidence_class"],
            "prospective_design_arithmetic_only_no_outcomes",
        )

    def test_synthetic_manifest_evaluator_admission_report_pipeline(self) -> None:
        # Every object is synthetic and deliberately incapable of production elevation.
        rows = run_factorial(
            _factories(),
            families=["bargaining", "negotiation", "persuasion"],
            games=12,
            seed=20260829,
            scenario_factory=_text_scenario,
            support_mask_fn=lambda scenario: {"inside_support": True},
            eligibility_fn=lambda scenario: derive_factorial_eligibility(
                scenario, model_c=MODEL_C, receiver_contract=RECEIVER
            ),
            require_inert_parity=True,
            required_artifact_provenance=ARTIFACTS,
        )
        scenarios = [row.arms[0].episode.scenario for row in rows]
        masks = {row.arms[0].episode.scenario.scenario_id: row.support_mask for row in rows}
        manifest_contract = PreOutcomeManifestContract.synthetic(
            rows_per_family=4,
            receiver_contract=RECEIVER,
            artifact_provenance=ARTIFACTS,
            scenario_design_sha256=scenario_design_sha256(scenarios),
            model_c_payload_sha256=canonical_hash(MODEL_C),
            support_masks_sha256=support_masks_sha256(masks),
        )
        manifest = build_preoutcome_manifest(
            scenarios,
            contract=manifest_contract,
            model_c=MODEL_C,
            support_masks=masks,
        )
        manifest_validation = validate_synthetic_preoutcome_manifest(
            manifest, contract=manifest_contract, model_c=MODEL_C
        )
        self.assertTrue(manifest_validation["passed"])
        self.assertEqual(
            manifest_validation["evidence_class"], "infrastructure_only_non_evidence"
        )
        for index, manifest_row in enumerate(manifest["rows"]):
            validation = validate_outcome_admission(
                manifest_row,
                _admission(manifest_row, missing=index == 0),
                receiver_contract=RECEIVER,
            )
            self.assertTrue(validation["passed"])

        report_contract = FactorialReportContract.synthetic(
            rows_per_family=4,
            required_artifact_provenance_hash=canonical_hash(ARTIFACTS),
            research_question_sha256="3" * 64,
        )
        report = build_factorial_report(rows, report_contract)
        report_validation = validate_synthetic_factorial_report(
            rows, report, report_contract
        )
        self.assertTrue(report_validation["passed"])
        self.assertEqual(
            report_validation["evidence_class"],
            "synthetic_arithmetic_only_not_production",
        )
        self.assertEqual(report["paired_rows"], 12)
        self.assertEqual(report["arm_episodes"], 48)
        self.assertEqual(
            {row.arms[0].episode.scenario.scenario_id for row in rows},
            {row["scenario_id"] for row in manifest["rows"]},
        )
        self.assertIsNone(factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256)
        self.assertIsNone(
            preoutcome_manifest.AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256
        )


if __name__ == "__main__":
    unittest.main()
