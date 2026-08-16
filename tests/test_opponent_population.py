from __future__ import annotations

import random
import statistics as st
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from glee_eval.opponents.policies import PolicyFactory
from glee_eval.population.opponent_fit import (
    ARCHETYPE_BANDS,
    OpponentPopulation,
    extract_joint_bundle_observations,
    fit_opponent_population,
)
from glee_eval.population.sampler import ARCHETYPES, sample_opponent_spec
from glee_eval.population.crossfit import build_manifest, row_fold
from glee_eval.storage.trajectories import canonical_json_sha256, write_json, write_json_atomic, write_jsonl


def _quantile_table(low: float, high: float) -> dict[str, float]:
    return {f"{0.01 * i:.2f}": low + (high - low) * (i - 1) / 98.0 for i in range(1, 100)}


def _payload() -> dict:
    return {
        "archetype_bands": {name: list(band) for name, band in ARCHETYPE_BANDS.items()},
        "inverted_parameters": ["concession_rate", "accept_margin", "trust_prior"],
        "families": {
            "bargaining": {
                "target_share": _quantile_table(0.48, 0.66),
                "accept_threshold": _quantile_table(0.40, 0.50),
                "concession_rate": _quantile_table(-0.05, 0.12),
            },
            "persuasion": {
                "trust_prior": _quantile_table(0.30, 1.0),
                "honesty": _quantile_table(0.70, 1.0),
                "yes_on_low_rate": _quantile_table(0.0, 0.60),
            },
        },
    }


class OpponentPopulationDrawTests(unittest.TestCase):
    def test_atomic_json_replaces_complete_file_without_temp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"artifact.json"
            path.write_text('{"old":true}\n')
            write_json_atomic(path,{"large":[{"value":index} for index in range(1000)]})
            self.assertEqual(__import__('json').loads(path.read_text())["large"][-1]["value"],999)
            self.assertEqual(list(Path(tmp).glob(".artifact.json.*.tmp")),[])

    def test_atomic_stream_failure_preserves_previous_complete_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"artifact.json"; path.write_text('{"old":true}\n')
            def fail(payload, handle, **kwargs):
                handle.write('{"partial":')
                raise RuntimeError("injected stream failure")
            with patch("glee_eval.storage.trajectories.json.dump",side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,"injected"):
                    write_json_atomic(path,{"new":True})
            self.assertEqual(path.read_text(),'{"old":true}\n')
            self.assertEqual(list(Path(tmp).glob(".artifact.json.*.tmp")),[])

    def test_streaming_writer_forbids_monolithic_json_and_root_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload={"rows":[{"index":index,"value":"x"*40} for index in range(5000)]}
            with patch("glee_eval.storage.trajectories.json.dumps",side_effect=AssertionError("monolithic dumps")), \
                 patch("glee_eval.storage.trajectories.to_jsonable",side_effect=AssertionError("root conversion")):
                write_json_atomic(Path(tmp)/"artifact.json",payload)
            self.assertEqual(__import__('json').loads((Path(tmp)/"artifact.json").read_text())["rows"][-1]["index"],4999)

    def test_canonical_hash_stream_is_deterministic_for_enum_and_dataclass(self) -> None:
        from dataclasses import dataclass
        from enum import Enum
        class Kind(str,Enum): A="a"
        @dataclass
        class Record: kind: Kind; count: int
        left={"z":[Record(Kind.A,2)],"a":1}; right={"a":1,"z":[{"kind":"a","count":2}]}
        with patch("glee_eval.storage.trajectories.json.dumps",side_effect=AssertionError("monolithic dumps")):
            self.assertEqual(canonical_json_sha256(left),canonical_json_sha256(right))

    def test_compact_bundle_streaming_peak_does_not_scale_with_output_bytes(self) -> None:
        import tracemalloc
        with tempfile.TemporaryDirectory() as tmp:
            peaks=[]; sizes=[]
            for count in (200,2000):
                entry={"family":"persuasion","channel":"persuasion|buyer_yes","canonical_fit_reference":"joint_model.response_estimators.persuasion","canonical_fit_sha256":"a"*64,"channel_support":{"rows":10,"games":2}}
                payload={"joint_model":{"response_estimators":{"persuasion":{"status":"ok"}}},"joint_bundles":{"persuasion":[{"bundle_id":str(i),"response_estimator":{"trust_prior":entry}} for i in range(count)]}}
                path=Path(tmp)/f"{count}.json"; tracemalloc.start(); write_json_atomic(path,payload); _,peak=tracemalloc.get_traced_memory(); tracemalloc.stop()
                peaks.append(peak); sizes.append(path.stat().st_size)
            self.assertGreater(sizes[1],sizes[0]*9)
            self.assertLess(peaks[1],peaks[0]*3)

    def setUp(self) -> None:
        self.population = OpponentPopulation(_payload())

    def test_archetype_bands_order_aggression(self) -> None:
        rng = random.Random(0)
        means = {}
        for archetype in ("conceding", "fairness_sensitive", "rational", "aggressive_extractor"):
            draws = [self.population.draw("bargaining", "target_share", archetype, rng) for _ in range(400)]
            means[archetype] = st.mean(draws)

        self.assertLess(means["conceding"], means["fairness_sensitive"])
        self.assertLess(means["fairness_sensitive"], means["rational"])
        self.assertLess(means["rational"], means["aggressive_extractor"])

    def test_inverted_parameters_read_from_the_other_end(self) -> None:
        """A high concession rate is a soft opponent, so aggressors must draw low."""

        rng = random.Random(1)
        aggressive = st.mean(self.population.draw("bargaining", "concession_rate", "aggressive_extractor", rng) for _ in range(400))
        soft = st.mean(self.population.draw("bargaining", "concession_rate", "conceding", rng) for _ in range(400))

        self.assertLess(aggressive, soft)

    def test_draws_stay_inside_the_observed_range(self) -> None:
        rng = random.Random(2)
        for archetype in ARCHETYPES:
            for _ in range(50):
                value = self.population.draw("bargaining", "target_share", archetype, rng)
                self.assertGreaterEqual(value, 0.48)
                self.assertLessEqual(value, 0.66)

    def test_unknown_parameter_returns_none_rather_than_guessing(self) -> None:
        self.assertIsNone(self.population.draw("bargaining", "not_a_parameter", "rational", random.Random(3)))
        self.assertIsNone(self.population.draw("negotiation", "target_share", "rational", random.Random(3)))

    def test_unknown_archetype_falls_back_to_the_middle_band(self) -> None:
        rng = random.Random(4)
        value = self.population.draw("bargaining", "target_share", "not_an_archetype", rng)
        self.assertGreaterEqual(value, 0.48)
        self.assertLessEqual(value, 0.66)

    def test_load_from_directory_and_missing_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp) / "opponent_population.json", _payload())
            self.assertIsNotNone(OpponentPopulation.load(tmp))
        self.assertIsNone(OpponentPopulation.load(None))
        self.assertIsNone(OpponentPopulation.load("/nonexistent/opponent_population.json"))

    def test_joint_draw_preserves_bundle_and_role(self) -> None:
        payload = _payload()
        payload["schema_version"] = 2
        payload["joint_bundles"] = {
            "bargaining": [
                {
                    "bundle_id": "soft",
                    "role": "player_1",
                    "parameters": {"target_share": 0.48, "concession_rate": 0.12},
                    "latent_percentile": 0.1,
                    "config_signature": "different",
                    "coarse_config_signature": "different",
                    "weight": 1,
                },
                {
                    "bundle_id": "hard",
                    "role": "player_2",
                    "parameters": {"target_share": 0.66, "concession_rate": -0.05},
                    "latent_percentile": 0.9,
                    "config_signature": "different",
                    "coarse_config_signature": "different",
                    "weight": 1,
                },
            ]
        }
        population = OpponentPopulation(payload)
        drawn = population.sample_bundle("bargaining", "player_2", {}, random.Random(9))
        self.assertEqual(drawn["bundle_id"], "hard")
        self.assertEqual(drawn["role"], "player_2")
        self.assertEqual(drawn["draw_fallback_level"], "role")
        self.assertEqual((drawn["parameters"]["target_share"], drawn["parameters"]["concession_rate"]), (0.66, -0.05))
        spec = sample_opponent_spec(
            "bargaining", random.Random(9), population=population,
            opponent_role="player_2", scenario_config={},
        )
        self.assertEqual(spec.parameters["action_noise"], 0.0)
        self.assertEqual(spec.parameters["action_noise_source"], "explicit_zero_when_bundle_residual_unidentified")
        self.assertEqual(spec.parameters["parameter_source"], "fitted_joint_population")


class JointBundleExtractionTests(unittest.TestCase):
    def test_bargaining_intercept_is_first_offer_not_all_offer_mean(self) -> None:
        events = []
        for game_index in range(2):
            for round_number, gain in ((1, 60.0), (3, 50.0)):
                events.append({
                    "game_family": "bargaining", "game_id": f"g{game_index}", "config_id": "c",
                    "role": "player_1", "player_1_model": "m", "player_2_model": "other",
                    "action_type": "offer", "numeric_action": gain, "round": round_number,
                    "configuration": {"money_to_divide": 100},
                    "raw_record": {"alice_gain": gain, "bob_gain": 100 - gain},
                })
        [row] = extract_joint_bundle_observations(events)
        self.assertAlmostEqual(row["parameters"]["target_share"], 0.60)
        self.assertAlmostEqual(row["parameters"]["concession_rate"], 0.10)
        self.assertEqual(row["parameter_game_counts"]["target_share"], 2)

    def test_negotiation_intercept_slope_and_acceptance_crossing_match_policy_units(self) -> None:
        events = []
        config = {"seller_value": 0.5, "buyer_value": 1.0, "product_price_order": 100}
        for game_index in range(2):
            for round_number, price in ((1, 90.0), (3, 80.0)):
                events.append({"game_family": "negotiation", "game_id": f"g{game_index}", "config_id": "c",
                    "role": "seller", "player_1_model": "m", "player_2_model": "o", "action_type": "offer",
                    "numeric_action": price, "round": round_number, "configuration": config,
                    "raw_record": {"product_price": price}})
        decisions = ((60.0, "RejectOffer"), (70.0, "AcceptOffer"), (80.0, "AcceptOffer"))
        for index in range(30):
            price, decision = decisions[index % 3]
            events.append({"game_family": "negotiation", "game_id": f"g{index % 2}", "config_id": "c",
                "role": "seller", "player_1_model": "m", "player_2_model": "o", "action_type": "decision",
                "round": 5, "configuration": config, "raw_record": {"decision": decision},
                "transcript_so_far": [{"action_type": "offer", "numeric_action": price, "round": 5}]})
        [row] = extract_joint_bundle_observations(events)
        self.assertAlmostEqual(row["parameters"]["aspiration_price"], 0.9)
        self.assertAlmostEqual(row["parameters"]["concession_rate"], 0.1)
        self.assertAlmostEqual(row["parameters"]["accept_margin"], 0.15)

    def test_persuasion_honesty_is_yes_given_high_not_overall_truth(self) -> None:
        events = []
        for game_index in range(2):
            for quality in ("high-quality", "low-quality"):
                events.append({"game_family": "persuasion", "game_id": f"g{game_index}", "config_id": "c",
                    "role": "seller", "player_1_model": "m", "player_2_model": "o",
                    "action_type": "recommendation", "round": 1,
                    "transcript_so_far": [{"role": "nature", "action_type": "nature_quality", "round": 1, "quality": quality}],
                    "raw_record": {"decision": "yes"}})
        [row] = extract_joint_bundle_observations(events)
        self.assertEqual(row["parameters"]["honesty"], 1.0)
        self.assertEqual(row["parameters"]["yes_on_low_rate"], 1.0)

    def test_persuasion_buyer_has_joint_yes_and_no_rates_and_game_support(self) -> None:
        events = []
        for game_index in range(2):
            for recommendation, decision in (("yes", "yes"), ("no", "no")):
                events.append(
                    {
                        "game_family": "persuasion",
                        "game_id": f"g{game_index}",
                        "config_id": "c",
                        "role": "buyer",
                        "player_1_model": "seller-model",
                        "player_2_model": "buyer-model",
                        "action_type": "buy_decision",
                        "raw_record": {"decision": decision},
                        "transcript_so_far": [
                            {"role": "seller", "buy_no_buy": recommendation, "round": 1}
                        ],
                        "round": 1,
                    }
                )
        [row] = extract_joint_bundle_observations(events)
        self.assertEqual(row["player_model"], "buyer-model")
        self.assertEqual(row["role"], "buyer")
        self.assertEqual(row["game_count"], 2)
        self.assertEqual(row["parameters"], {"trust_prior": 1.0, "buy_after_no_rate": 0.0})


class SamplerCalibrationTests(unittest.TestCase):
    def test_archetype_now_determines_parameters(self) -> None:
        population = OpponentPopulation(_payload())
        by_archetype: dict[str, list[float]] = {}
        for seed in range(3000):
            spec = sample_opponent_spec("bargaining", random.Random(seed), population=population)
            by_archetype.setdefault(spec.archetype, []).append(spec.parameters["target_share"])

        aggressive = st.mean(by_archetype["aggressive_extractor"])
        conceding = st.mean(by_archetype["conceding"])
        self.assertGreater(aggressive - conceding, 0.05, "archetype should move target_share materially")

    def test_parameter_source_is_recorded(self) -> None:
        population = OpponentPopulation(_payload())
        fitted = sample_opponent_spec("bargaining", random.Random(1), population=population)
        self.assertEqual(fitted.parameters["parameter_source"], "fitted_real_population")

    def test_uncalibrated_fallback_is_labelled_not_silent(self) -> None:
        empty = OpponentPopulation({"families": {}, "archetype_bands": {}})
        spec = sample_opponent_spec("bargaining", random.Random(1), population=empty)

        self.assertEqual(spec.parameters["parameter_source"], "uncalibrated_hand_picked")
        self.assertIn("target_share", spec.parameters)

    def test_negotiation_falls_back_when_family_is_unfitted(self) -> None:
        spec = sample_opponent_spec("negotiation", random.Random(1), population=OpponentPopulation(_payload()))

        self.assertEqual(spec.parameters["parameter_source"], "uncalibrated_hand_picked")
        self.assertIn("accept_margin", spec.parameters)


class PersuasionRateSemanticsTests(unittest.TestCase):
    """Fitted rates are probabilities and must be applied as such."""

    def _buy_rate(self, trust: float, recommendation: str, rounds: int = 400) -> float:
        buys = 0
        for round_number in range(1, rounds + 1):
            policy = PolicyFactory.create(
                "persuasion",
                {"archetype": "rational", "parameters": {"trust_prior": trust}, "seed": round_number * 7},
            )
            state = type(
                "S",
                (),
                {
                    "role": "buyer",
                    "round": 1,
                    "horizon": 20,
                    "game_family": "persuasion",
                    "public_parameters": {},
                    "private_parameters": {},
                    "valid_action_schema": {"kind": "buy_decision"},
                    "visible_transcript": [{"role": "seller", "buy_no_buy": recommendation}],
                    "metadata": {},
                    "game_id": "g",
                    "scenario_id": "s",
                },
            )()
            buys += int(policy.decide(state).buy_no_buy == "yes")
        return buys / rounds

    def test_trust_prior_behaves_like_a_probability(self) -> None:
        low = self._buy_rate(0.2, "yes")
        high = self._buy_rate(0.8, "yes")

        self.assertLess(low, 0.4)
        self.assertGreater(high, 0.6)
        self.assertGreater(high, low)

    def test_a_no_recommendation_is_almost_never_bought(self) -> None:
        self.assertLess(self._buy_rate(0.9, "no"), 0.1)


class FitSmokeTests(unittest.TestCase):
    def test_unavailable_canonical_fit_removes_preexisting_response_proxies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); events=[]
            for game in range(25):
                for quality in ("high-quality","low-quality"):
                    events.append({"game_family":"persuasion","game_id":f"g{game}","config_id":"c","role":"seller","player_1_model":"m","action_type":"recommendation","round":game+1,"configuration":{"p":.5,"v":2,"c":0,"product_price":100},"round_quality":quality,"raw_record":{"decision":"yes"}})
            write_jsonl(root/"processed"/"events.jsonl",events)
            unavailable={"status":"unavailable","reason":"fixture"}
            with patch("glee_eval.population.opponent_fit.fit_hierarchical_responses",return_value=unavailable):
                payload=fit_opponent_population(root,root/"out")
            self.assertEqual(payload["joint_bundles"].get("persuasion",[]),[])
            self.assertEqual(payload["joint_model"]["response_estimator_reference_schema"]["references_by_family"].get("persuasion",0),0)

    def test_outer_fold_is_excluded_from_marginals_observations_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            for model_index in range(15):
                for game_index in range(3):
                    events.append({
                        "event_id": f"e-{model_index}-{game_index}",
                        "game_family": "bargaining", "game_id": f"g-{model_index}-{game_index}",
                        "config_id": f"c-{model_index}-{game_index}", "role": "player_1",
                        "player_1_model": f"m{model_index:02d}", "player_2_model": "opponent",
                        "action_type": "offer", "round": 1,
                        "configuration": {"money_to_divide": 100, "max_rounds": 12,
                                          "delta_1": .9, "delta_2": .9},
                        "numeric_action": 50.0,
                        "raw_record": {"alice_gain": 50.0, "bob_gain": 50.0},
                    })
            manifest = build_manifest(events)
            excluded_fold = 0
            for event in events:
                if row_fold(event, "actor", manifest) == excluded_fold:
                    event["numeric_action"] = 99.0
                    event["raw_record"] = {"alice_gain": 99.0, "bob_gain": 1.0}
            write_jsonl(root / "processed" / "events.jsonl", events)
            payload = fit_opponent_population(
                root, root / "out", crossfit_manifest=manifest,
                excluded_fold=excluded_fold, crossfit_axis="actor",
            )
            self.assertEqual(payload["events_scanned"], 30)
            self.assertEqual(payload["events_skipped_by_split"], 15)
            self.assertTrue(all(value == 0.5 for value in payload["families"]["bargaining"]["target_share"].values()))
            expected = manifest["folds_manifest"]["actor"][str(excluded_fold)]
            self.assertEqual(payload["crossfit_provenance"], {
                "axis": "actor", "fold": excluded_fold, "folds": 3, "holdout_fraction": 1 / 3,
                "manifest_sha256": manifest["manifest_sha256"],
                "training_key_hashes": expected["training_key_hashes"],
                "evaluation_key_hashes": expected["evaluation_key_hashes"],
            })

    def test_fit_runs_and_reports_unfitted_parameters_on_thin_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = [
                {
                    "game_family": "bargaining",
                    "game_id": f"g{i}",
                    "config_id": "c1",
                    "role": "player_1",
                    "action_type": "offer",
                    "numeric_action": 55.0,
                    "round": 1,
                    "configuration": {"money_to_divide": 100},
                }
                for i in range(5)
            ]
            write_jsonl(root / "processed" / "events.jsonl", events)

            payload = fit_opponent_population(root, root / "out")
            schema=payload["joint_model"]["response_estimator_reference_schema"]
            self.assertEqual(schema["canonical_full_fit_count"],3)
            self.assertEqual(payload["joint_model"]["serialization"]["writer"],"atomic_streaming_json")
            for bundles in payload["joint_bundles"].values():
                for bundle in bundles:
                    for entry in bundle["response_estimator"].values():
                        self.assertNotIn("inner_cv_convergence",entry)
                        self.assertEqual(set(("family","channel","canonical_fit_reference"))-set(entry),set())

            self.assertEqual(payload["events_scanned"], 5)
            # Far below the minimum segment count, so nothing may be silently invented.
            self.assertTrue(payload["unfitted_parameters"])
            self.assertIsNone(payload["families"]["bargaining"]["target_share"])

    def test_missing_events_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                fit_opponent_population(tmp, Path(tmp) / "out")


if __name__ == "__main__":
    unittest.main()
