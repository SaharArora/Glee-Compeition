from __future__ import annotations

import copy
import unittest
from dataclasses import replace

from glee_eval.data.schemas import EpisodeResult, OpponentSpec, Scenario
from glee_eval.experiments.factorial import (
    ARM_FLAGS,
    ArmResult,
    FactorialRow,
    factorial_named_seed,
    factorial_stream_hash,
)
from glee_eval.experiments.factorial_report import (
    ELIGIBILITY_DERIVATION_SPEC,
    PRODUCTION_CONTRACT_SCHEMA,
    FactorialReportContract,
    FactorialReportError,
    _validate_row,
    build_factorial_report,
    canonical_hash,
    derive_factorial_eligibility,
    validate_factorial_report,
    validate_synthetic_factorial_report,
)
from glee_eval.experiments.receiver_itt import receiver_envelope_itt_payoff


MASTER_SEED = 20260829
FAMILIES = ("bargaining", "negotiation", "persuasion")
ROLES = {
    "bargaining": ("player_1", "player_2"),
    "negotiation": ("seller", "buyer"),
    "persuasion": ("seller", "buyer"),
}
ARTIFACT_PROVENANCE = {
    "schema": "glee.research.factorial_baseline_artifacts.v1",
    "response_model": {"path": "/frozen/model.json", "sha256": "1" * 64},
    "support_index": {"path": "/frozen/support_index.json", "sha256": "2" * 64},
    "baseline_configuration": {"economic_core": "TreatmentOffEconomicCore"},
    "receiver_contract": {
        "schema": "glee.research.receiver_capability.v1",
        "environment_id": "fixture.text_responsive.v1",
        "candidate_text_delivered": True,
        "receiver_consumes_candidate_text": True,
    },
}
ARTIFACT_HASH = canonical_hash(ARTIFACT_PROVENANCE)


def _contract(rows_per_family: int) -> FactorialReportContract:
    return FactorialReportContract.synthetic(
        rows_per_family=rows_per_family,
        master_seed=MASTER_SEED,
        minimum_cell_rows=2,
        required_artifact_provenance_hash=ARTIFACT_HASH,
        research_question_sha256="3" * 64,
    )


def _payoffs(eprocess: float, language: float, interaction: float) -> dict[str, float]:
    # This parameterization makes the three FactorialRow contrasts exactly the
    # requested values, rather than conflating a pure interaction with main effects.
    baseline = 0.4
    return {
        "e0_l0": baseline,
        "e1_l0": baseline + eprocess - interaction / 2.0,
        "e0_l1": baseline + language - interaction / 2.0,
        "e1_l1": baseline + eprocess + language,
    }


def _eligibility(eprocess: bool = True, language: bool = True) -> dict[str, object]:
    return {
        "schema": "glee.research.factorial_eligibility.v1",
        "eprocess_eligible": eprocess,
        "language_eligible": language,
        "joint_eligible": eprocess and language,
        "eprocess_negative_control": not eprocess,
        "language_negative_control": not language,
    }


def _claim(owner: str, stream: str, scenario_id: str) -> dict:
    seed_stream = {
        "economic_policy": "candidate-economic",
        "eprocess_treatment": "candidate-eprocess",
        "language_treatment": "candidate-language",
    }[owner]
    return {
        "name": stream,
        "owner": owner,
        "seed_hash": canonical_hash(
            {
                "stream": stream,
                "seed": factorial_named_seed(MASTER_SEED, scenario_id, seed_stream),
            }
        ),
        "draws": 0,
        "trace_sha256": canonical_hash([]),
    }


def _row(
    family: str,
    index: int,
    *,
    eprocess: float = 0.0,
    language: float = 0.0,
    interaction: float = 0.0,
    eligibility: dict[str, object] | None = None,
) -> FactorialRow:
    role = ROLES[family][index % 2]
    opponent = ROLES[family][1 - index % 2]
    scenario_id = f"synthetic-{family}-{index}"
    environment_seed = factorial_named_seed(MASTER_SEED, scenario_id, "environment")
    opponent_seed = factorial_named_seed(MASTER_SEED, scenario_id, "opponent-policy")
    scenario = Scenario(
        scenario_id=scenario_id,
        game_family=family,
        config_id=f"synthetic-config-{family}-{index % 2}",
        public_parameters=(
            {
                "fixture": family,
                "cell": index % 2,
                "p": 0.5,
                "total_rounds": 4,
                "seller_message_type": "text",
            }
            if family == "persuasion"
            else {"fixture": family, "cell": index % 2}
        ),
        candidate_role=role,
        opponent_role=opponent,
        opponent_spec={"archetype": "fixture", "parameters": {}, "seed": opponent_seed},
        seed=environment_seed,
        metadata={
            "factorial_randomness": {
                "schema": "glee.factorial.stream_manifest.v2",
                "master_seed_hash": canonical_hash({"master_seed": MASTER_SEED}),
                "scenario_seed_hash": "4" * 64,
                "environment_seed_hash": factorial_stream_hash(
                    scenario_id, "environment", environment_seed
                ),
                "opponent_seed_hash": factorial_stream_hash(
                    scenario_id, "opponent-policy", opponent_seed
                ),
            }
        },
    )
    scenario_hash = canonical_hash(scenario)
    configuration_hash = canonical_hash(
        {"config_id": scenario.config_id, "public_parameters": scenario.public_parameters}
    )
    opponent_identity_hash = canonical_hash(
        {"opponent_role": scenario.opponent_role, "opponent_spec": scenario.opponent_spec}
    )
    role_identity_hash = canonical_hash(
        {"candidate_role": scenario.candidate_role, "opponent_role": scenario.opponent_role}
    )
    eligibility = eligibility or _eligibility()
    support_mask = {"inside_support": True, "fixture": family}
    support_mask_hash = canonical_hash(support_mask)
    eligibility_hash = canonical_hash(eligibility)
    support_identity_hash = canonical_hash(
        {
            "support_mask_hash": support_mask_hash,
            "support_index": ARTIFACT_PROVENANCE["support_index"],
        }
    )
    arms: list[ArmResult] = []
    for arm, payoff in _payoffs(eprocess, language, interaction).items():
        use_eprocess, use_language = ARM_FLAGS[arm]
        claims = {"economic_policy": _claim("economic_policy", "economic", scenario_id)}
        if use_eprocess:
            claims["eprocess_treatment"] = _claim(
                "eprocess_treatment", "eprocess", scenario_id
            )
        if use_language:
            claims["language_treatment"] = _claim(
                "language_treatment", "language", scenario_id
            )
        randomness = {
            "schema": "glee.factorial.candidate_randomness.v2",
            "scenario_id": scenario.scenario_id,
            "enabled": {
                "economic": True,
                "eprocess": use_eprocess,
                "language": use_language,
            },
            "claims": claims,
        }
        episode = EpisodeResult(
            episode_id=f"{scenario.scenario_id}-{arm}",
            scenario=scenario,
            candidate_agent_id="wave3_factorial_shared_core",
            opponent_spec=OpponentSpec(
                archetype="fixture",
                game_family=family,
                parameters={},
                seed=opponent_seed,
            ),
            full_transcript=[],
            decision_records=[],
            terminal_outcome={"fixture": True},
            candidate_payoff=payoff,
            opponent_payoff=1.0 - payoff,
            metrics={},
        )
        arms.append(
            ArmResult(
                arm=arm,
                use_eprocess=use_eprocess,
                use_language=use_language,
                candidate_payoff=payoff,
                opponent_payoff=1.0 - payoff,
                scenario_hash=scenario_hash,
                initial_state_hash="7" * 64,
                configuration_hash=configuration_hash,
                opponent_identity_hash=opponent_identity_hash,
                role_identity_hash=role_identity_hash,
                support_mask_hash=support_mask_hash,
                support_identity_hash=support_identity_hash,
                eligibility_hash=eligibility_hash,
                environment_stream_hash=factorial_stream_hash(
                    scenario_id, "environment", environment_seed
                ),
                nature_stream_hash=factorial_stream_hash(
                    scenario_id, "environment", environment_seed
                ),
                nature_trace_hash=canonical_hash([]),
                opponent_stream_hash=factorial_stream_hash(
                    scenario_id, "opponent-policy", opponent_seed
                ),
                economic_stream_hash=factorial_stream_hash(
                    scenario_id,
                    "candidate-economic",
                    factorial_named_seed(MASTER_SEED, scenario_id, "candidate-economic"),
                ),
                artifact_provenance_hash=ARTIFACT_HASH,
                artifact_provenance=copy.deepcopy(ARTIFACT_PROVENANCE),
                randomness_audit_hash=canonical_hash(randomness),
                randomness_audit=randomness,
                episode_hash=canonical_hash(episode),
                unlabeled_record_hash="b" * 64,
                non_language_record_hash="c" * 64,
                non_eprocess_record_hash="d" * 64,
                episode=episode,
            )
        )
    return FactorialRow(
        key=f"{family}:{scenario.scenario_id}:{role}",
        family=family,
        candidate_role=role,
        scenario_hash=scenario_hash,
        initial_state_hash="7" * 64,
        support_mask=support_mask,
        support_mask_hash=support_mask_hash,
        eligibility=eligibility,
        eligibility_hash=eligibility_hash,
        arms=tuple(arms),
    )


def _rows(
    rows_per_family: int = 2,
    *,
    eprocess: float = 0.0,
    language: float = 0.0,
    interaction: float = 0.0,
) -> list[FactorialRow]:
    return [
        _row(
            family,
            index,
            eprocess=eprocess,
            language=language,
            interaction=interaction,
        )
        for family in FAMILIES
        for index in range(rows_per_family)
    ]


class FactorialReportTests(unittest.TestCase):
    def test_zero_effect_fixture_is_exactly_nonconfirming(self) -> None:
        rows = _rows()
        report = build_factorial_report(rows, _contract(2))
        for contrast in ("eprocess_main_effect", "language_main_effect", "interaction"):
            self.assertEqual(report["estimands"]["overall"][contrast]["effect"], 0.0)
        tests = report["hypothesis_tests"]
        self.assertEqual(
            tests["confirmatory_primary"]["hypothesis"]["name"], "language"
        )
        self.assertEqual(
            tests["confirmatory_primary"]["hypothesis"]["decision"],
            "nonconfirming",
        )
        self.assertEqual(
            {row["decision"] for row in tests["key_secondary_holm"]["hypotheses"]},
            {"nonconfirming"},
        )
        validation = validate_synthetic_factorial_report(rows, report, _contract(2))
        self.assertTrue(validation["passed"])
        self.assertEqual(validation["evidence_class"], "synthetic_arithmetic_only_not_production")

    def test_eprocess_only_fixture_recovers_eprocess_main_effect(self) -> None:
        report = build_factorial_report(_rows(eprocess=0.06), _contract(2))
        self.assertAlmostEqual(
            report["estimands"]["overall"]["eprocess_main_effect"]["effect"], 0.06
        )
        self.assertEqual(report["estimands"]["overall"]["language_main_effect"]["effect"], 0.0)
        decisions = {
            row["name"]: row["decision"]
            for row in report["hypothesis_tests"]["key_secondary_holm"]["hypotheses"]
        }
        self.assertEqual(decisions["eprocess"], "improvement")
        self.assertEqual(
            report["hypothesis_tests"]["confirmatory_primary"]["hypothesis"]["decision"],
            "nonconfirming",
        )

    def test_language_only_fixture_recovers_language_main_effect(self) -> None:
        report = build_factorial_report(_rows(language=0.04), _contract(2))
        self.assertAlmostEqual(
            report["estimands"]["overall"]["language_main_effect"]["effect"], 0.04
        )
        self.assertEqual(report["estimands"]["overall"]["interaction"]["effect"], 0.0)

    def test_pure_interaction_fixture_recovers_only_interaction_target(self) -> None:
        report = build_factorial_report(_rows(interaction=0.03), _contract(2))
        self.assertAlmostEqual(report["estimands"]["overall"]["interaction"]["effect"], 0.03)
        self.assertEqual(report["estimands"]["overall"]["eprocess_main_effect"]["effect"], 0.0)
        self.assertEqual(report["estimands"]["overall"]["language_main_effect"]["effect"], 0.0)

    def test_report_reconstructs_receiver_itt_natural_payoff(self) -> None:
        rows = _rows()
        row = rows[0]
        arm = row.arms[1]
        receiver = {
            "schema": "glee.research.controlled_receiver_envelope.v1",
            "status": "refusal",
            "attempts": 1,
            "request_sha256": "c" * 64,
            "response_sha256": "d" * 64,
            "parsed_output": None,
            "applied_environment_action": "no",
            "ordinary_environment_continued": True,
            "terminal_candidate_payoff": arm.candidate_payoff,
        }
        episode = replace(
            arm.episode,
            replay_artifacts={"controlled_receiver_envelope": receiver},
        )
        changed_arm = replace(
            arm,
            episode=episode,
            episode_hash=canonical_hash(episode),
            receiver_itt_payoff=receiver_envelope_itt_payoff(receiver),
        )
        rows[0] = replace(
            row,
            arms=tuple(changed_arm if value.arm == arm.arm else value for value in row.arms),
        )
        build_factorial_report(rows, _contract(2))
        bad_arm = replace(
            changed_arm,
            receiver_itt_payoff={
                **changed_arm.receiver_itt_payoff,
                "terminal_candidate_payoff": arm.candidate_payoff + 1,
            },
        )
        rows[0] = replace(
            rows[0],
            arms=tuple(bad_arm if value.arm == arm.arm else value for value in rows[0].arms),
        )
        with self.assertRaisesRegex(FactorialReportError, "does not reconstruct"):
            build_factorial_report(rows, _contract(2))

    def test_eligible_subgroup_effect_is_separate_from_aggregate(self) -> None:
        rows: list[FactorialRow] = []
        for family in FAMILIES:
            for index in range(4):
                eligible = index < 2
                rows.append(
                    _row(
                        family,
                        index,
                        eprocess=0.08 if eligible else 0.0,
                        language=0.06 if eligible else 0.0,
                        eligibility=_eligibility(eligible, eligible),
                    )
                )
        report = build_factorial_report(rows, _contract(4))
        self.assertAlmostEqual(
            report["estimands"]["overall"]["eprocess_main_effect"]["effect"], 0.04
        )
        self.assertAlmostEqual(
            report["estimands"]["eprocess_eligible"]["eprocess_main_effect"]["effect"],
            0.08,
        )
        self.assertEqual(
            report["estimands"]["eprocess_negative_control"]["eprocess_main_effect"]["effect"],
            0.0,
        )

    def test_arm_and_row_order_do_not_change_report_or_hashes(self) -> None:
        rows = _rows()
        reordered = [replace(row, arms=tuple(reversed(row.arms))) for row in reversed(rows)]
        self.assertEqual(
            build_factorial_report(rows, _contract(2)),
            build_factorial_report(reordered, _contract(2)),
        )

    def test_missing_arm_and_duplicate_scenario_are_rejected(self) -> None:
        rows = _rows()
        malformed = list(rows)
        malformed[0] = replace(malformed[0], arms=malformed[0].arms[:3])
        with self.assertRaisesRegex(FactorialReportError, "all four arms"):
            build_factorial_report(malformed, _contract(2))
        duplicate = list(rows)
        duplicate[-1] = duplicate[0]
        with self.assertRaises(FactorialReportError):
            build_factorial_report(duplicate, _contract(2))

    def test_malformed_secondary_holm_and_output_hash_are_rejected(self) -> None:
        rows = _rows(eprocess=0.02)
        report = build_factorial_report(rows, _contract(2))
        report["hypothesis_tests"]["key_secondary_holm"]["hypotheses"][0][
            "holm_adjusted_p"
        ] = 0.777
        with self.assertRaisesRegex(FactorialReportError, "does not reconstruct"):
            validate_synthetic_factorial_report(rows, report, _contract(2))

    def test_small_synthetic_contract_cannot_receive_production_validation(self) -> None:
        rows = _rows()
        report = build_factorial_report(rows, _contract(2))
        with self.assertRaisesRegex(FactorialReportError, "production contract schema"):
            validate_factorial_report(rows, report, _contract(2))

    def test_no_unselected_language_environment_can_claim_production_status(self) -> None:
        contract = FactorialReportContract(
            required_artifact_provenance_hash="1" * 64,
            research_question_sha256="2" * 64,
            config_catalogue_sha256="3" * 64,
            opponent_population_sha256="4" * 64,
            scenario_manifest_sha256="5" * 64,
            evaluator_code_sha256="6" * 64,
            agent_entrypoints_sha256="7" * 64,
            execution_command_sha256="8" * 64,
            eligibility_derivation_sha256=canonical_hash(ELIGIBILITY_DERIVATION_SPEC),
        )
        with self.assertRaisesRegex(FactorialReportError, "no production contract is authorized"):
            contract.validate_production_freeze()

    def test_rng_crossover_and_post_outcome_eligibility_tamper_are_rejected(self) -> None:
        rows = _rows()
        arm = rows[0].arms[3]
        audit = copy.deepcopy(arm.randomness_audit)
        audit["claims"]["language_treatment"]["name"] = "economic"
        bad_arm = replace(arm, randomness_audit=audit, randomness_audit_hash=canonical_hash(audit))
        rows[0] = replace(rows[0], arms=(*rows[0].arms[:3], bad_arm))
        with self.assertRaisesRegex(FactorialReportError, "crossed RNG"):
            build_factorial_report(rows, _contract(2))

        rows = _rows()
        bad_eligibility = dict(rows[0].eligibility)
        bad_eligibility["joint_eligible"] = False
        rows[0] = replace(
            rows[0],
            eligibility=bad_eligibility,
            eligibility_hash=canonical_hash(bad_eligibility),
            arms=tuple(
                replace(arm, eligibility_hash=canonical_hash(bad_eligibility))
                for arm in rows[0].arms
            ),
        )
        with self.assertRaisesRegex(FactorialReportError, "joint eligibility"):
            build_factorial_report(rows, _contract(2))

    def test_exact_rng_derivation_aliasing_and_economic_trace_divergence_are_rejected(self) -> None:
        rows = _rows()
        changed_arms = []
        for arm in rows[0].arms:
            audit = copy.deepcopy(arm.randomness_audit)
            for claim in audit["claims"].values():
                claim["seed_hash"] = "f" * 64
            changed_arms.append(
                replace(arm, randomness_audit=audit, randomness_audit_hash=canonical_hash(audit))
            )
        rows[0] = replace(rows[0], arms=tuple(changed_arms))
        with self.assertRaisesRegex(FactorialReportError, "forged .* seed provenance"):
            build_factorial_report(rows, _contract(2))

        rows = _rows()
        arm = rows[0].arms[1]
        audit = copy.deepcopy(arm.randomness_audit)
        audit["claims"]["economic_policy"]["trace_sha256"] = "e" * 64
        bad = replace(arm, randomness_audit=audit, randomness_audit_hash=canonical_hash(audit))
        rows[0] = replace(rows[0], arms=(rows[0].arms[0], bad, *rows[0].arms[2:]))
        with self.assertRaisesRegex(FactorialReportError, "arm-dependent economic_policy RNG trace"):
            build_factorial_report(rows, _contract(2))

    def test_episode_opponent_and_realized_nature_tampering_are_rejected(self) -> None:
        rows = _rows()
        arm = rows[0].arms[-1]
        episode = replace(
            arm.episode,
            opponent_spec=OpponentSpec(
                archetype="forged-other",
                game_family=rows[0].family,
                parameters={},
                seed=999,
            ),
            full_transcript=[
                {
                    "round": 1,
                    "role": "nature",
                    "action_type": "nature_quality",
                    "quality": "forged",
                }
            ],
        )
        bad = replace(arm, episode=episode, episode_hash=canonical_hash(episode))
        rows[0] = replace(rows[0], arms=(*rows[0].arms[:-1], bad))
        with self.assertRaisesRegex(FactorialReportError, "nature trace|episode opponent"):
            build_factorial_report(rows, _contract(2))

    def test_arbitrary_balanced_role_names_are_rejected(self) -> None:
        rows = _rows()
        row = rows[0]
        forged_scenario = replace(
            row.arms[0].episode.scenario,
            candidate_role="fake_role_0",
            opponent_role="fake_role_1",
        )
        scenario_hash = canonical_hash(forged_scenario)
        role_hash = canonical_hash(
            {"candidate_role": "fake_role_0", "opponent_role": "fake_role_1"}
        )
        opponent_hash = canonical_hash(
            {
                "opponent_role": "fake_role_1",
                "opponent_spec": forged_scenario.opponent_spec,
            }
        )
        forged_arms = []
        for arm in row.arms:
            episode = replace(arm.episode, scenario=forged_scenario)
            forged_arms.append(
                replace(
                    arm,
                    scenario_hash=scenario_hash,
                    role_identity_hash=role_hash,
                    opponent_identity_hash=opponent_hash,
                    episode=episode,
                    episode_hash=canonical_hash(episode),
                )
            )
        rows[0] = replace(
            row,
            key=f"{row.family}:{forged_scenario.scenario_id}:fake_role_0",
            candidate_role="fake_role_0",
            scenario_hash=scenario_hash,
            arms=tuple(forged_arms),
        )
        with self.assertRaisesRegex(FactorialReportError, "invalid family role"):
            build_factorial_report(rows, _contract(2))

    def test_production_eligibility_reconstructs_without_outcomes(self) -> None:
        row = _row("persuasion", 0, eligibility=_eligibility(True, True))
        scenario = row.arms[0].episode.scenario
        state = {
            "configuration": dict(scenario.public_parameters),
            "round": 1,
            "source": scenario.source,
        }
        from glee_eval.response_models.runtime import persuasion_keys

        key = next(
            key
            for key in persuasion_keys(state, "yes", "high-quality", "I recommend buying.")
            if key not in {"__global__", "implicit_global"}
        )
        model = {
            "min_support": 30,
            "families": {
                "persuasion": {
                    "buckets": {
                        key: {
                            "probability": 0.7,
                            "trials": 100,
                            "support_quality": 1.0,
                        }
                    }
                }
            },
        }
        receiver = ARTIFACT_PROVENANCE["receiver_contract"]
        expected = derive_factorial_eligibility(
            scenario, model_c=model, receiver_contract=receiver
        )
        self.assertEqual(expected, _eligibility(True, True))
        outcome_selected = _eligibility(False, False)
        bad_row = replace(
            row,
            eligibility=outcome_selected,
            eligibility_hash=canonical_hash(outcome_selected),
            arms=tuple(
                replace(arm, eligibility_hash=canonical_hash(outcome_selected))
                for arm in row.arms
            ),
        )
        production = replace(_contract(2), schema=PRODUCTION_CONTRACT_SCHEMA)
        with self.assertRaisesRegex(FactorialReportError, "pre-outcome inputs"):
            _validate_row(
                bad_row,
                production,
                model_c=model,
                receiver_contract=receiver,
            )


if __name__ == "__main__":
    unittest.main()
