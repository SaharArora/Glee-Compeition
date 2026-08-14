from __future__ import annotations

import unittest

from glee_eval.contracts import (
    INGESTED_EVENT,
    LIVE_PERSUASION,
    TRANSCRIPT_DECISION_ROW,
    TRANSCRIPT_MESSAGE_ROW,
    TRANSCRIPT_QUALITY_ROW,
    Contract,
    ContractReport,
    Field,
    Mode,
    Problem,
    SchemaViolation,
    check,
    enforce,
    live_contract,
)


def _problems(violations) -> set[str]:
    return {v.problem.value for v in violations}


class HistoricalBugRegressionTests(unittest.TestCase):
    """The two shape bugs that actually happened, encoded as tests.

    Both produced confidently-wrong behaviour with nothing raising anywhere. If a
    future refactor reintroduces either, these fail.
    """

    def test_the_persuasion_quality_bug_is_caught(self) -> None:
        """Reader that only knows `quality` cannot read a real `raw.round_quality` row."""

        real_row = {
            "action_type": "nature_quality",
            "round": 1,
            "raw": {"round_quality": "high-quality", "decision": None},
        }
        broken = Contract(
            "broken.quality",
            (Field("quality", aliases=("round_quality",), reader=lambda row: row.get("quality")),),
        )

        violations = check(real_row, broken)

        self.assertIn(Problem.UNREADABLE.value, _problems(violations))
        self.assertIn("raw.round_quality", violations[0].detail)

    def test_the_shipped_reader_handles_the_same_row(self) -> None:
        real_row = {
            "action_type": "nature_quality",
            "round": 1,
            "raw": {"round_quality": "high-quality", "decision": None},
        }

        self.assertEqual(check(real_row, TRANSCRIPT_QUALITY_ROW), [])

    def test_the_shipped_reader_handles_a_synthetic_row_too(self) -> None:
        synthetic = {"action_type": "nature_quality", "round": 1, "quality": "low-quality"}

        self.assertEqual(check(synthetic, TRANSCRIPT_QUALITY_ROW), [])

    def test_the_live_low_value_rename_is_caught(self) -> None:
        """`u` is the live name for our `c`; reading only `c` sees nothing."""

        live_state = {
            "game_id": "g",
            "game_family": "persuasion",
            "valid_actions": {"type": "buyer_decision"},
            "game_state": {"product_price": 10000, "p": 0.5, "round": 1, "total_rounds": 20, "u": 0, "v": 12500},
        }
        reading_only_c = Contract(
            "broken.low_value",
            (Field("c", aliases=("u",), reader=lambda payload: (payload.get("game_state") or {}).get("c")),),
        )

        self.assertIn(Problem.UNREADABLE.value, _problems(check(live_state, reading_only_c)))
        # And the real contract is satisfied by the same payload.
        self.assertEqual(check(live_state, LIVE_PERSUASION), [])


class ReaderSemanticsTests(unittest.TestCase):
    def test_a_present_but_null_key_is_not_the_fact_being_present(self) -> None:
        """Real rows carry every column, so a text-mode message has decision=null."""

        message_row = {
            "action_type": "message",
            "round": 2,
            "raw": {"decision": None, "message": "Hello, I have a product."},
        }

        self.assertEqual(check(message_row, TRANSCRIPT_MESSAGE_ROW), [])

    def test_a_genuinely_absent_fact_reports_missing_not_unreadable(self) -> None:
        row = {"action_type": "buy_decision", "round": 1, "raw": {}}

        violations = check(row, TRANSCRIPT_DECISION_ROW)

        self.assertIn(Problem.MISSING.value, _problems(violations))
        self.assertNotIn(Problem.UNREADABLE.value, _problems(violations))

    def test_a_reader_that_raises_is_itself_a_violation(self) -> None:
        def exploding(row):
            raise KeyError("nope")

        contract = Contract("boom", (Field("x", reader=exploding),))

        violations = check({"x": 1}, contract)

        self.assertIn(Problem.UNREADABLE.value, _problems(violations))
        self.assertIn("KeyError", violations[0].detail)

    def test_shadowing_is_reported_when_no_reader_is_declared(self) -> None:
        contract = Contract("no_reader", (Field("quality", aliases=("round_quality",)),))

        violations = check({"raw": {"round_quality": "high-quality"}}, contract)

        self.assertIn(Problem.SHADOWED_BY_ALIAS.value, _problems(violations))

    def test_wrong_types_are_reported(self) -> None:
        contract = Contract("typed", (Field("round", kind=(int, float)),))

        self.assertIn(Problem.WRONG_TYPE.value, _problems(check({"round": "two"}, contract)))

    def test_a_non_mapping_payload_is_reported_rather_than_crashing(self) -> None:
        for payload in (None, [], "", 0, {}):
            self.assertIn(Problem.EMPTY_PAYLOAD.value, _problems(check(payload, INGESTED_EVENT)))


class EnforcementModeTests(unittest.TestCase):
    """The mode differs by boundary because the cost of raising differs."""

    def test_strict_raises_with_every_violation_named(self) -> None:
        with self.assertRaises(SchemaViolation) as caught:
            enforce({}, INGESTED_EVENT, mode=Mode.STRICT, context="g-1")

        self.assertIn("ingest.event", str(caught.exception))
        self.assertIn("g-1", str(caught.exception))

    def test_observe_never_raises_and_records(self) -> None:
        report = ContractReport()

        violations = enforce({}, INGESTED_EVENT, mode=Mode.OBSERVE, report=report)

        self.assertTrue(violations)
        self.assertFalse(report.clean)
        self.assertTrue(report.to_dict()["violation_counts"])

    def test_off_does_nothing(self) -> None:
        self.assertEqual(enforce({}, INGESTED_EVENT, mode=Mode.OFF), [])

    def test_a_clean_payload_produces_no_violations_in_any_mode(self) -> None:
        event = {
            "game_id": "g",
            "game_family": "persuasion",
            "role": "buyer",
            "round": 1,
            "action_type": "buy_decision",
            "configuration": {"p": 0.5},
        }
        for mode in (Mode.STRICT, Mode.OBSERVE, Mode.OFF):
            self.assertEqual(enforce(event, INGESTED_EVENT, mode=mode), [])

    def test_report_caps_its_samples_but_not_its_counts(self) -> None:
        report = ContractReport(max_samples=3)
        for _ in range(50):
            enforce({}, INGESTED_EVENT, mode=Mode.OBSERVE, report=report)

        payload = report.to_dict()
        self.assertEqual(len(payload["samples"]), 3)
        self.assertEqual(sum(payload["violation_counts"].values()), 50)


class LiveBoundaryTests(unittest.TestCase):
    def test_every_family_has_a_contract(self) -> None:
        for family in ("bargaining", "negotiation", "persuasion"):
            self.assertIsNotNone(live_contract(family))
        self.assertIsNone(live_contract("chess"))

    def test_the_live_fixtures_satisfy_their_contracts(self) -> None:
        from glee_eval.live import fixtures

        for game in fixtures.sample_games():
            contract = live_contract(game["game_family"])
            self.assertEqual(check(game, contract), [], f"{game['game_id']} violated {contract.name}")

    def test_a_live_strategy_records_violations_without_raising(self) -> None:
        """Raising on the live path would be swallowed by the SDK and cost the game."""

        from glee_eval.live import fixtures
        from glee_eval.live.strategy import LiveStrategy
        from my_agents.jordan_strategic import MyAgent

        game = fixtures.persuasion_buyer_decision()
        del game["game_state"]["p"]  # a field the contract requires

        strategy = LiveStrategy(MyAgent(seed=1), observation_log=None)
        action = strategy(game)

        self.assertIsInstance(action, dict)
        self.assertTrue(action)
        self.assertFalse(strategy.contract_report.clean)
        self.assertIn("schema", strategy.summary())


if __name__ == "__main__":
    unittest.main()
