from __future__ import annotations

import json
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

from glee_eval.experiments.controlled_receiver import (
    BudgetExceeded,
    CACHE_MODE,
    CallReservation,
    CapabilityProbe,
    ContractValidationError,
    ControlledReceiverHarness,
    EnvelopeIntegrityError,
    ExactReplayCache,
    INFRASTRUCTURE_ONLY_NON_EVIDENCE,
    MISSINGNESS_RULE,
    ReceiverContract,
    RequestEnvelope,
    TransportResult,
    Usage,
    canonical_json_bytes,
    certify_capability,
    main,
)


def receiver_contract(**overrides: object) -> ReceiverContract:
    values: dict[str, object] = {
        "contract_id": "synthetic.receiver.contract.v1",
        "provider": "synthetic-offline",
        "model": "deterministic-test-double",
        "version": "1",
        "local_artifact_sha256": None,
        "system_prompt_bytes": b"Return one frozen JSON decision.",
        "user_prompt_bytes": b"Use the distinct stance, text, and visible-state fields.",
        "visible_input_fields": ("public_quality", "round"),
        "hidden_input_fields": ("private_canary", "treatment_arm"),
        "candidate_text_field": "candidate_text",
        "economic_stance_field": "economic_stance",
        "decoding_parameters": {"temperature": 0, "max_output_tokens": 16},
        "receiver_seeds": (101, 103),
        "parser_id": "strict_json_decision_v1",
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string", "enum": ["buy", "pass", "refuse"]}
            },
            "required": ["decision"],
        },
        "decision_field": "decision",
        "allowed_decisions": ("buy", "pass"),
        "refusal_decisions": ("refuse",),
        "failure_actions": {
            "timeout": "retry_then_record_missing",
            "refusal": "record_missing",
            "malformed": "retry_then_record_missing",
            "missing": "record_missing",
        },
        "max_attempts": 2,
        "timeout_seconds": 2.0,
        "missingness_rule": MISSINGNESS_RULE,
        "cache_mode": CACHE_MODE,
        "max_calls": 100,
        "max_input_tokens": 100_000,
        "max_output_tokens": 10_000,
        "max_cost_microusd": 1_000_000,
        "max_runtime_seconds": 100.0,
        "eligible_family": "persuasion",
        "eligible_candidate_role": "seller",
        "receiver_role": "buyer",
        "receiver_selection_rule": (
            "pre-existing receiver selected by an independent owner using generic capability "
            "probes before treatment outcomes"
        ),
        "receiver_selection_is_treatment_blind": True,
        "selection_frozen_before_treatment": True,
        "selection_uses_factorial_payoff": False,
        "selection_uses_treatment_templates": False,
    }
    values.update(overrides)
    return ReceiverContract(**values)  # type: ignore[arg-type]


def request(
    contract: ReceiverContract,
    *,
    text: str = "Please review the public evidence before deciding.",
    arm: str = "capability_not_a_treatment_arm",
    probe_id: str = "generic-001",
) -> RequestEnvelope:
    return RequestEnvelope.build(
        contract,
        probe_id=probe_id,
        candidate_text=text,
        economic_stance={"recommendation": "yes"},
        visible_inputs={"public_quality": "unknown", "round": 1},
        hidden_inputs={
            "private_canary": "HIDDEN_CANARY_8db11b1a",
            "treatment_arm": arm,
        },
        seed=101,
    )


RESERVATION = CallReservation(input_tokens=100, max_output_tokens=16, max_cost_microusd=500)


class ControlledReceiverContractTests(unittest.TestCase):
    def test_contract_hash_is_canonical_and_nested_inputs_are_immutable(self) -> None:
        first = receiver_contract(
            decoding_parameters={"temperature": 0, "max_output_tokens": 16}
        )
        second = receiver_contract(
            decoding_parameters={"max_output_tokens": 16, "temperature": 0}
        )
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(len(first.sha256), 64)
        self.assertEqual(ReceiverContract.from_dict(first.to_dict()).sha256, first.sha256)
        with self.assertRaises(TypeError):
            first.decoding_parameters["temperature"] = 1  # type: ignore[index]

    def test_contract_fails_closed_on_identity_selection_and_missingness(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "provider/model/version"):
            receiver_contract(provider="", model="", version="")
        with self.assertRaisesRegex(ContractValidationError, "treatment-blind"):
            receiver_contract(selection_uses_factorial_payoff=True)
        with self.assertRaisesRegex(ContractValidationError, "prespecified failed rows"):
            receiver_contract(missingness_rule="drop_failed_rows")
        with self.assertRaisesRegex(ContractValidationError, "hidden input"):
            receiver_contract(hidden_input_fields=("private_canary",))

    def test_request_separates_candidate_text_stance_visible_and_hidden_inputs(self) -> None:
        contract = receiver_contract()
        envelope = request(contract)
        envelope.verify(contract)
        outbound = envelope.outbound_object()
        self.assertEqual(
            outbound["inputs"][contract.candidate_text_field],
            "Please review the public evidence before deciding.",
        )
        self.assertEqual(
            outbound["inputs"][contract.economic_stance_field], {"recommendation": "yes"}
        )
        encoded = envelope.outbound_bytes.decode("utf-8")
        self.assertNotIn("private_canary", encoded)
        self.assertNotIn("HIDDEN_CANARY_8db11b1a", encoded)
        self.assertNotIn("treatment_arm", encoded)
        with self.assertRaisesRegex(EnvelopeIntegrityError, "visible input keys"):
            RequestEnvelope.build(
                contract,
                probe_id="bad",
                candidate_text="generic",
                economic_stance={},
                visible_inputs={"round": 1},
                hidden_inputs={
                    "private_canary": "HIDDEN_CANARY_x",
                    "treatment_arm": "00",
                },
                seed=101,
            )

    def test_retry_parse_cache_export_and_exact_replay(self) -> None:
        contract = receiver_contract()
        envelope = request(contract)
        calls: list[bytes] = []

        def transport(outbound: bytes, timeout: float) -> TransportResult:
            self.assertEqual(timeout, 2.0)
            calls.append(outbound)
            if len(calls) == 1:
                return TransportResult(
                    b"not-json",
                    Usage(80, 2, 50),
                    elapsed_ms=3,
                    consumed_fields=("candidate_text",),
                )
            return TransportResult(
                b'{"decision":"buy"}',
                Usage(80, 4, 60),
                elapsed_ms=4,
                consumed_fields=("candidate_text",),
            )

        harness = ControlledReceiverHarness(contract)
        result = harness.invoke(envelope, reservation=RESERVATION, transport=transport)
        self.assertFalse(result.cache_hit)
        self.assertEqual(result.record.observation.decision, "buy")
        self.assertEqual(result.record.observation.attempts, 2)
        self.assertEqual(
            result.record.observation.evidence_label, INFRASTRUCTURE_ONLY_NON_EVIDENCE
        )
        self.assertEqual(harness.budget.calls, 2)

        dumped = harness.cache.dump_bytes()
        restored = ExactReplayCache.load_bytes(dumped)
        replay = ControlledReceiverHarness(contract, restored).invoke(
            envelope, reservation=RESERVATION, replay_only=True
        )
        self.assertTrue(replay.cache_hit)
        self.assertEqual(replay.record.to_bytes(), result.record.to_bytes())
        self.assertEqual(len(calls), 2)

    def test_refusal_timeout_missing_and_malformed_all_retain_missing_row(self) -> None:
        base = receiver_contract()
        cases = {
            "refusal": TransportResult(b'{"decision":"refuse"}'),
            "timeout": TransportResult(b"", transport_status="timeout"),
            "missing": TransportResult(b""),
            "malformed": TransportResult(b'{"decision":"unknown"}'),
        }
        for name, transport_result in cases.items():
            with self.subTest(name=name):
                contract = replace(
                    base,
                    failure_actions={kind: "record_missing" for kind in cases},
                )
                result = ControlledReceiverHarness(contract).invoke(
                    request(contract, probe_id=name),
                    reservation=RESERVATION,
                    transport=lambda _outbound, _timeout, value=transport_result: value,
                )
                self.assertTrue(result.record.observation.missing)
                self.assertEqual(result.record.observation.failure_kind, name)
                self.assertEqual(result.record.observation.attempts, 1)

    def test_failure_parser_is_identical_when_only_hidden_arm_changes(self) -> None:
        contract = receiver_contract()
        left = request(contract, arm="00", probe_id="same-state:00")
        right = request(contract, arm="11", probe_id="same-state:11")
        self.assertEqual(left.outbound_bytes, right.outbound_bytes)
        self.assertNotEqual(left.request_sha256, right.request_sha256)
        harness = ControlledReceiverHarness(contract)
        transport = lambda _outbound, _timeout: TransportResult(b"malformed")
        observations = [
            harness.invoke(item, reservation=RESERVATION, transport=transport).record.observation
            for item in (left, right)
        ]
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[0].failure_kind, "malformed")

    def test_budget_reservation_fails_before_transport(self) -> None:
        contract = receiver_contract(max_calls=1, max_input_tokens=10)
        invoked = False

        def transport(_outbound: bytes, _timeout: float) -> TransportResult:
            nonlocal invoked
            invoked = True
            return TransportResult(b'{"decision":"buy"}')

        with self.assertRaises(BudgetExceeded):
            ControlledReceiverHarness(contract).invoke(
                request(contract), reservation=RESERVATION, transport=transport
            )
        self.assertFalse(invoked)

    def test_cache_rejects_a_canonical_but_hash_tampered_response(self) -> None:
        contract = receiver_contract()
        envelope = request(contract)
        harness = ControlledReceiverHarness(contract)
        harness.invoke(
            envelope,
            reservation=RESERVATION,
            transport=lambda _outbound, _timeout: TransportResult(b'{"decision":"buy"}'),
        )
        value = json.loads(harness.cache.dump_bytes())
        value["records"][0]["responses"][0]["response_b64"] = "e30="
        with self.assertRaisesRegex(EnvelopeIntegrityError, "cache hash mismatch"):
            ExactReplayCache.load_bytes(canonical_json_bytes(value))


class CapabilityCertificateTests(unittest.TestCase):
    @staticmethod
    def probe(probe_id: str = "generic-responsiveness-001") -> CapabilityProbe:
        return CapabilityProbe(
            probe_id=probe_id,
            candidate_text_a="Proceed after weighing the public evidence.",
            candidate_text_b="Pause before acting on the public evidence.",
            economic_stance={"recommendation": "yes"},
            visible_inputs={"public_quality": "unknown", "round": 1},
            hidden_inputs={
                "private_canary": "HIDDEN_CANARY_4cf3f642",
                "treatment_arm": "HIDDEN_CANARY_NO_TREATMENT_ARM",
            },
            seed=101,
        )

    def test_text_sensitive_synthetic_receiver_passes_all_six_checks(self) -> None:
        contract = receiver_contract()

        def sensitive_receiver(outbound: bytes, _timeout: float) -> TransportResult:
            payload = json.loads(outbound)
            text = payload["inputs"]["candidate_text"]
            decision = "buy" if text.startswith("Proceed") else "pass"
            return TransportResult(
                canonical_json_bytes({"decision": decision}),
                Usage(90, 4, 100),
                elapsed_ms=2,
                consumed_fields=("candidate_text",),
            )

        certificate = certify_capability(
            contract,
            [self.probe()],
            transport=sensitive_receiver,
            reservation=RESERVATION,
        )
        self.assertTrue(certificate.passed)
        self.assertTrue(certificate.candidate_text_delivered)
        self.assertTrue(certificate.receiver_consumes_candidate_text)
        self.assertTrue(certificate.text_only_perturbation_changes_output)
        self.assertTrue(certificate.hidden_treatment_information_not_exposed)
        self.assertTrue(certificate.parsing_and_failures_arm_invariant)
        self.assertTrue(certificate.exact_cache_replay)
        self.assertEqual(certificate.evidence_label, INFRASTRUCTURE_ONLY_NON_EVIDENCE)
        self.assertEqual(
            certificate.probe_results[0]["evidence_label"],
            INFRASTRUCTURE_ONLY_NON_EVIDENCE,
        )

    def test_text_blind_or_uninstrumented_synthetic_receiver_cannot_certify(self) -> None:
        contract = receiver_contract()

        def blind_receiver(_outbound: bytes, _timeout: float) -> TransportResult:
            return TransportResult(b'{"decision":"buy"}', consumed_fields=())

        certificate = certify_capability(
            contract,
            [self.probe("generic-negative-control")],
            transport=blind_receiver,
            reservation=RESERVATION,
        )
        self.assertFalse(certificate.passed)
        self.assertFalse(certificate.receiver_consumes_candidate_text)
        self.assertFalse(certificate.text_only_perturbation_changes_output)
        self.assertEqual(certificate.evidence_label, INFRASTRUCTURE_ONLY_NON_EVIDENCE)

    def test_future_cli_uses_only_the_explicit_transport_and_writes_labelled_artifacts(self) -> None:
        contract = receiver_contract()
        probe = self.probe("generic-cli-probe")
        adapter_name = "wave5a_synthetic_receiver_adapter"
        adapter = types.ModuleType(adapter_name)

        def transport(outbound: bytes, _timeout: float) -> TransportResult:
            payload = json.loads(outbound)
            text = payload["inputs"]["candidate_text"]
            decision = "buy" if text.startswith("Proceed") else "pass"
            return TransportResult(
                canonical_json_bytes({"decision": decision}),
                Usage(90, 4, 100),
                consumed_fields=("candidate_text",),
            )

        adapter.transport = transport  # type: ignore[attr-defined]
        sys.modules[adapter_name] = adapter
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                contract_path = root / "contract.json"
                probes_path = root / "probes.json"
                cache_path = root / "cache.json"
                certificate_path = root / "certificate.json"
                contract_path.write_bytes(canonical_json_bytes(contract.to_dict()))
                probes_path.write_bytes(
                    canonical_json_bytes(
                        {
                            "schema": "glee.research.receiver_capability_probes.v1",
                            "probes": [
                                {
                                    "probe_id": probe.probe_id,
                                    "candidate_text_a": probe.candidate_text_a,
                                    "candidate_text_b": probe.candidate_text_b,
                                    "economic_stance": probe.economic_stance,
                                    "visible_inputs": probe.visible_inputs,
                                    "hidden_inputs": probe.hidden_inputs,
                                    "seed": probe.seed,
                                }
                            ],
                        }
                    )
                )
                with redirect_stdout(io.StringIO()) as output:
                    code = main(
                        [
                            "certify",
                            "--contract",
                            str(contract_path),
                            "--probes",
                            str(probes_path),
                            "--transport",
                            f"{adapter_name}:transport",
                            "--cache-out",
                            str(cache_path),
                            "--certificate-out",
                            str(certificate_path),
                            "--reserved-input-tokens",
                            "100",
                            "--reserved-output-tokens",
                            "16",
                            "--reserved-cost-microusd",
                            "500",
                        ]
                    )
                self.assertEqual(code, 0)
                self.assertTrue(json.loads(output.getvalue())["passed"])
                self.assertEqual(
                    json.loads(certificate_path.read_text())["evidence_label"],
                    INFRASTRUCTURE_ONLY_NON_EVIDENCE,
                )
                ExactReplayCache.load_bytes(cache_path.read_bytes())
        finally:
            sys.modules.pop(adapter_name, None)


if __name__ == "__main__":
    unittest.main()
