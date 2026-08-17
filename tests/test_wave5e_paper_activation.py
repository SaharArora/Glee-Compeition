from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import glee_eval.experiments.openai_responses as openai_responses_module
from glee_eval.experiments.controlled_receiver import (
    CallReservation,
    ControlledReceiverHarness,
    RequestEnvelope,
    TransportResult,
    Usage,
    canonical_json_bytes,
)
from glee_eval.experiments.factorial_report import (
    FactorialReportError,
    _cluster_design_summary,
    _clustered_estimate,
)
from glee_eval.experiments.openai_responses import (
    FROZEN_MODEL,
    MAX_RESPONSE_BODY_BYTES,
    OPENAI_RESPONSES_ENDPOINT,
    OpenAIAdapterError,
    OpenAIResponsesTransport,
    load_protected_api_key,
)
from glee_eval.experiments.receiver_itt import (
    RECEIVER_FAILURE_ITT_RULE_SHA256,
    bind_terminal_itt_payoff,
    resolve_receiver_itt,
)
from glee_eval.experiments.wave5c_receiver import (
    GENERIC_TEXT_A,
    build_capability_probes,
    build_receiver_contract,
)
from glee_eval.experiments.wave5e_capability import (
    RESERVATION,
    CapabilityRunError,
    PreauthorizedRouteTransport,
    _create_fresh_output_dir,
    _read_audit_document,
    capability_failure_certificate,
    run_capability,
    source_hashes,
    validate_dependency_lock,
    validate_runtime_and_sources,
)
from glee_eval.experiments.wave5e_paper_activation import activation_evidence


class _FakeHTTPResponse:
    def __init__(self, document: dict, *, url: str = OPENAI_RESPONSES_ENDPOINT) -> None:
        self.status = 200
        self._data = json.dumps(document).encode("utf-8")
        self._url = url

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._data if size < 0 else self._data[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _request() -> RequestEnvelope:
    contract = build_receiver_contract()
    probe = build_capability_probes()[0]
    return RequestEnvelope.build(
        contract,
        probe_id="wave5e-adapter-unit",
        candidate_text=GENERIC_TEXT_A,
        economic_stance=probe.economic_stance,
        visible_inputs=probe.visible_inputs,
        hidden_inputs=probe.hidden_inputs,
        seed=probe.seed,
    )


def _provider_document(text: str = '{"decision":"buy"}') -> dict:
    return {
        "id": "redacted-unit-id",
        "model": FROZEN_MODEL,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {"input_tokens": 321, "output_tokens": 5},
    }


class ReceiverITTTests(unittest.TestCase):
    def test_all_failures_map_to_pass_and_natural_numeric_payoff(self) -> None:
        for failure in ("timeout", "malformed", "refusal", "missing", "exhausted_retry"):
            attempts = 2 if failure in {"timeout", "malformed", "exhausted_retry"} else 1
            result = resolve_receiver_itt(
                status="failure", decision=None, failure_kind=failure, attempts=attempts
            )
            self.assertEqual(result.controlled_decision, "pass")
            self.assertEqual(result.environment_action, "no")
            self.assertEqual(result.rule_sha256, RECEIVER_FAILURE_ITT_RULE_SHA256)
            if attempts == 2:
                self.assertEqual(result.effective_status, "exhausted_retry")
            payoff = bind_terminal_itt_payoff(result, 0.35)
            self.assertEqual(payoff["terminal_candidate_payoff"], 0.35)
            self.assertTrue(payoff["row_included_in_intent_to_treat"])

    def test_success_mapping_and_malformed_observations_fail_closed(self) -> None:
        self.assertEqual(
            resolve_receiver_itt(
                status="ok", decision="buy", failure_kind=None, attempts=1
            ).environment_action,
            "yes",
        )
        with self.assertRaises(ValueError):
            resolve_receiver_itt(
                status="failure", decision="buy", failure_kind="timeout", attempts=1
            )
        with self.assertRaises(ValueError):
            resolve_receiver_itt(
                status="failure", decision=None, failure_kind="timeout", attempts=1
            )
        with self.assertRaises(ValueError):
            bind_terminal_itt_payoff(
                resolve_receiver_itt(
                    status="ok", decision="pass", failure_kind=None, attempts=1
                ),
                float("nan"),
            )
        for invalid in (True, "0.5"):
            with self.assertRaises(ValueError):
                bind_terminal_itt_payoff(
                    resolve_receiver_itt(
                        status="ok", decision="pass", failure_kind=None, attempts=1
                    ),
                    invalid,  # type: ignore[arg-type]
                )


class ClusteredInferenceTests(unittest.TestCase):
    @staticmethod
    def _record(cluster: str, value: float, role: str = "seller", replicate: int = 0):
        class Row:
            family = "persuasion"
            candidate_role = role

        return {
            "row": Row(),
            "base_stratum_id": cluster,
            "base_stratum_hash": "a" * 64,
            "receiver_replicate": replicate,
            "contrasts": {"language_main_effect": value},
        }

    def test_cluster_means_not_repeated_rows_drive_standard_error(self) -> None:
        records = [
            self._record("p:0", 0.0, replicate=0),
            self._record("p:0", 2.0, replicate=1),
            self._record("p:1", 4.0, replicate=0),
            self._record("p:1", 6.0, replicate=1),
        ]
        estimate = _clustered_estimate(records, "language_main_effect", 0.05, 2)
        self.assertEqual(estimate["paired_rows"], 4)
        self.assertEqual(estimate["independent_clusters"], 2)
        self.assertEqual(estimate["effect"], 3.0)
        self.assertEqual(estimate["standard_error"], 2.0)

    def test_design_a_requires_300_exact_role_replicate_crossings(self) -> None:
        records = []
        for index in range(300):
            cluster = f"persuasion:base-{index:06d}"
            for role in ("seller", "buyer"):
                for replicate in (0, 1):
                    records.append(self._record(cluster, 0.0, role, replicate))
        summary = _cluster_design_summary(records, require_design_a=True)
        self.assertEqual(summary["persuasion"]["independent_base_strata"], 300)
        records[-1]["base_stratum_hash"] = "b" * 64
        with self.assertRaisesRegex(FactorialReportError, "inconsistent economic bytes"):
            _cluster_design_summary(records, require_design_a=True)


class OpenAIResponsesAdapterTests(unittest.TestCase):
    def test_exact_provider_payload_usage_and_secret_separation(self) -> None:
        captured = {}

        def opener(request, **_kwargs):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["body"] = json.loads(request.data)
            return _FakeHTTPResponse(_provider_document())

        key = "UNIT_TEST_SECRET_MUST_NOT_LEAK"
        contract = build_receiver_contract()
        result = OpenAIResponsesTransport(contract, key, opener=opener)(
            _request().outbound_bytes, 30
        )
        self.assertEqual(captured["url"], OPENAI_RESPONSES_ENDPOINT)
        self.assertEqual(captured["body"]["model"], FROZEN_MODEL)
        self.assertFalse(captured["body"]["store"])
        self.assertNotIn("seed", captured["body"])
        self.assertTrue(captured["body"]["text"]["format"]["strict"])
        self.assertNotIn(key, json.dumps(captured["body"]))
        self.assertEqual(result.response_bytes, b'{"decision":"buy"}')
        self.assertEqual(result.usage.cost_microusd, 321 * 2 + 5 * 8)
        self.assertEqual(result.consumed_fields, ("candidate_text",))

    def test_http_error_body_and_key_are_redacted(self) -> None:
        key = "LEAK_CANARY_OPENAI_KEY"

        def opener(request, **_kwargs):
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                None,
            )

        with self.assertRaises(OpenAIAdapterError) as caught:
            OpenAIResponsesTransport(build_receiver_contract(), key, opener=opener)(
                _request().outbound_bytes, 30
            )
        self.assertNotIn(key, str(caught.exception))
        self.assertNotIn("rate limited", str(caught.exception))

    def test_redirect_and_model_drift_fail_closed(self) -> None:
        for response in (
            _FakeHTTPResponse(_provider_document(), url="https://example.invalid/steal"),
            _FakeHTTPResponse({**_provider_document(), "model": "gpt-4.1"}),
        ):
            with self.assertRaises(OpenAIAdapterError):
                OpenAIResponsesTransport(
                    build_receiver_contract(), "secret", opener=lambda *_a, **_k: response
                )(_request().outbound_bytes, 30)

    def test_refusal_maps_to_frozen_parser_value(self) -> None:
        response = _provider_document()
        response["output"][0]["content"] = [
            {"type": "refusal", "refusal": "unit-test refusal body"}
        ]
        result = OpenAIResponsesTransport(
            build_receiver_contract(),
            "secret",
            opener=lambda *_a, **_k: _FakeHTTPResponse(response),
        )(_request().outbound_bytes, 30)
        self.assertEqual(result.response_bytes, b'{"decision":"refuse"}')
        self.assertNotIn(b"unit-test", result.response_bytes)

    def test_empty_provider_output_enters_typed_missing_path(self) -> None:
        response = _provider_document()
        response["output"] = []
        transport = OpenAIResponsesTransport(
            build_receiver_contract(),
            "secret",
            opener=lambda *_a, **_k: _FakeHTTPResponse(response),
        )
        result = transport(_request().outbound_bytes, 30)
        self.assertEqual(result.response_bytes, b"")

    def test_response_body_is_bounded_and_usage_types_are_strict(self) -> None:
        oversized = _FakeHTTPResponse(_provider_document())
        oversized._data = b"{" + b"x" * MAX_RESPONSE_BODY_BYTES + b"}"
        with self.assertRaisesRegex(OpenAIAdapterError, "byte limit"):
            OpenAIResponsesTransport(
                build_receiver_contract(),
                "secret",
                opener=lambda *_a, **_k: oversized,
            )(_request().outbound_bytes, 30)
        for invalid in ("321", 321.0, True, -1):
            document = _provider_document()
            document["usage"]["input_tokens"] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                OpenAIAdapterError, "strict nonnegative integers"
            ):
                OpenAIResponsesTransport(
                    build_receiver_contract(),
                    "secret",
                    opener=lambda *_a, _document=document, **_k: _FakeHTTPResponse(
                        _document
                    ),
                )(_request().outbound_bytes, 30)

    def test_oversized_provider_payload_fails_before_transport(self) -> None:
        request = _request()
        outbound = request.outbound_object()
        outbound["inputs"]["candidate_text"] = "x" * 4096
        called = False

        def opener(*_args, **_kwargs):
            nonlocal called
            called = True
            return _FakeHTTPResponse(_provider_document())

        with self.assertRaisesRegex(OpenAIAdapterError, "pre-reservation"):
            OpenAIResponsesTransport(
                build_receiver_contract(), "secret", opener=opener
            )(canonical_json_bytes(outbound), 30)
        self.assertFalse(called)

    def test_key_file_must_be_outside_repo_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            repository = root / "repo"
            repository.mkdir()
            outside = root / "openai.key"
            outside.write_text("secret\n", encoding="utf-8")
            outside.chmod(0o600)
            self.assertEqual(
                load_protected_api_key(outside, repository_root=repository), "secret"
            )
            outside.chmod(0o644)
            with self.assertRaises(OpenAIAdapterError):
                load_protected_api_key(outside, repository_root=repository)
            inside = repository / "openai.key"
            inside.write_text("secret\n", encoding="utf-8")
            inside.chmod(0o600)
            with self.assertRaises(OpenAIAdapterError):
                load_protected_api_key(inside, repository_root=repository)
            outside.chmod(0o700)
            with self.assertRaisesRegex(OpenAIAdapterError, "exactly 0600"):
                load_protected_api_key(outside, repository_root=repository)
            outside.chmod(0o600)
            link = root / "openai-link.key"
            link.symlink_to(outside)
            with self.assertRaisesRegex(OpenAIAdapterError, "symbolic link"):
                load_protected_api_key(link, repository_root=repository)


class CapabilityRunnerTests(unittest.TestCase):
    def test_offline_transport_proves_exact_100_request_200_attempt_cap_path(self) -> None:
        class OfflineTransport:
            contract = build_receiver_contract()

            def __call__(self, outbound: bytes, _timeout: float) -> TransportResult:
                value = json.loads(outbound)
                text = value["inputs"]["candidate_text"]
                decision = "buy" if "proceed if" in text else "pass"
                return TransportResult(
                    canonical_json_bytes({"decision": decision}),
                    Usage(input_tokens=256, output_tokens=4, cost_microusd=544),
                    consumed_fields=("candidate_text",),
                )

        result = run_capability(OfflineTransport())  # type: ignore[arg-type]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["accounting"]["nominal_requests"], 100)
        self.assertEqual(result["accounting"]["actual_attempts"], 100)
        self.assertEqual(result["accounting"]["maximum_attempts"], 200)
        self.assertLessEqual(
            result["accounting"]["maximum_prereserved_cost_microusd"], 1_000_000
        )
        self.assertFalse(result["boundaries"]["automatic_fallback"])

    def test_reservation_is_debited_before_unknown_transport_failure(self) -> None:
        class FailingTransport:
            contract = build_receiver_contract()

            def __call__(self, _outbound: bytes, _timeout: float):
                raise OpenAIAdapterError("secret provider detail")

        route = PreauthorizedRouteTransport(FailingTransport())  # type: ignore[arg-type]
        with self.assertRaises(OpenAIAdapterError):
            route(b"{}", 30)
        self.assertEqual(route.attempts_started, 1)
        self.assertEqual(
            route.reserved_cost_microusd, RESERVATION.max_cost_microusd
        )
        certificate = capability_failure_certificate(
            route, {"implementation_commit": "a" * 40, "source_sha256": {}}, RuntimeError("leak")
        )
        self.assertEqual(certificate["status"], "FAIL")
        self.assertNotIn("leak", json.dumps(certificate))

    def test_timeout_charges_full_conservative_reservation(self) -> None:
        request = _request()
        harness = ControlledReceiverHarness(build_receiver_contract())

        def timeout(_outbound: bytes, _seconds: float):
            raise TimeoutError

        result = harness.invoke(request, reservation=RESERVATION, transport=timeout)
        self.assertEqual(result.record.observation.failure_kind, "timeout")
        self.assertEqual(len(result.record.responses), 2)
        self.assertTrue(
            all(
                response.usage.cost_microusd == RESERVATION.max_cost_microusd
                for response in result.record.responses
            )
        )

    def test_mixed_root_import_and_inside_output_fail_closed(self) -> None:
        root = Path.cwd().resolve()
        with mock.patch.object(
            openai_responses_module, "__file__", "/tmp/mixed-root/openai_responses.py"
        ), self.assertRaisesRegex(CapabilityRunError, "outside audited root"):
            validate_runtime_and_sources(root)
        inside = root / "forbidden-capability-output"
        with self.assertRaisesRegex(CapabilityRunError, "outside the repository"):
            _create_fresh_output_dir(inside, root)
        with tempfile.TemporaryDirectory(dir=root) as inside_directory:
            audit = Path(inside_directory) / "audit.json"
            audit.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(CapabilityRunError, "outside the repository"):
                _read_audit_document(audit, root)


class PaperActivationEvidenceTests(unittest.TestCase):
    def test_committed_evidence_reconstructs_exactly(self) -> None:
        committed = json.loads(
            Path("research/EVIDENCE/WAVE5E_PAPER_ACTIVATION.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(committed, activation_evidence())

    def test_adapter_evidence_reconstructs_exact_source_map(self) -> None:
        committed = json.loads(
            Path("research/EVIDENCE/WAVE5E_ADAPTER_IMPLEMENTATION.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(committed["source_sha256"], source_hashes("."))
        validate_dependency_lock(".")

    def test_recommendation_uses_new_sesoi_and_reconciled_runtime(self) -> None:
        evidence = activation_evidence()
        self.assertEqual(evidence["sesoi"]["normalized_payoff"], 0.035)
        self.assertFalse(evidence["sesoi"]["competition_gate_0_010_reused"])
        self.assertLess(
            evidence["sesoi"]["a300_single_primary_mde"],
            evidence["sesoi"]["normalized_payoff"],
        )
        self.assertGreater(
            evidence["sesoi"]["a200_single_primary_mde"],
            evidence["sesoi"]["normalized_payoff"],
        )
        self.assertEqual(evidence["runtime"]["wall_clock_cap_hours"], 32)
        self.assertGreater(evidence["runtime"]["retry_cap_service_margin_seconds"], 0)
        self.assertFalse(evidence["runtime"]["full_study_authorized"])
        self.assertEqual(
            evidence["estimand_order"]["single_confirmatory_primary"],
            "language_main_effect_on_preoutcome_language_eligible_rows",
        )

    def test_dilution_and_conditional_effect_arithmetic_is_explicit(self) -> None:
        evidence = activation_evidence()
        translation = evidence["mde_translation"]["full_glee_equal_family_role_dilution"]
        self.assertAlmostEqual(
            translation["a300_mde_equivalent"],
            evidence["mde_translation"]["central_a300_normalized"] / 6,
        )
        self.assertAlmostEqual(
            evidence["exposure"]["eprocess"][
                "conditional_episode_effect_required_by_affected_scenario_frequency"
            ]["0.05"],
            evidence["mde_translation"]["central_a300_normalized"] / 0.05,
        )
        self.assertEqual(
            evidence["mde_translation"]["leaderboard_relevance"][
                "payoff_to_percentile_mapping"
            ],
            "unknown_without_a_prospectively_frozen_reference_CDF_density",
        )
        self.assertTrue(
            all(value is False for value in evidence["boundaries"].values())
        )


if __name__ == "__main__":
    unittest.main()
