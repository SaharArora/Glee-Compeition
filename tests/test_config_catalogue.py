from __future__ import annotations

import collections
import random
import tempfile
import unittest
from pathlib import Path

from glee_eval.population.config_catalogue import ConfigCatalogue, build_config_catalogue
from glee_eval.population.sampler import sample_scenario
from glee_eval.storage.trajectories import write_json, write_jsonl


def _game(family: str, args: dict, game_id: str = "g") -> dict:
    return {
        "game_id": game_id,
        "game_family": family,
        "configuration": {"game_type": family, "game_args": args},
    }


NEGOTIATION_A = {
    "seller_value": 0.8,
    "buyer_value": 1.2,
    "product_price_order": 1_000_000,
    "max_rounds": 10,
    "complete_information": True,
    "messages_allowed": False,
}
NEGOTIATION_B = {**NEGOTIATION_A, "seller_value": 1.5, "buyer_value": 0.8}


class BuildCatalogueTests(unittest.TestCase):
    def test_counts_distinct_configs_and_weights_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            games = [_game("negotiation", NEGOTIATION_A, f"a{i}") for i in range(7)]
            games += [_game("negotiation", NEGOTIATION_B, f"b{i}") for i in range(3)]
            write_jsonl(root / "processed" / "games.jsonl", games)

            payload = build_config_catalogue(root, root / "out")

            block = payload["families"]["negotiation"]
            self.assertEqual(block["distinct_configs"], 2)
            self.assertEqual(block["games"], 10)
            self.assertEqual([entry["count"] for entry in block["entries"]], [7, 3])
            self.assertEqual(payload["games_skipped"], 0)

    def test_omitted_optional_fields_use_upstream_defaults_not_a_skip(self) -> None:
        """13,021 of 13,506 real persuasion configs omit two flags; skipping loses the family."""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = {"p": 0.5, "v": 1.2, "c": 0.0, "product_price": 100, "total_rounds": 20, "is_seller_know_cv": True}
            write_jsonl(root / "processed" / "games.jsonl", [_game("persuasion", args)])

            payload = build_config_catalogue(root, root / "out")

            self.assertEqual(payload["games_skipped"], 0)
            config = payload["families"]["persuasion"]["entries"][0]["config"]
            self.assertTrue(config["is_buyer_know_p"])
            self.assertFalse(config["allow_buyer_message"])
            self.assertEqual(config["seller_message_type"], "text")

    def test_a_config_missing_a_required_field_is_skipped_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken = {k: v for k, v in NEGOTIATION_A.items() if k != "seller_value"}
            write_jsonl(root / "processed" / "games.jsonl", [_game("negotiation", broken)])

            payload = build_config_catalogue(root, root / "out")

            self.assertEqual(payload["games_skipped"], 1)
            self.assertEqual(payload["families"]["negotiation"]["distinct_configs"], 0)

    def test_missing_games_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                build_config_catalogue(tmp, Path(tmp) / "out")


class CatalogueSamplingTests(unittest.TestCase):
    def _catalogue(self) -> ConfigCatalogue:
        return ConfigCatalogue(
            {
                "families": {
                    "negotiation": {
                        "entries": [
                            {"config": NEGOTIATION_A, "count": 90},
                            {"config": NEGOTIATION_B, "count": 10},
                        ]
                    }
                }
            }
        )

    def test_sampling_respects_observed_frequency(self) -> None:
        catalogue = self._catalogue()
        rng = random.Random(0)
        counts: collections.Counter = collections.Counter()
        for _ in range(3000):
            config = catalogue.sample("negotiation", rng)
            counts["no_trade" if config["buyer_value"] <= config["seller_value"] else "gains"] += 1

        self.assertAlmostEqual(counts["no_trade"] / 3000, 0.10, delta=0.03)

    def test_joint_structure_is_preserved(self) -> None:
        """Marginal sampling could produce value pairs that never co-occur."""

        catalogue = self._catalogue()
        rng = random.Random(1)
        allowed = {(0.8, 1.2), (1.5, 0.8)}
        for _ in range(500):
            config = catalogue.sample("negotiation", rng)
            self.assertIn((config["seller_value"], config["buyer_value"]), allowed)

    def test_unfitted_family_returns_none(self) -> None:
        self.assertIsNone(self._catalogue().sample("bargaining", random.Random(0)))
        self.assertFalse(self._catalogue().has("bargaining"))

    def test_load_from_directory_file_and_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"families": {"negotiation": {"entries": [{"config": NEGOTIATION_A, "count": 1}]}}}
            write_json(Path(tmp) / "config_catalogue.json", payload)
            self.assertIsNotNone(ConfigCatalogue.load(tmp))
        self.assertIsNone(ConfigCatalogue.load(None))
        self.assertIsNone(ConfigCatalogue.load("/nonexistent/config_catalogue.json"))

    def test_empty_catalogue_loads_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp) / "config_catalogue.json", {"families": {}})
            self.assertIsNone(ConfigCatalogue.load(tmp))


class SamplerProvenanceTests(unittest.TestCase):
    def test_scenario_records_whether_the_config_was_real(self) -> None:
        catalogue = ConfigCatalogue(
            {"families": {"negotiation": {"entries": [{"config": NEGOTIATION_B, "count": 1}]}}}
        )

        real = sample_scenario("negotiation", seed=1, catalogue=catalogue)
        self.assertEqual(real.metadata["config_source"], "observed_real_config")
        self.assertEqual(real.public_parameters["seller_value"], 1.5)
        self.assertEqual(real.public_parameters["max_rounds"], 10)

    def test_falling_back_to_invented_configs_is_labelled(self) -> None:
        empty = ConfigCatalogue({"families": {"negotiation": {"entries": [{"config": NEGOTIATION_B, "count": 1}]}}})

        invented = sample_scenario("bargaining", seed=1, catalogue=empty)

        self.assertEqual(invented.metadata["config_source"], "invented_default_config")
        self.assertEqual(invented.public_parameters["max_rounds"], 6)

    def test_real_configs_produce_no_trade_zones_the_old_sampler_could_not(self) -> None:
        catalogue = ConfigCatalogue(
            {"families": {"negotiation": {"entries": [{"config": NEGOTIATION_B, "count": 1}]}}}
        )

        scenario = sample_scenario("negotiation", seed=3, catalogue=catalogue)
        config = scenario.public_parameters

        self.assertLessEqual(config["buyer_value"], config["seller_value"])


if __name__ == "__main__":
    unittest.main()
