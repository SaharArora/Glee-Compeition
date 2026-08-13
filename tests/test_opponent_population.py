from __future__ import annotations

import random
import statistics as st
import tempfile
import unittest
from pathlib import Path

from glee_eval.opponents.policies import PolicyFactory
from glee_eval.population.opponent_fit import ARCHETYPE_BANDS, OpponentPopulation, fit_opponent_population
from glee_eval.population.sampler import ARCHETYPES, sample_opponent_spec
from glee_eval.storage.trajectories import write_json, write_jsonl


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
