from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest import mock

from glee_eval.data.schemas import Scenario
from glee_eval.experiments.factorial import (
    factorial_named_seed,
    factorial_scenario_seed,
    factorial_stream_hash,
)
from glee_eval.experiments.factorial_report import canonical_hash
from glee_eval.experiments import factorial_report, preoutcome_manifest
from glee_eval.experiments.preoutcome_manifest import (
    FACTORIAL_ARMS,
    OUTCOME_ADMISSION_SCHEMA,
    PreOutcomeManifestContract,
    PreOutcomeManifestError,
    build_preoutcome_manifest,
    scenario_design_sha256,
    support_masks_sha256,
    validate_outcome_admission,
    validate_production_preoutcome_manifest,
    validate_synthetic_preoutcome_manifest,
)


SEED = 20260829
FAMILIES = ("bargaining", "negotiation", "persuasion")
ROLES = {
    "bargaining": ("player_1", "player_2"),
    "negotiation": ("seller", "buyer"),
    "persuasion": ("seller", "buyer"),
}
RECEIVER = {
    "schema": "glee.research.controlled_receiver_contract.v1",
    "environment_id": "synthetic-receiver-only",
    "candidate_text_delivered": True,
    "receiver_consumes_candidate_text": True,
    "evidence_class": "infrastructure_only_non_evidence",
    "output_contract": {
        "parser_id": "strict_json_decision_v1",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "decision": {"type": "string", "enum": ["yes", "no", "refuse"]}
            },
            "required": ["decision"],
        },
        "decision_field": "decision",
        "allowed_decisions": ["yes", "no"],
        "refusal_decisions": ["refuse"],
    },
}
ARTIFACTS = {
    "schema": "glee.research.factorial_baseline_artifacts.v1",
    "response_model": {"path": "/fixture/model.json", "sha256": "a" * 64},
    "support_index": {"path": "/fixture/support.json", "sha256": "b" * 64},
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


def _scenario(family: str, index: int) -> Scenario:
    role = ROLES[family][index % 2]
    opponent = ROLES[family][1 - index % 2]
    scenario_id = f"wave5a-{family}-{index}"
    environment_seed = factorial_named_seed(SEED, scenario_id, "environment")
    opponent_seed = factorial_named_seed(SEED, scenario_id, "opponent-policy")
    public = {
        "bargaining": {"max_rounds": 12, "money_to_divide": 100},
        "negotiation": {
            "max_rounds": 12,
            "seller_value": 0.7,
            "buyer_value": 1.1,
            "product_price_order": 100,
        },
        "persuasion": {
            "total_rounds": 4,
            "p": 0.5,
            "v": 2.0,
            "c": 0.0,
            "seller_message_type": "text",
        },
    }[family]
    return Scenario(
        scenario_id=scenario_id,
        game_family=family,
        config_id=f"config-{family}-{index}",
        public_parameters=public,
        candidate_role=role,
        opponent_role=opponent,
        opponent_spec={"archetype": "fixture", "parameters": {}, "seed": opponent_seed},
        seed=environment_seed,
        source="synthetic",
        metadata={
            "fixture": "wave5a_manifest",
            "factorial_randomness": {
                "schema": "glee.factorial.stream_manifest.v2",
                "master_seed_hash": canonical_hash({"master_seed": SEED}),
                "scenario_seed_hash": factorial_stream_hash(
                    scenario_id,
                    "scenario",
                    factorial_scenario_seed(SEED, family, index),
                ),
                "environment_seed_hash": factorial_stream_hash(
                    scenario_id, "environment", environment_seed
                ),
                "opponent_seed_hash": factorial_stream_hash(
                    scenario_id, "opponent-policy", opponent_seed
                ),
            },
        },
    )


def _fixture(rows_per_family: int = 2):
    scenarios = [
        _scenario(family, index)
        for family in FAMILIES
        for index in range(rows_per_family)
    ]
    masks = {scenario.scenario_id: {"inside_support": True} for scenario in scenarios}
    contract = PreOutcomeManifestContract.synthetic(
        rows_per_family=rows_per_family,
        receiver_contract=RECEIVER,
        artifact_provenance=ARTIFACTS,
        scenario_design_sha256=scenario_design_sha256(scenarios),
        model_c_payload_sha256=canonical_hash(MODEL_C),
        support_masks_sha256=support_masks_sha256(masks),
    )
    manifest = build_preoutcome_manifest(
        scenarios,
        contract=contract,
        model_c=MODEL_C,
        support_masks=masks,
    )
    return contract, scenarios, masks, manifest


def _rehash_manifest(manifest: dict) -> None:
    for row in manifest["rows"]:
        row["row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
    manifest["row_root_sha256"] = canonical_hash(
        [row["row_sha256"] for row in manifest["rows"]]
    )
    manifest["manifest_sha256"] = canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )


def _admission(row: dict) -> dict:
    return {
        "schema": OUTCOME_ADMISSION_SCHEMA,
        "manifest_row_sha256": row["row_sha256"],
        "arms": [
            {
                "arm": arm,
                "included_in_intent_to_treat": True,
                "receiver_envelope": {
                    "schema": "glee.research.controlled_receiver_envelope.v1",
                    "status": "ok",
                    "request_sha256": "c" * 64,
                    "response_sha256": "d" * 64,
                    "parsed_output": {"decision": "yes"},
                },
            }
            for arm in FACTORIAL_ARMS
        ],
    }


class PreOutcomeManifestTests(unittest.TestCase):
    def test_synthetic_manifest_is_reconstructible_but_nonproduction(self) -> None:
        contract, _, _, manifest = _fixture()
        result = validate_synthetic_preoutcome_manifest(
            manifest, contract=contract, model_c=MODEL_C
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["evidence_class"], "infrastructure_only_non_evidence")
        self.assertFalse(manifest["outcomes_present"])

    def test_changed_or_missing_receiver_contract_is_rejected(self) -> None:
        contract, _, _, manifest = _fixture()
        changed = copy.deepcopy(manifest)
        changed["rows"][0]["receiver_contract_sha256"] = "f" * 64
        _rehash_manifest(changed)
        with self.assertRaisesRegex(PreOutcomeManifestError, "receiver contract"):
            validate_synthetic_preoutcome_manifest(changed, contract=contract, model_c=MODEL_C)

        missing = copy.deepcopy(manifest)
        del missing["rows"][0]["receiver_contract_sha256"]
        _rehash_manifest(missing)
        with self.assertRaisesRegex(PreOutcomeManifestError, "fields differ"):
            validate_synthetic_preoutcome_manifest(missing, contract=contract, model_c=MODEL_C)

    def test_arm_dependent_economic_or_environment_rng_is_rejected(self) -> None:
        contract, _, _, manifest = _fixture()
        changed = copy.deepcopy(manifest)
        changed["rows"][0]["arm_rng_stream_sha256"]["e1_l1"]["economic"] = "e" * 64
        _rehash_manifest(changed)
        with self.assertRaisesRegex(PreOutcomeManifestError, "arm-dependent"):
            validate_synthetic_preoutcome_manifest(changed, contract=contract, model_c=MODEL_C)

    def test_duplicate_missing_and_wrong_count_scenarios_are_rejected(self) -> None:
        contract, scenarios, masks, _ = _fixture()
        with self.assertRaisesRegex(PreOutcomeManifestError, "duplicate"):
            build_preoutcome_manifest(
                [*scenarios[:-1], scenarios[0]],
                contract=contract,
                model_c=MODEL_C,
                support_masks=masks,
            )
        with self.assertRaisesRegex(PreOutcomeManifestError, "expected"):
            build_preoutcome_manifest(
                scenarios[:-1],
                contract=contract,
                model_c=MODEL_C,
                support_masks={key: value for key, value in masks.items() if key != scenarios[-1].scenario_id},
            )

    def test_outcome_selected_eligibility_is_recomputed_and_rejected(self) -> None:
        contract, _, _, manifest = _fixture()
        changed = copy.deepcopy(manifest)
        target = next(
            row
            for row in changed["rows"]
            if row["family"] == "persuasion" and row["candidate_role"] == "seller"
        )
        target["eligibility"]["eprocess_eligible"] = False
        target["eligibility"]["joint_eligible"] = False
        target["eligibility"]["eprocess_negative_control"] = True
        target["eligibility_hash"] = canonical_hash(target["eligibility"])
        _rehash_manifest(changed)
        with self.assertRaisesRegex(PreOutcomeManifestError, "eligibility changed"):
            validate_synthetic_preoutcome_manifest(changed, contract=contract, model_c=MODEL_C)

    def test_modified_agent_artifact_and_scenario_hashes_are_rejected(self) -> None:
        contract, _, _, manifest = _fixture()
        for field, replacement, message in (
            ("artifact_provenance_sha256", "e" * 64, "artifact provenance"),
            ("scenario_hash", "d" * 64, "scenario hash"),
        ):
            changed = copy.deepcopy(manifest)
            changed["rows"][0][field] = replacement
            _rehash_manifest(changed)
            with self.assertRaisesRegex(PreOutcomeManifestError, message):
                validate_synthetic_preoutcome_manifest(
                    changed, contract=contract, model_c=MODEL_C
                )
        changed = copy.deepcopy(manifest)
        changed["rows"][0]["agent_entrypoints"]["e1_l1"] = "forged:Agent"
        _rehash_manifest(changed)
        with self.assertRaisesRegex(PreOutcomeManifestError, "entrypoint"):
            validate_synthetic_preoutcome_manifest(changed, contract=contract, model_c=MODEL_C)

    def test_coherent_scenario_model_c_and_support_rewrites_are_rejected(self) -> None:
        contract, scenarios, masks, manifest = _fixture()
        replacement = list(scenarios)
        replacement[0] = _scenario(replacement[0].game_family, 100)
        replacement_masks = dict(masks)
        del replacement_masks[scenarios[0].scenario_id]
        replacement_masks[replacement[0].scenario_id] = {"inside_support": True}
        with self.assertRaisesRegex(PreOutcomeManifestError, "scenario design"):
            build_preoutcome_manifest(
                replacement,
                contract=contract,
                model_c=MODEL_C,
                support_masks=replacement_masks,
            )

        changed_model = copy.deepcopy(MODEL_C)
        changed_model["ignored_but_coherently_changed"] = True
        with self.assertRaisesRegex(PreOutcomeManifestError, "Model-C payload"):
            validate_synthetic_preoutcome_manifest(
                manifest, contract=contract, model_c=changed_model
            )

        changed_support = copy.deepcopy(manifest)
        changed_support["rows"][0]["support_mask"] = {"inside_support": False}
        changed_support["rows"][0]["support_mask_hash"] = canonical_hash(
            changed_support["rows"][0]["support_mask"]
        )
        _rehash_manifest(changed_support)
        with self.assertRaisesRegex(PreOutcomeManifestError, "support masks"):
            validate_synthetic_preoutcome_manifest(
                changed_support, contract=contract, model_c=MODEL_C
            )

    def test_scenario_rng_receiver_provenance_and_dependencies_fail_closed(self) -> None:
        contract, scenarios, masks, manifest = _fixture()
        missing_rng = copy.deepcopy(scenarios)
        missing_rng[0].metadata.pop("factorial_randomness")
        missing_contract = replace(
            contract, scenario_design_sha256=scenario_design_sha256(missing_rng)
        )
        with self.assertRaisesRegex(PreOutcomeManifestError, "RNG provenance"):
            build_preoutcome_manifest(
                missing_rng,
                contract=missing_contract,
                model_c=MODEL_C,
                support_masks=masks,
            )
        forged_rng = copy.deepcopy(scenarios)
        forged_rng[0].metadata["factorial_randomness"]["scenario_seed_hash"] = "f" * 64
        forged_contract = replace(
            contract, scenario_design_sha256=scenario_design_sha256(forged_rng)
        )
        with self.assertRaisesRegex(PreOutcomeManifestError, "scenario stream provenance"):
            build_preoutcome_manifest(
                forged_rng,
                contract=forged_contract,
                model_c=MODEL_C,
                support_masks=masks,
            )

        other_receiver = copy.deepcopy(RECEIVER)
        other_receiver["environment_id"] = "conflicting-receiver"
        changed_artifacts = copy.deepcopy(ARTIFACTS)
        changed_artifacts["receiver_contract"] = other_receiver
        changed_contract = replace(
            contract,
            artifact_provenance=changed_artifacts,
            artifact_provenance_sha256=canonical_hash(changed_artifacts),
        )
        with self.assertRaisesRegex(PreOutcomeManifestError, "another receiver"):
            changed_contract.validate(require_production=False)

        with self.assertRaisesRegex(PreOutcomeManifestError, "required source"):
            replace(contract, dependency_sha256={}).validate(require_production=False)

        reversed_rows = copy.deepcopy(manifest)
        reversed_rows["rows"].reverse()
        _rehash_manifest(reversed_rows)
        with self.assertRaisesRegex(PreOutcomeManifestError, "canonical order"):
            validate_synthetic_preoutcome_manifest(
                reversed_rows, contract=contract, model_c=MODEL_C
            )

    def test_mirrored_policy_estimand_report_and_schema_rewrites_are_rejected(self) -> None:
        contract, _, _, manifest = _fixture()
        row_fields = {
            "language_policy": {"schema": "forged"},
            "eprocess_contract": {"threshold": 999},
            "retry_failure_policy": {"retries": 99},
            "missingness_policy": {"exclude_after_assignment": True},
        }
        for field, value in row_fields.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(manifest)
                changed["rows"][0][field] = value
                _rehash_manifest(changed)
                with self.assertRaises(PreOutcomeManifestError):
                    validate_synthetic_preoutcome_manifest(
                        changed, contract=contract, model_c=MODEL_C
                    )
        for field, value in (
            ("estimand_contract", {"primary": ["forged"]}),
            ("report_schema", "forged.report"),
            ("schema", "glee.research.preoutcome_manifest.production.v1"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(manifest)
                changed[field] = value
                _rehash_manifest(changed)
                with self.assertRaises(PreOutcomeManifestError):
                    validate_synthetic_preoutcome_manifest(
                        changed, contract=contract, model_c=MODEL_C
                    )

    def test_malformed_missing_receiver_output_and_exclusion_are_rejected(self) -> None:
        _, _, _, manifest = _fixture()
        row = manifest["rows"][0]
        self.assertTrue(
            validate_outcome_admission(row, _admission(row), receiver_contract=RECEIVER)[
                "passed"
            ]
        )
        missing = _admission(row)
        del missing["arms"][0]["receiver_envelope"]
        with self.assertRaisesRegex(PreOutcomeManifestError, "fields differ"):
            validate_outcome_admission(row, missing, receiver_contract=RECEIVER)
        malformed = _admission(row)
        malformed["arms"][0]["receiver_envelope"]["parsed_output"] = None
        with self.assertRaisesRegex(PreOutcomeManifestError, "malformed"):
            validate_outcome_admission(row, malformed, receiver_contract=RECEIVER)
        missing_decision = _admission(row)
        missing_decision["arms"][0]["receiver_envelope"]["parsed_output"] = {}
        with self.assertRaisesRegex(PreOutcomeManifestError, "fields"):
            validate_outcome_admission(
                row, missing_decision, receiver_contract=RECEIVER
            )
        typed_receiver = copy.deepcopy(RECEIVER)
        typed_receiver["output_contract"]["schema"]["properties"]["confidence"] = {
            "type": "integer"
        }
        typed_receiver["output_contract"]["schema"]["required"].append("confidence")
        typed_row = copy.deepcopy(row)
        typed_row["receiver_contract_sha256"] = canonical_hash(typed_receiver)
        typed_admission = _admission(typed_row)
        for arm in typed_admission["arms"]:
            arm["receiver_envelope"]["parsed_output"] = {
                "decision": "yes",
                "confidence": "high",
            }
        with self.assertRaisesRegex(PreOutcomeManifestError, "type"):
            validate_outcome_admission(
                typed_row, typed_admission, receiver_contract=typed_receiver
            )
        excluded = _admission(row)
        excluded["arms"][0]["included_in_intent_to_treat"] = False
        with self.assertRaisesRegex(PreOutcomeManifestError, "exclusion"):
            validate_outcome_admission(row, excluded, receiver_contract=RECEIVER)

    def test_production_manifest_is_rejected_while_authorization_pin_is_none(self) -> None:
        contract, _, _, manifest = _fixture()
        with self.assertRaisesRegex(PreOutcomeManifestError, "synthetic contracts"):
            validate_production_preoutcome_manifest(
                manifest, contract=contract, model_c=MODEL_C
            )
        production = copy.copy(contract)
        object.__setattr__(production, "schema", "glee.research.preoutcome_manifest.production.v1")
        with self.assertRaisesRegex(PreOutcomeManifestError, "AUTHORIZED_PRODUCTION_CONTRACT_SHA256"):
            production.validate(require_production=True)

    def test_scoped_authorization_pins_only_the_exact_production_contract(self) -> None:
        contract, _, _, _ = _fixture()
        production = replace(
            contract,
            schema="glee.research.preoutcome_manifest.production.v1",
            expected_rows=3600,
            expected_family_counts=tuple((family, 1200) for family in FAMILIES),
        )
        report_pin = production.report_contract_sha256
        manifest_pin = canonical_hash(production.to_dict())
        with mock.patch.object(
            factorial_report, "AUTHORIZED_PRODUCTION_CONTRACT_SHA256", report_pin
        ), mock.patch.object(
            preoutcome_manifest,
            "AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256",
            manifest_pin,
        ):
            production.validate(require_production=True)
            changed = replace(production, scenario_design_sha256="f" * 64)
            with self.assertRaisesRegex(PreOutcomeManifestError, "unauthorized"):
                changed.validate(require_production=True)


if __name__ == "__main__":
    unittest.main()
