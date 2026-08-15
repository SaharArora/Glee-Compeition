from __future__ import annotations

import unittest

from glee_eval.experiments.ab import config_regime
from glee_eval.experiments.promotion import (
    Observation,
    PromotionCriteria,
    evaluate_construction_defect,
    evaluate_promotion,
    verdict_markdown,
)
from glee_eval.population.splits import FIT, HOLDOUT, is_holdout_key, keeps, partition_of


def _observations(
    n: int = 400,
    effect: float = 0.05,
    *,
    archetypes: int = 8,
    regimes: int = 4,
    concentrate_in: str | None = None,
    negative_fraction: float = 0.0,
    baseline_value: float = 0.4,
    tail_penalty: float = 0.0,
) -> list[Observation]:
    """Synthetic paired outcomes with controllable subgroup structure."""

    rows = []
    for i in range(n):
        archetype = f"arch_{i % archetypes}"
        regime = f"regime_{i % regimes}"
        if concentrate_in is not None:
            delta = effect * archetypes if archetype == concentrate_in else 0.0
        elif negative_fraction and (i % archetypes) < round(negative_fraction * archetypes):
            delta = -effect
        else:
            delta = effect
        # A little deterministic spread so the t statistic is finite.
        delta += 0.001 * ((i % 7) - 3)
        baseline = baseline_value
        candidate = baseline + delta
        # 12.5% penalised, comfortably inside the 5th percentile rather than
        # sitting exactly on its nearest-rank boundary.
        if tail_penalty and i % 8 == 0:
            candidate -= tail_penalty
        rows.append(
            Observation(
                key=str(i),
                baseline=baseline,
                candidate=candidate,
                subgroups={"opponent_archetype": archetype, "config_regime": regime},
            )
        )
    return rows


def _verdict(rows, **kwargs):
    kwargs.setdefault("evaluated_on_holdout", True)
    return evaluate_promotion(rows, **kwargs)


class PromotionGateTests(unittest.TestCase):
    def test_a_broad_significant_improvement_is_promoted(self) -> None:
        verdict = _verdict(_observations())

        self.assertTrue(verdict["promoted"], verdict["failed_checks"])
        self.assertGreater(verdict["summary"]["mean_effect"], 0.04)

    def test_an_effect_below_the_minimum_is_rejected(self) -> None:
        verdict = _verdict(_observations(effect=0.002))

        self.assertFalse(verdict["promoted"])
        self.assertIn("minimum_effect", verdict["failed_checks"])

    def test_too_few_paired_episodes_is_rejected(self) -> None:
        verdict = _verdict(_observations(n=50))

        self.assertFalse(verdict["promoted"])
        self.assertIn("sample_size", verdict["failed_checks"])

    def test_a_gain_concentrated_in_one_opponent_is_rejected(self) -> None:
        """The headline number can be fine while the change helps only one subgroup."""

        rows = _observations(concentrate_in="arch_0")
        verdict = _verdict(rows)

        self.assertGreater(verdict["summary"]["mean_effect"], 0.04, "headline effect should still look good")
        self.assertFalse(verdict["promoted"])
        self.assertIn("subgroup_concentration[opponent_archetype]", verdict["failed_checks"])

    def test_a_change_that_regresses_most_subgroups_is_rejected(self) -> None:
        verdict = _verdict(_observations(effect=0.08, negative_fraction=0.5))

        self.assertIn("subgroup_breadth[opponent_archetype]", verdict["failed_checks"])

    def test_a_worse_bad_tail_is_rejected(self) -> None:
        verdict = _verdict(_observations(tail_penalty=0.5))

        self.assertFalse(verdict["promoted"])
        self.assertIn("downside_p5", verdict["failed_checks"])
        self.assertLess(verdict["summary"]["candidate_p5"], verdict["summary"]["baseline_p5"])

    def test_evaluating_on_the_fitting_slice_is_rejected(self) -> None:
        verdict = evaluate_promotion(_observations(), evaluated_on_holdout=False)

        self.assertFalse(verdict["promoted"])
        self.assertIn("structural_holdout", verdict["failed_checks"])

    def test_the_holdout_requirement_can_be_waived_only_explicitly(self) -> None:
        criteria = PromotionCriteria(require_holdout=False)
        verdict = evaluate_promotion(_observations(), criteria=criteria, evaluated_on_holdout=False)

        self.assertTrue(verdict["promoted"], verdict["failed_checks"])

    def test_too_few_subgroups_to_judge_concentration_is_rejected(self) -> None:
        verdict = _verdict(_observations(archetypes=2, regimes=1))

        self.assertIn("subgroup_coverage[config_regime]", verdict["failed_checks"])

    def test_a_regression_is_rejected_on_effect_and_significance(self) -> None:
        verdict = _verdict(_observations(effect=-0.05))

        self.assertFalse(verdict["promoted"])
        self.assertIn("minimum_effect", verdict["failed_checks"])
        self.assertIn("significance", verdict["failed_checks"])

    def test_verdict_markdown_renders_without_error(self) -> None:
        text = verdict_markdown(_verdict(_observations(), change="test change"))

        self.assertIn("test change", text)
        self.assertIn("PROMOTE", text)
        self.assertIn("subgroup_concentration", text)

    def test_every_check_reports_observed_and_threshold(self) -> None:
        for check in _verdict(_observations())["checks"]:
            self.assertIn("observed", check)
            self.assertIn("threshold", check)
            self.assertTrue(check["detail"])

    def test_construction_defect_replaces_only_minimum_effect(self) -> None:
        rows = _observations(n=400, effect=0.005)
        for index, row in enumerate(rows):
            row.branch_predicates["proved_branch"] = index < 80
            if index < 80:
                row.candidate = row.baseline + 0.025 + 0.001 * ((index % 5) - 2)

        verdict = evaluate_construction_defect(
            rows,
            predicate_name="proved_branch",
            change="proved construction defect",
            evaluated_on_holdout=True,
        )

        self.assertEqual(verdict["ordinary"]["failed_checks"], ["minimum_effect"])
        self.assertTrue(verdict["gate_passed"], verdict["conditional_checks"])

    def test_construction_defect_rejects_one_conditional_loss(self) -> None:
        rows = _observations(n=400, effect=0.005)
        for index, row in enumerate(rows):
            row.branch_predicates["proved_branch"] = index < 80
            if index < 80:
                row.candidate = row.baseline + 0.025
        rows[0].candidate = rows[0].baseline - 0.001

        verdict = evaluate_construction_defect(
            rows,
            predicate_name="proved_branch",
            change="one-loss candidate",
            evaluated_on_holdout=True,
        )

        loss_check = next(check for check in verdict["conditional_checks"] if check["name"] == "conditional_losses")
        self.assertFalse(loss_check["passed"])
        self.assertFalse(verdict["gate_passed"])

    def test_non_effect_ordinary_failure_cannot_be_replaced(self) -> None:
        rows = _observations(n=400, effect=0.005, negative_fraction=0.5)
        for row in rows:
            row.branch_predicates["proved_branch"] = True

        verdict = evaluate_construction_defect(
            rows,
            predicate_name="proved_branch",
            change="ineligible candidate",
            evaluated_on_holdout=True,
        )

        self.assertFalse(verdict["ordinary_eligible"])
        self.assertFalse(verdict["gate_passed"])


class SplitTests(unittest.TestCase):
    def test_assignment_is_deterministic(self) -> None:
        game = {"player_1_model": "gpt-4o", "player_2_model": "otree", "config_id": "abc"}

        self.assertEqual(partition_of(game, "model"), partition_of(game, "model"))
        self.assertEqual(is_holdout_key("gpt-4o"), is_holdout_key("gpt-4o"))

    def test_none_mode_keeps_everything(self) -> None:
        game = {"player_1_model": "gpt-4o", "config_id": "abc"}

        self.assertEqual(partition_of(game, "none"), FIT)
        self.assertTrue(keeps(game, mode="none", split=HOLDOUT))

    def test_a_game_touching_a_holdout_model_is_held_out(self) -> None:
        """Requiring both players would leak holdout behavior into the fit slice."""

        holdout_model = next(m for m in ("gpt-4o-mini", "otree", "otree_LLM") if is_holdout_key(m))
        fit_model = next(m for m in ("gpt-4o", "o3-mini", "xai/grok-2-1212") if not is_holdout_key(m))

        mixed = {"player_1_model": fit_model, "player_2_model": holdout_model}
        pure_fit = {"player_1_model": fit_model, "player_2_model": fit_model}

        self.assertEqual(partition_of(mixed, "model"), HOLDOUT)
        self.assertEqual(partition_of(pure_fit, "model"), FIT)

    def test_config_mode_partitions_on_the_configuration(self) -> None:
        keys = [f"cfg-{i}" for i in range(400)]
        held = [key for key in keys if partition_of({"config_id": key}, "config") == HOLDOUT]

        self.assertGreater(len(held), 40)
        self.assertLess(len(held), 160)

    def test_a_record_without_models_stays_in_fit(self) -> None:
        self.assertEqual(partition_of({}, "model"), FIT)

    def test_unknown_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            partition_of({"config_id": "a"}, "nonsense")

    def test_keeps_filters_to_the_requested_split(self) -> None:
        holdout_model = next(m for m in ("gpt-4o-mini", "otree") if is_holdout_key(m))
        game = {"player_1_model": holdout_model, "player_2_model": holdout_model}

        self.assertTrue(keeps(game, mode="model", split=HOLDOUT))
        self.assertFalse(keeps(game, mode="model", split=FIT))


class ConfigRegimeTests(unittest.TestCase):
    def test_negotiation_regime_separates_trade_zones(self) -> None:
        gains = config_regime("negotiation", {"seller_value": 0.8, "buyer_value": 1.2, "max_rounds": 10})
        none = config_regime("negotiation", {"seller_value": 1.5, "buyer_value": 0.8, "max_rounds": 10})

        self.assertIn("gains_from_trade", gains)
        self.assertIn("no_trade_zone", none)
        self.assertNotEqual(gains, none)

    def test_bargaining_regime_separates_who_is_patient(self) -> None:
        symmetric = config_regime("bargaining", {"delta_1": 0.9, "delta_2": 0.9, "max_rounds": 12})
        p1 = config_regime("bargaining", {"delta_1": 1.0, "delta_2": 0.8, "max_rounds": 12})
        p2 = config_regime("bargaining", {"delta_1": 0.8, "delta_2": 1.0, "max_rounds": 12})

        self.assertEqual(len({symmetric, p1, p2}), 3)

    def test_missing_values_do_not_raise(self) -> None:
        self.assertIn("unknown", config_regime("negotiation", {}))
        self.assertIn("unknown", config_regime("bargaining", {}))
        self.assertEqual(config_regime("chess", {}), "unknown")


if __name__ == "__main__":
    unittest.main()
