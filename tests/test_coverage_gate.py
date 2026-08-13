from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from glee_eval.data.dataset_audit import build_support_index, context_support_lookup
from glee_eval.population.sampler import sample_scenario
from glee_eval.simulate.coverage_gate import CoverageGate
from glee_eval.simulate.dispatch import TargetedSimulationDispatcher
from glee_eval.storage.trajectories import read_jsonl, write_json
from glee_eval.tournament.runner import run_episode
from my_agents.jordan_strategic import MyAgent


BARGAINING_CONFIG = {
    "money_to_divide": 100,
    "max_rounds": 6,
    "complete_information": True,
    "messages_allowed": True,
    "delta_1": 1.0,
    "delta_2": 1.0,
}


def _bargaining_events(share: float, count: int) -> list[dict]:
    """`count` observed player_2 offers, all at the same share of the pot."""

    return [
        {
            "game_family": "bargaining",
            "role": "player_2",
            "configuration": BARGAINING_CONFIG,
            "action_type": "offer",
            "numeric_action": share * 100.0,
            "round": 1,
        }
        for _ in range(count)
    ]


def _offer_action(self_gain: float) -> dict:
    return {
        "action_type": "offer",
        "numeric_action": self_gain,
        "structured": {"self_gain": self_gain, "other_gain": 100.0 - self_gain},
    }


class _RecordingDispatcher:
    """Stands in for the real dispatcher so the gate's own logic is isolated."""

    def __init__(self, available: bool = True):
        self.calls: list[dict] = []
        self.available = available

    def counterfactual_available(self) -> bool:
        return self.available

    def counterfactual_simulation(self, **kwargs):
        self.calls.append(kwargs)
        return {"skipped": False, "output_dir": f"out/{len(self.calls)}", "episodes": []}


class ContextSupportLookupTests(unittest.TestCase):
    def test_context_score_rises_with_observations_and_spread(self) -> None:
        state = SimpleNamespace(round=1, horizon=6)
        thin = build_support_index(_bargaining_events(0.55, 5))
        thick = build_support_index(
            _bargaining_events(0.45, 120) + _bargaining_events(0.55, 120) + _bargaining_events(0.65, 120)
        )

        thin_result = context_support_lookup("bargaining", BARGAINING_CONFIG, "player_2", "offer", state, support_index=thin)
        thick_result = context_support_lookup("bargaining", BARGAINING_CONFIG, "player_2", "offer", state, support_index=thick)

        self.assertTrue(thin_result["found"])
        self.assertTrue(thick_result["found"])
        self.assertLess(thin_result["context_score"], thick_result["context_score"])

    def test_missing_context_is_reported_as_not_found(self) -> None:
        result = context_support_lookup(
            "bargaining",
            BARGAINING_CONFIG,
            "player_2",
            "offer",
            SimpleNamespace(round=1, horizon=6),
            support_index={"buckets": {}},
        )
        self.assertFalse(result["found"])
        self.assertEqual(result["context_score"], 0.0)

    def test_context_and_action_lookups_resolve_the_same_bucket(self) -> None:
        index = build_support_index(_bargaining_events(0.55, 80))
        state = SimpleNamespace(round=1, horizon=6)
        from glee_eval.data.dataset_audit import support_lookup

        context = context_support_lookup("bargaining", BARGAINING_CONFIG, "player_2", "offer", state, support_index=index)
        action = support_lookup("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(55.0), state, support_index=index)

        self.assertEqual(context["bucket_key"], action["bucket_key"])
        self.assertEqual(context["bucket_level"], action["bucket_level"])


class CoverageGateTests(unittest.TestCase):
    def setUp(self) -> None:
        # 80 observations, all in the 0.55-0.60 share bin: that bin is well
        # covered, every other bin in the same context is not.
        self.index = build_support_index(_bargaining_events(0.57, 80))
        self.state = SimpleNamespace(round=1, horizon=6)

    def _gate(self, dispatcher=None, **kwargs) -> CoverageGate:
        return CoverageGate(self.index, dispatcher=dispatcher, **kwargs)

    def test_action_inside_support_does_not_dispatch(self) -> None:
        dispatcher = _RecordingDispatcher()
        gate = self._gate(dispatcher)

        request = gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(57.0), self.state)

        self.assertEqual(request["status"], "inside_support")
        self.assertTrue(request["coverage"]["inside_support"])
        self.assertEqual(dispatcher.calls, [])

    def test_action_outside_support_dispatches_counterfactual(self) -> None:
        dispatcher = _RecordingDispatcher()
        gate = self._gate(dispatcher)

        request = gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(95.0), self.state)

        self.assertEqual(request["status"], "dispatched")
        self.assertFalse(request["coverage"]["inside_support"])
        self.assertEqual(len(dispatcher.calls), 1)
        self.assertEqual(dispatcher.calls[0]["family"], "bargaining")

    def test_repeat_bucket_is_deduplicated(self) -> None:
        dispatcher = _RecordingDispatcher()
        gate = self._gate(dispatcher)

        first = gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(95.0), self.state)
        second = gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(96.0), self.state)

        self.assertEqual(first["status"], "dispatched")
        self.assertEqual(second["status"], "duplicate_bucket")
        self.assertEqual(len(dispatcher.calls), 1)

    def test_budget_is_capped_and_the_drop_is_recorded(self) -> None:
        dispatcher = _RecordingDispatcher()
        gate = self._gate(dispatcher, max_dispatches=1)

        gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(95.0), self.state)
        dropped = gate.request_counterfactual("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(10.0), self.state)

        self.assertEqual(dropped["status"], "budget_exhausted")
        self.assertEqual(len(dispatcher.calls), 1)
        self.assertEqual(gate.summary()["request_status_counts"]["budget_exhausted"], 1)

    def test_no_index_treats_every_action_as_inside_support(self) -> None:
        gate = CoverageGate({"buckets": {}}, dispatcher=_RecordingDispatcher())

        verdict = gate.evaluate("bargaining", BARGAINING_CONFIG, "player_2", _offer_action(95.0), self.state)

        self.assertFalse(gate.has_index)
        self.assertFalse(verdict.known)
        self.assertTrue(verdict.inside_support)

    def test_from_path_loads_a_measurement_only_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_dir = Path(tmp)
            write_json(audit_dir / "support_index.json", self.index)

            gate = CoverageGate.from_path(audit_dir)

            self.assertIsNotNone(gate)
            self.assertTrue(gate.has_index)
            self.assertIsNone(gate.dispatcher)
            status = gate.request_counterfactual(
                "bargaining", BARGAINING_CONFIG, "player_2", _offer_action(95.0), self.state
            )["status"]
            self.assertEqual(status, "no_dispatcher")

    def test_from_path_returns_none_when_absent(self) -> None:
        self.assertIsNone(CoverageGate.from_path(None))
        self.assertIsNone(CoverageGate.from_path("/nonexistent/support_index.json"))


class DispatcherCounterfactualTests(unittest.TestCase):
    def _dispatcher(self, tmp: Path, index: dict, **kwargs) -> TargetedSimulationDispatcher:
        return TargetedSimulationDispatcher(
            agent_spec="heuristic",
            support_index=index,
            audit_report={},
            seed=5,
            ledger_path=tmp / "simulation_ledger.jsonl",
            counterfactual_games=2,
            **kwargs,
        )

    def test_out_of_support_action_runs_and_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatcher = self._dispatcher(root, build_support_index(_bargaining_events(0.57, 80)))

            result = dispatcher.counterfactual_simulation(
                family="bargaining",
                config=BARGAINING_CONFIG,
                role="player_2",
                action=_offer_action(95.0),
                state=SimpleNamespace(round=1, horizon=6),
                games=2,
                output_dir=root / "counterfactual",
            )

            self.assertFalse(result["skipped"])
            self.assertEqual(len(result["episodes"]), 2)
            self.assertEqual(result["episodes"][0].scenario.metadata["simulation"]["trigger"], "counterfactual")
            entries = read_jsonl(root / "simulation_ledger.jsonl")
            self.assertEqual([entry["status"] for entry in entries], ["ran"])
            self.assertEqual(entries[0]["trigger"], "counterfactual")

    def test_in_support_action_is_skipped_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatcher = self._dispatcher(root, build_support_index(_bargaining_events(0.57, 80)))

            result = dispatcher.counterfactual_simulation(
                family="bargaining",
                config=BARGAINING_CONFIG,
                role="player_2",
                action=_offer_action(57.0),
                state=SimpleNamespace(round=1, horizon=6),
                games=2,
                output_dir=root / "counterfactual",
            )

            self.assertTrue(result["skipped"])
            self.assertEqual(result["episodes"], [])
            entries = read_jsonl(root / "simulation_ledger.jsonl")
            self.assertEqual([entry["status"] for entry in entries], ["skipped"])
            self.assertIn("inside empirical support", entries[0]["reason"])

    def test_reentrant_request_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatcher = self._dispatcher(root, build_support_index(_bargaining_events(0.57, 80)))
            dispatcher._counterfactual_active = True

            self.assertFalse(dispatcher.counterfactual_available())
            result = dispatcher.counterfactual_simulation(
                family="bargaining",
                config=BARGAINING_CONFIG,
                role="player_2",
                action=_offer_action(95.0),
                state=SimpleNamespace(round=1, horizon=6),
                games=2,
                output_dir=root / "counterfactual",
            )

            self.assertTrue(result["skipped"])
            self.assertIn("Already inside", read_jsonl(root / "simulation_ledger.jsonl")[0]["reason"])

    def test_build_agent_attaches_the_shared_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dispatcher = TargetedSimulationDispatcher(
                agent_spec="my_agents.jordan_strategic:MyAgent",
                support_index=build_support_index(_bargaining_events(0.57, 80)),
                audit_report={},
                seed=5,
                ledger_path=root / "simulation_ledger.jsonl",
            )

            agent = dispatcher.build_agent()

            self.assertIs(agent.coverage_gate, dispatcher.coverage_gate)
            self.assertIs(agent.coverage_gate.dispatcher, dispatcher)


class AgentCoverageWiringTests(unittest.TestCase):
    """The agent end of Gap 1: a committed action must reach the gate."""

    def test_agent_tags_actions_with_support_and_requests_simulation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # The index knows only about a narrow slice of bargaining offers, so
            # most of what the agent plays is genuinely outside support.
            dispatcher = TargetedSimulationDispatcher(
                agent_spec="my_agents.jordan_strategic:MyAgent",
                support_index=build_support_index(_bargaining_events(0.57, 80)),
                audit_report={},
                seed=5,
                ledger_path=root / "simulation_ledger.jsonl",
                max_counterfactual_dispatches=1,
                counterfactual_games=2,
            )
            agent = dispatcher.build_agent()

            episode = run_episode(sample_scenario("bargaining", seed=11, candidate_role="player_2"), agent)

            candidate_actions = [
                record.action for record in episode.decision_records if record.role == episode.scenario.candidate_role
            ]
            self.assertTrue(candidate_actions)
            tagged = [action for action in candidate_actions if "action_support" in action["structured"]]
            self.assertTrue(tagged, "committed actions should carry an action_support reading")

            summary = dispatcher.coverage_gate.summary()
            self.assertTrue(summary["has_index"])
            self.assertGreater(summary["decisions_evaluated"], 0)
            statuses = summary["request_status_counts"]
            self.assertTrue(statuses, "an out-of-support decision should have produced a request")
            self.assertLessEqual(summary["dispatches_used"], 1)
            # Whatever the gate did, the counterfactual trigger must have been
            # reached through the ledger rather than bypassed.
            triggers = {entry["trigger"] for entry in read_jsonl(root / "simulation_ledger.jsonl")}
            self.assertIn("counterfactual", triggers)

    def test_agent_without_support_index_is_unchanged(self) -> None:
        agent = MyAgent(seed=5)
        agent.coverage_gate = None

        episode = run_episode(sample_scenario("bargaining", seed=11, candidate_role="player_2"), agent)

        candidate_actions = [
            record.action for record in episode.decision_records if record.role == episode.scenario.candidate_role
        ]
        self.assertTrue(candidate_actions)
        for action in candidate_actions:
            self.assertNotIn("action_support", action["structured"])

    def test_thin_coverage_blocks_exploit_escalation(self) -> None:
        """Gap 2: the audit support index, not just the response model, gates EXPLOIT."""

        agent = MyAgent(seed=5)
        state = SimpleNamespace(round=1, horizon=6)
        evidence = {"E_sample": 2.0}

        unknown = agent._counterfactual_uncertainty(state, {}, evidence, {"known": False})
        covered = agent._counterfactual_uncertainty(state, {}, evidence, {"known": True, "context_score": 1.0})
        thin = agent._counterfactual_uncertainty(state, {}, evidence, {"known": True, "context_score": 0.0})

        self.assertEqual(unknown, covered)
        self.assertGreater(thin, covered)
        self.assertLessEqual(covered, agent.max_counterfactual_uncertainty)
        self.assertGreater(thin, agent.max_counterfactual_uncertainty)


if __name__ == "__main__":
    unittest.main()
