"""Offline-only Wave 5D competition-preparation evidence checks.

This module deliberately reads only the already-exposed Wave 5B paired-output
ledger.  It never opens the underlying opponent/configuration/model artifacts
and cannot launch a simulation, provider request, or live game.  Once inspected
in Wave 5B, those 900 outcomes may inform mechanism generation but cannot serve
as untouched confirmation for a new policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable


EXPOSED_OBSERVATIONS = Path(
    "research/EVIDENCE/WAVE5B_SHARED_BACKBONE/observations.jsonl"
)
EXPOSED_OBSERVATIONS_SHA256 = (
    "66ffc4c3ebfdf80fec9cad677c92f5151074088c643e5fd75f9e350861959211"
)
EXPOSED_SUMMARY = Path("research/EVIDENCE/WAVE5B_SHARED_BACKBONE/summary.json")
EXPOSED_SUMMARY_SHA256 = (
    "1031dd237f7092b7ac8be00ccaf079166595827d74a5d9d64645835df9253936"
)

SOURCE_PINS = {
    "my_agents/jordan_strategic.py": (
        "27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82"
    ),
    "research/CANDIDATES/r1_treatment_off_baseline.py": (
        "5e6e5daebef9df16c06ce2c4bdc3a3378b30241a4b23b08310f9447c051998a9"
    ),
    "research/CANDIDATES/wave3_factorial_agents.py": (
        "f5b34b42c759391a0f68d188ce71e51cbc43a33e128dd73fcecbfebd8e6a8265"
    ),
}


BEHAVIOR_TRACE = (
    {
        "family": "bargaining",
        "roles": ["player_1", "player_2"],
        "decision_point": "offer",
        "shared_surface": (
            "beliefs, SPE/fairness anchor, optional Model-C offer search, and legal action"
        ),
        "jordan": (
            "heuristic evidence may select EXPLORE or EXPLOIT and thereby change the "
            "offer branch and Model-C search cap"
        ),
        "factorial00": "empty evidence and forced SAFE control",
        "payoff_relevant": True,
    },
    {
        "family": "bargaining",
        "roles": ["player_1", "player_2"],
        "decision_point": "accept_or_reject",
        "shared_surface": "continuation-value accept floor and final-round positive-payoff rule",
        "jordan": "EXPLOIT adds 0.02 and EXPLORE adds 0.01 to the pre-clipped floor",
        "factorial00": "forced SAFE adds neither increment",
        "payoff_relevant": True,
    },
    {
        "family": "negotiation",
        "roles": ["buyer", "seller"],
        "decision_point": "offer",
        "shared_surface": "value beliefs, surplus calculation, outside option, and price bounds",
        "jordan": "heuristic control may select EXPLORE, COMMIT, or EXPLOIT price branches",
        "factorial00": "forced SAFE price branch",
        "payoff_relevant": True,
    },
    {
        "family": "negotiation",
        "roles": ["buyer", "seller"],
        "decision_point": "accept_reject_and_counter",
        "shared_surface": "outside option and reservation-value checks",
        "jordan": (
            "capture floor is 0.16 in EXPLOIT, 0.18 in COMMIT, otherwise 0.22; "
            "default policy does not attach its own counter on every rejection"
        ),
        "factorial00": (
            "forced SAFE uses 0.22 and its action wrapper always attaches the core's "
            "next price to a rejection"
        ),
        "payoff_relevant": True,
    },
    {
        "family": "persuasion",
        "roles": ["seller"],
        "decision_point": "recommendation",
        "shared_surface": "high quality always recommends yes; inherited fixed economic template",
        "jordan": (
            "low quality may recommend yes only through late EXPLOIT/obedience gates; "
            "also records a shadow message that is not sent in default mode"
        ),
        "factorial00": "forced SAFE makes low-quality recommendations no and records no shadow",
        "payoff_relevant": True,
    },
    {
        "family": "persuasion",
        "roles": ["buyer"],
        "decision_point": "buy_or_pass",
        "shared_surface": (
            "recommendation parser, Bayesian posterior, break-even rule, and all experimental "
            "buyer flags off"
        ),
        "jordan": (
            "E_sample lowers the safety margin from 0.04 to 0.02 once visible transcript "
            "length reaches 10"
        ),
        "factorial00": "empty evidence leaves the safety margin at 0.04",
        "payoff_relevant": True,
    },
)


HYPOTHESES = (
    {
        "id": "jordan_v2_family_local_neutral_control",
        "status": "hypothesis_only_unimplemented",
        "exact_code_delta": (
            "Create a separate candidate subclass. Override _control so bargaining and "
            "negotiation return a SAFE StrategicControl with empty evidence and unchanged "
            "beliefs/coverage; delegate persuasion unchanged to JordanStrategicAgent._control. "
            "Change no family rule, counteroffer plumbing, artifact binding, message path, or "
            "default flag. Do not edit MyAgent."
        ),
        "theory": (
            "The bargaining/negotiation heuristic mode selector pays for exploration or "
            "strategic screening without a causal value-of-information certificate. A neutral "
            "mode preserves the theory/reservation-value core while persuasion retains the "
            "legacy late seller exploitation that Factorial00 removed."
        ),
        "eligible_cells": (
            "all bargaining and negotiation roles at offer and response decisions; exact inert "
            "parity required in both persuasion roles"
        ),
        "failure_modes": [
            "the exposed benchmark advantage is evaluator-specific or selection noise",
            "SAFE sacrifices profitable adaptation against live opponents",
            "ambient artifact activation differed between the two benchmark policies",
            "gains concentrate in a few configurations or roles",
            "negotiation counteroffer plumbing, not control mode, explains part of the result",
        ],
        "allowed_development_data": (
            "the already-exposed 900-row Wave 5B ledger only for hypothesis formation and an "
            "exact replay; synthetic/action-parity fixtures; no untouched evaluation rows"
        ),
        "offline_kill_check": (
            "On the exact exposed 900 scenario identities, require persuasion action-byte "
            "parity, no affected family-role paired mean below -0.005, bargaining mean at "
            "least +0.020, overall mean at least +0.010, and no configuration regime holding "
            "more than 50% of absolute gains. Any failure kills this formulation; passage is "
            "development evidence only."
        ),
        "untouched_confirmation": (
            "prospectively freeze a structurally disjoint non-Model-B confirmation of 1,600 "
            "paired games per affected family, seed 20260901, and apply the existing full "
            "promotion gate plus family/role non-regression without threshold changes"
        ),
        "future_live_promotion_criterion": (
            "Only after the frozen Jordan canary is attributable and the untouched offline gate "
            "passes: authorize a new v2 tuple and canary. Require telemetry hostile-audit PASS, "
            "every family official-rating 95% LCB >= 2000, bargaining and negotiation 95% LCB "
            "for v2-minus-Jordan > 0, and persuasion noninferiority lower bound >= -100 rating "
            "points before champion promotion."
        ),
    },
    {
        "id": "jordan_v2_memory_aware_seller_exploitation",
        "status": "hypothesis_only_unimplemented",
        "exact_code_delta": (
            "In a separate candidate, expose prior_yes_recommendations and "
            "prior_buys_after_yes from _persuasion_beliefs. Replace only the low-quality seller "
            "EXPLOIT branch with a one-sided 90% Wilson lower bound on P(buy|yes), requiring "
            "n>=3. For myopic buyers require LCB>=0.50 and remaining_fraction<=0.50; for "
            "persistent buyers require LCB>=0.55, no prior visible yes-on-low event, and "
            "remaining_fraction<=0.25. High-quality recommendations and both buyer policies "
            "remain byte-identical. Do not edit MyAgent."
        ),
        "theory": (
            "A sale has immediate seller value, but a revealed low-quality recommendation can "
            "destroy personalized trust for a persistent buyer. Myopic and persistent receivers "
            "therefore have different intertemporal reputation costs; a sample-aware lower "
            "bound prevents treating a smoothed prior as obedience evidence."
        ),
        "eligible_cells": (
            "persuasion seller, low quality, at least three prior yes recommendations, split "
            "prospectively by myopic versus persistent receiver; all other cells exactly inert"
        ),
        "failure_modes": [
            "the seller cannot legally observe the required response counts in a target schema",
            "myopic market statistics still transmit enough reputation cost to erase the gain",
            "the stricter persistent gate discards profitable terminal sales",
            "Wilson thresholds are too sparse for twenty-round games",
            "apparent gains are driven by the exposed evaluator's buyer policy",
        ],
        "allowed_development_data": (
            "the exposed Wave 5B persuasion-seller rows and their public regime labels for "
            "hypothesis formation; synthetic visible-history probes; no unobserved declined "
            "qualities and no untouched evaluation rows"
        ),
        "offline_kill_check": (
            "On an exact exposed-ledger replay, require changes only in eligible low-quality "
            "seller turns, persuasion-seller mean candidate-minus-Jordan >= +0.005, both myopic "
            "and persistent means >= 0, no regime mean below -0.010, gain concentration <= 0.50, "
            "and zero illegal/private-field reads. Any failure kills this formulation; passage "
            "is development evidence only."
        ),
        "untouched_confirmation": (
            "prospectively freeze 1,600 structurally disjoint non-Model-B persuasion games, seed "
            "20260902, with seller as primary role and prespecified myopic/persistent subgroups; "
            "apply the full promotion gate and intent-to-treat missingness"
        ),
        "future_live_promotion_criterion": (
            "After untouched confirmation and a fresh policy/telemetry audit, separately "
            "authorize a persuasion v2 canary. Require 100 attributable terminals, official "
            "rating 95% LCB >= 2000, v2-minus-frozen-Jordan 95% LCB > 0, no integrity stop, and "
            "no persistent-receiver subgroup regression before champion promotion."
        ),
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_exposed_rows(repo: Path) -> list[dict[str, Any]]:
    path = repo / EXPOSED_OBSERVATIONS
    actual = _sha256(path)
    if actual != EXPOSED_OBSERVATIONS_SHA256:
        raise ValueError(
            f"exposed observations hash mismatch: expected {EXPOSED_OBSERVATIONS_SHA256}, "
            f"found {actual}"
        )
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    required = {
        "key",
        "family",
        "candidate_role",
        "config_regime",
        "opponent_archetype",
        "jordan_payoff",
        "factorial00_payoff",
        "factorial00_minus_jordan",
    }
    if len(rows) != 900 or any(not required.issubset(row) for row in rows):
        raise ValueError("exposed ledger must contain exactly 900 complete paired rows")
    keys = [str(row["key"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("exposed ledger contains duplicate paired identities")
    for row in rows:
        expected = float(row["factorial00_payoff"]) - float(row["jordan_payoff"])
        if not math.isclose(
            float(row["factorial00_minus_jordan"]),
            expected,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(f"paired difference arithmetic changed for {row['key']}")
    family_counts = {
        family: sum(row["family"] == family for row in rows)
        for family in ("bargaining", "negotiation", "persuasion")
    }
    if family_counts != {"bargaining": 300, "negotiation": 300, "persuasion": 300}:
        raise ValueError("exposed ledger is not the frozen 300-per-family comparison")
    return rows


def _summarize(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    differences = [float(row["factorial00_minus_jordan"]) for row in rows]
    return {
        "n": len(rows),
        "mean_jordan": fmean(float(row["jordan_payoff"]) for row in rows),
        "mean_factorial00": fmean(float(row["factorial00_payoff"]) for row in rows),
        "mean_factorial00_minus_jordan": fmean(differences),
        "factorial00_wins": sum(value > 1e-12 for value in differences),
        "factorial00_losses": sum(value < -1e-12 for value in differences),
        "ties": sum(abs(value) <= 1e-12 for value in differences),
    }


def _group_summary(
    rows: Iterable[dict[str, Any]], fields: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[tuple(str(row[field]) for field in fields)].append(row)
    return {
        ":".join(key): _summarize(group)
        for key, group in sorted(groups.items())
    }


def analyze_exposed_development(repo: str | Path) -> dict[str, Any]:
    """Return deterministic mechanism-generation summaries, never a gate verdict."""

    repo = Path(repo)
    summary_path = repo / EXPOSED_SUMMARY
    summary_actual = _sha256(summary_path)
    if summary_actual != EXPOSED_SUMMARY_SHA256:
        raise ValueError(
            f"exposed summary hash mismatch: expected {EXPOSED_SUMMARY_SHA256}, "
            f"found {summary_actual}"
        )
    prior_summary = json.loads(summary_path.read_text())
    if prior_summary.get("evidence_class") != "bounded_offline_architecture_diagnostic_not_promotion":
        raise ValueError("prior summary evidence class changed")

    rows = _load_exposed_rows(repo)
    seller = [
        row
        for row in rows
        if row["family"] == "persuasion" and row["candidate_role"] == "seller"
    ]
    return {
        "input_classification": (
            "previously_exposed_development_reuse_not_untouched_confirmation"
        ),
        "input_rows": len(rows),
        "overall": _summarize(rows),
        "by_family_role": _group_summary(rows, ("family", "candidate_role")),
        "persuasion_seller": {
            **_summarize(seller),
            "mean_jordan_minus_factorial00": -_summarize(seller)[
                "mean_factorial00_minus_jordan"
            ],
            "all_non_ties_favor_jordan": all(
                float(row["factorial00_minus_jordan"]) <= 1e-12 for row in seller
            ),
            "by_config_regime": _group_summary(seller, ("config_regime",)),
            "by_opponent_archetype": _group_summary(seller, ("opponent_archetype",)),
        },
    }


def verify_source_pins(repo: str | Path) -> dict[str, str]:
    repo = Path(repo)
    observed: dict[str, str] = {}
    for relative, expected in SOURCE_PINS.items():
        actual = _sha256(repo / relative)
        if actual != expected:
            raise ValueError(f"source hash mismatch for {relative}: {actual}")
        observed[relative] = actual
    return observed


def build_evidence(repo: str | Path) -> dict[str, Any]:
    """Build the timestamp-free durable certificate for this bounded route."""

    return {
        "schema": "glee.research.wave5d_competition_prep.v1",
        "branch": "research/wave5d-competition-prep",
        "base_commit": "f2a1bb5afe6f83c3a8a03201a0e5939f748ecda9",
        "evidence_class": "hypothesis_generation_from_previously_exposed_development_rows",
        "boundaries": {
            "untouched_evaluation_read": False,
            "underlying_evaluator_artifacts_opened": False,
            "new_payoff_simulation_run": False,
            "jordan_modified": False,
            "candidate_implemented": False,
            "policy_promoted": False,
            "external_api_called": False,
            "live_or_rated_game_run": False,
            "model_b_used": False,
        },
        "input_sha256": {
            str(EXPOSED_OBSERVATIONS): EXPOSED_OBSERVATIONS_SHA256,
            str(EXPOSED_SUMMARY): EXPOSED_SUMMARY_SHA256,
        },
        "source_sha256": verify_source_pins(repo),
        "analysis": analyze_exposed_development(repo),
        "behavior_trace": list(BEHAVIOR_TRACE),
        "persuasion_seller_tradeoff": {
            "observed_development_pattern": (
                "Jordan exceeds Factorial00 by 0.0572992700729927 mean payoff across 137 "
                "seller rows; all 67 non-ties favor Jordan and 70 tie. The sign is nonnegative "
                "for Jordan in every recorded regime and archetype."
            ),
            "source_aligned_mechanism": (
                "Factorial00 deletes heuristic control by forcing SAFE. In low-quality seller "
                "turns that removes Jordan's only late obedience-conditioned yes branch; high-"
                "quality recommendations remain yes."
            ),
            "causal_status": (
                "underidentified: the exposed ledger contains terminal payoffs and subgroup "
                "labels, not action trajectories or intervention labels; source alignment is "
                "a falsifiable mechanism hypothesis, not a decomposition of the payoff gap"
            ),
        },
        "hypotheses": list(HYPOTHESES),
        "strict_evidence_ceiling": (
            "candidate/self-audited competition-preparation hypotheses only; no new payoff, "
            "predictive, confirmation, receiver, leaderboard, or promotion evidence"
        ),
    }


def validate_evidence(repo: str | Path, evidence_path: str | Path) -> None:
    payload = json.loads(Path(evidence_path).read_text())
    if payload.get("analysis") != analyze_exposed_development(repo):
        raise ValueError("durable analysis does not reconstruct from exposed input")
    if payload.get("source_sha256") != verify_source_pins(repo):
        raise ValueError("durable source pins do not reconstruct")
    if payload.get("behavior_trace") != list(BEHAVIOR_TRACE):
        raise ValueError("durable behavior trace differs from frozen trace")
    if payload.get("hypotheses") != list(HYPOTHESES):
        raise ValueError("durable hypothesis records differ from frozen hypotheses")
    boundaries = payload.get("boundaries") or {}
    required_false = (
        "untouched_evaluation_read",
        "underlying_evaluator_artifacts_opened",
        "new_payoff_simulation_run",
        "jordan_modified",
        "candidate_implemented",
        "policy_promoted",
        "external_api_called",
        "live_or_rated_game_run",
        "model_b_used",
    )
    if any(boundaries.get(key) is not False for key in required_false):
        raise ValueError("evidence boundary is missing or not false")
    if len(payload.get("hypotheses") or []) > 2:
        raise ValueError("at most two hypotheses are permitted")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check-evidence", type=Path)
    parser.add_argument("--emit-evidence", action="store_true")
    args = parser.parse_args(argv)
    if args.check_evidence:
        validate_evidence(args.repo, args.check_evidence)
        print("PASS: Wave 5D Route 3 evidence reconstructs from exposed development inputs")
        return
    if args.emit_evidence:
        print(json.dumps(build_evidence(args.repo), indent=2, sort_keys=True))
        return
    print(json.dumps(analyze_exposed_development(args.repo), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
