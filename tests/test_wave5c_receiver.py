from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from glee_eval.experiments import factorial_report, preoutcome_manifest
from glee_eval.experiments.controlled_receiver import (
    ContractValidationError,
    EnvelopeIntegrityError,
    RequestEnvelope,
    canonical_json_bytes,
    sha256_hex,
)
from glee_eval.experiments.wave5c_receiver import (
    FIELD_NAMES,
    ReceiverCallAccounting,
    build_capability_probes,
    build_dry_run_report,
    build_proposal,
    build_receiver_contract,
    proposal_sha256,
    validate_proposal,
)


class ReceiverProposalTests(unittest.TestCase):
    def test_committed_evidence_matches_executable_builders(self) -> None:
        path = Path("research/EVIDENCE/WAVE5C_RECEIVER_DECISION.json")
        committed = json.loads(path.read_text(encoding="utf-8"))
        validate_proposal(committed["proposal"])
        self.assertEqual(committed["proposal"], build_proposal())
        self.assertEqual(committed["dry_run"], build_dry_run_report())

    def test_3600_rows_are_not_calls_or_arm_executions(self) -> None:
        accounting = ReceiverCallAccounting().to_dict()
        self.assertEqual(accounting["paired_scenario_rows"], 3_600)
        self.assertEqual(accounting["rows_per_family"], 1_200)
        self.assertEqual(accounting["agent_executions"], 14_400)
        self.assertEqual(accounting["receiver_eligible_rows"], 600)
        self.assertEqual(accounting["confirmatory_nominal_requests"], 48_000)
        self.assertEqual(accounting["confirmatory_max_attempts"], 96_000)
        self.assertEqual(accounting["capability_nominal_requests"], 100)
        self.assertEqual(accounting["total_max_attempts"], 96_200)
        self.assertEqual(accounting["total_planned_retries"], 0)

    def test_proposal_has_all_13_ordered_fields_and_canonical_hash(self) -> None:
        proposal = build_proposal()
        validate_proposal(proposal)
        self.assertEqual(set(proposal["fields"]), set(FIELD_NAMES))
        self.assertEqual(len(FIELD_NAMES), 13)
        self.assertEqual(proposal_sha256(proposal), proposal_sha256(build_proposal()))
        self.assertEqual(
            proposal["fields"]["identity"]["receiver_contract_sha256"],
            build_receiver_contract().sha256,
        )
        self.assertEqual(
            proposal["fields"]["confirmatory_design"]["design_recommendation"], "A"
        )

    def test_prompt_or_accounting_tampering_fails_closed(self) -> None:
        proposal = build_proposal()
        proposal["fields"]["prompt_bytes"]["system_b64"] = "e30="
        with self.assertRaisesRegex(ContractValidationError, "prompt"):
            validate_proposal(proposal)

        proposal = build_proposal()
        proposal["fields"]["confirmatory_design"]["agent_executions"] = 3_600
        with self.assertRaisesRegex(ContractValidationError, "accounting"):
            validate_proposal(proposal)

    def test_authorization_boundary_cannot_be_claimed_by_proposal(self) -> None:
        proposal = build_proposal()
        proposal["hard_boundaries"]["production_pins_set"] = True
        with self.assertRaisesRegex(ContractValidationError, "hard boundary"):
            validate_proposal(proposal)
        self.assertIsNone(factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256)
        self.assertIsNone(
            preoutcome_manifest.AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256
        )

    def test_proposed_contract_identifies_user_credentials_without_serializing_them(self) -> None:
        encoded = canonical_json_bytes(build_proposal()).decode("utf-8")
        self.assertIn("OPENAI_API_KEY", encoded)
        self.assertNotIn("sk-", encoded)
        self.assertIn("USER_MUST_SUPPLY_REVIEWED_MODULE_AND_SHA256", encoded)


class ReceiverHostileDryRunTests(unittest.TestCase):
    def test_probe_population_is_exact_and_treatment_blind(self) -> None:
        probes = build_capability_probes()
        self.assertEqual(len(probes), 50)
        self.assertEqual(len({probe.probe_id for probe in probes}), 50)
        self.assertEqual(len({probe.seed for probe in probes}), 2)
        self.assertEqual(len({probe.candidate_text_a for probe in probes}), 1)
        self.assertEqual(len({probe.candidate_text_b for probe in probes}), 1)
        self.assertTrue(
            all(probe.hidden_inputs["treatment_arm"] == "HIDDEN_CAPABILITY_NOT_FACTORIAL" for probe in probes)
        )

    def test_hidden_arm_is_committed_but_not_delivered(self) -> None:
        contract = build_receiver_contract()
        probe = build_capability_probes()[0]
        requests = []
        for arm in ("e0_l0", "e1_l1"):
            requests.append(
                RequestEnvelope.build(
                    contract,
                    probe_id=f"arm-{arm}",
                    candidate_text=probe.candidate_text_a,
                    economic_stance=probe.economic_stance,
                    visible_inputs=probe.visible_inputs,
                    hidden_inputs={**dict(probe.hidden_inputs), "treatment_arm": arm},
                    seed=probe.seed,
                )
            )
        self.assertEqual(requests[0].outbound_bytes, requests[1].outbound_bytes)
        self.assertNotEqual(requests[0].request_sha256, requests[1].request_sha256)
        outbound = requests[0].outbound_bytes.decode("utf-8")
        for key, value in probe.hidden_inputs.items():
            self.assertNotIn(key, outbound)
            self.assertNotIn(str(value), outbound)

    def test_hash_consistent_forged_outbound_hidden_field_is_rejected(self) -> None:
        contract = build_receiver_contract()
        probe = build_capability_probes()[0]
        request = RequestEnvelope.build(
            contract,
            probe_id="forge-target",
            candidate_text=probe.candidate_text_a,
            economic_stance=probe.economic_stance,
            visible_inputs=probe.visible_inputs,
            hidden_inputs=probe.hidden_inputs,
            seed=probe.seed,
        )
        outbound = json.loads(request.outbound_bytes)
        outbound["treatment_arm"] = "e1_l1"
        outbound_bytes = canonical_json_bytes(outbound)
        forged = replace(
            request,
            outbound_bytes=outbound_bytes,
            outbound_sha256=sha256_hex(outbound_bytes),
            request_sha256="0" * 64,
        )
        forged = replace(
            forged,
            request_sha256=sha256_hex(canonical_json_bytes(forged.unsigned_dict())),
        )
        with self.assertRaisesRegex(EnvelopeIntegrityError, "outbound receiver fields"):
            forged.verify(contract)

    def test_dry_run_is_reproducible_and_uses_no_external_transport(self) -> None:
        first = build_dry_run_report()
        second = build_dry_run_report()
        self.assertEqual(first, second)
        self.assertTrue(first["synthetic_certificate_passed"])
        self.assertTrue(first["wave5c_capability_rule"]["passed"])
        self.assertEqual(
            first["wave5c_capability_rule"]["changed_states_by_receiver_seed"],
            {"530011": 25, "530017": 25},
        )
        self.assertEqual(first["capability_nominal_requests"], 100)
        self.assertFalse(first["external_calls_performed"])
        self.assertEqual(first["payoff_rows_generated"], 0)
        self.assertFalse(first["production_authorization_pins_changed"])
        self.assertTrue(all(first["hostile_checks"].values()))


if __name__ == "__main__":
    unittest.main()
