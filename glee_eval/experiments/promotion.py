"""The evidence gate a policy change must clear before it becomes a default.

Every policy change shipped in this repo so far was promoted on a single paired
A/B run, with no threshold agreed in advance, no check that the gain was spread
across opponents rather than concentrated in one, and no slice of data held back
from fitting. That is how the first debug report came to describe a 33-game
comparison against hand-picked opponents as "a confirmed, live bug... not a
testbed artifact" -- and it was wrong.

The criteria below are deliberately fixed in code and defaulted, so a change is
measured against a standard set before its result is known rather than after.
Loosening one for a specific change means editing this file, which is a visible
act. `docs/PROMOTION_CRITERIA.md` explains the reasoning behind each number.

Nothing here is an anytime-valid test. These are fixed-sample checks on a
pre-declared comparison; the e-process framework remains deferred by design, and
calling this "significance" means the ordinary paired t statistic and nothing
stronger.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class PromotionCriteria:
    """Thresholds a change must clear. See docs/PROMOTION_CRITERIA.md."""

    # Payoffs are normalized surplus fractions, so 0.01 is one point of
    # normalized payoff -- below that a change is not worth the added policy
    # surface even when it is real.
    min_effect: float = 0.01
    # Enough paired episodes that a 0.01 effect is detectable at all.
    min_paired_n: int = 200
    # Ordinary two-sided paired t at 95%. Not anytime-valid.
    significance_t: float = 1.96
    # A gain that is more than half attributable to one opponent or config
    # subgroup is a subgroup-specific fix wearing a general change's clothes.
    max_subgroup_gain_share: float = 0.50
    # Some subgroups regressing is normal; most of them regressing is not.
    max_negative_subgroup_fraction: float = 0.40
    min_subgroups: int = 3
    # The candidate's own bad tail must not be materially worse than the
    # baseline's. This is the "no material downside" check, expressed on
    # outcomes rather than on paired differences, because the 5th percentile of
    # a difference distribution is negative for almost any change with variance
    # and would reject everything.
    max_p5_regression: float = 0.02
    require_holdout: bool = True


@dataclass
class Observation:
    """One paired outcome: the same scenario played by baseline and candidate."""

    key: str
    baseline: float
    candidate: float
    subgroups: dict[str, str] = field(default_factory=dict)

    @property
    def difference(self) -> float:
        return self.candidate - self.baseline


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((value - mu) ** 2 for value in values) / (len(values) - 1))


def _percentile(values: Sequence[float], point: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(point * (len(ordered) - 1)))))
    return ordered[index]


def _check(name: str, passed: bool, observed: Any, threshold: Any, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "observed": observed, "threshold": threshold, "detail": detail}


def _subgroup_report(observations: Sequence[Observation], dimension: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = {}
    for observation in observations:
        label = observation.subgroups.get(dimension)
        if label is None:
            continue
        groups.setdefault(str(label), []).append(observation.difference)
    if not groups:
        return {"dimension": dimension, "subgroups": 0, "rows": []}

    rows = []
    for label, differences in sorted(groups.items()):
        rows.append(
            {
                "label": label,
                "n": len(differences),
                "mean_effect": _mean(differences),
                # Total payoff this subgroup contributes to the overall gain.
                "contribution": _mean(differences) * len(differences),
            }
        )
    positive = [row["contribution"] for row in rows if row["contribution"] > 0]
    total_positive = sum(positive)
    max_share = (max(positive) / total_positive) if total_positive > 0 else 0.0
    negatives = [row for row in rows if row["mean_effect"] < 0]
    return {
        "dimension": dimension,
        "subgroups": len(rows),
        "max_gain_share": max_share,
        "negative_subgroup_fraction": len(negatives) / len(rows),
        "rows": sorted(rows, key=lambda row: row["mean_effect"]),
    }


def evaluate_promotion(
    observations: Iterable[Observation],
    *,
    criteria: PromotionCriteria | None = None,
    change: str = "unnamed change",
    evaluated_on_holdout: bool = False,
    holdout_description: str | None = None,
    subgroup_dimensions: Sequence[str] = ("opponent_archetype", "config_regime"),
) -> dict[str, Any]:
    """Decide whether a paired comparison clears the gate.

    `observations` must be paired on the same scenarios; unpaired comparisons are
    what produced the over-confident findings this exists to prevent.
    """

    criteria = criteria or PromotionCriteria()
    rows = list(observations)
    differences = [observation.difference for observation in rows]
    baseline = [observation.baseline for observation in rows]
    candidate = [observation.candidate for observation in rows]

    n = len(rows)
    effect = _mean(differences)
    sd = _stdev(differences)
    se = sd / math.sqrt(n) if n > 1 and sd > 0 else 0.0
    t_stat = effect / se if se > 0 else (math.inf if effect > 0 else (-math.inf if effect < 0 else 0.0))

    baseline_p5 = _percentile(baseline, 0.05)
    candidate_p5 = _percentile(candidate, 0.05)
    p5_regression = baseline_p5 - candidate_p5

    checks: list[dict[str, Any]] = [
        _check(
            "sample_size",
            n >= criteria.min_paired_n,
            n,
            criteria.min_paired_n,
            "Paired episodes available for the comparison.",
        ),
        _check(
            "minimum_effect",
            effect >= criteria.min_effect,
            effect,
            criteria.min_effect,
            "Paired mean improvement in normalized payoff.",
        ),
        _check(
            "significance",
            t_stat >= criteria.significance_t,
            t_stat,
            criteria.significance_t,
            "Paired t statistic. Fixed-sample, not anytime-valid.",
        ),
        _check(
            "downside_p5",
            p5_regression <= criteria.max_p5_regression,
            p5_regression,
            criteria.max_p5_regression,
            "How much worse the candidate's 5th-percentile outcome is than the baseline's.",
        ),
        _check(
            "structural_holdout",
            evaluated_on_holdout or not criteria.require_holdout,
            bool(evaluated_on_holdout),
            criteria.require_holdout,
            holdout_description or "Evaluated on a slice withheld from fitting.",
        ),
    ]

    subgroups = [_subgroup_report(rows, dimension) for dimension in subgroup_dimensions]
    for report in subgroups:
        dimension = report["dimension"]
        if report["subgroups"] < criteria.min_subgroups:
            checks.append(
                _check(
                    f"subgroup_coverage[{dimension}]",
                    False,
                    report["subgroups"],
                    criteria.min_subgroups,
                    "Too few subgroups on this dimension to judge concentration.",
                )
            )
            continue
        checks.append(
            _check(
                f"subgroup_concentration[{dimension}]",
                report["max_gain_share"] <= criteria.max_subgroup_gain_share,
                report["max_gain_share"],
                criteria.max_subgroup_gain_share,
                "Share of the total gain contributed by the single best subgroup.",
            )
        )
        checks.append(
            _check(
                f"subgroup_breadth[{dimension}]",
                report["negative_subgroup_fraction"] <= criteria.max_negative_subgroup_fraction,
                report["negative_subgroup_fraction"],
                criteria.max_negative_subgroup_fraction,
                "Fraction of subgroups where the candidate is worse.",
            )
        )

    failed = [check["name"] for check in checks if not check["passed"]]
    return {
        "schema_version": 1,
        "change": change,
        "promoted": not failed,
        "failed_checks": failed,
        "criteria": asdict(criteria),
        "summary": {
            "paired_n": n,
            "mean_effect": effect,
            "stdev": sd,
            "standard_error": se,
            "t_statistic": t_stat,
            "ci95_low": effect - 1.96 * se,
            "ci95_high": effect + 1.96 * se,
            "wins": sum(1 for value in differences if value > 1e-9),
            "losses": sum(1 for value in differences if value < -1e-9),
            "ties": sum(1 for value in differences if abs(value) <= 1e-9),
            "baseline_mean": _mean(baseline),
            "candidate_mean": _mean(candidate),
            "baseline_p5": baseline_p5,
            "candidate_p5": candidate_p5,
            "p5_regression": p5_regression,
            "difference_p5": _percentile(differences, 0.05),
            "evaluated_on_holdout": bool(evaluated_on_holdout),
            "holdout_description": holdout_description,
        },
        "checks": checks,
        "subgroups": subgroups,
    }


def verdict_markdown(verdict: dict[str, Any]) -> str:
    summary = verdict["summary"]
    lines = [
        f"# Promotion decision: {verdict['change']}",
        "",
        f"**{'PROMOTE' if verdict['promoted'] else 'DO NOT PROMOTE'}**",
        "",
        f"- Paired n: {summary['paired_n']}",
        f"- Mean effect: {summary['mean_effect']:+.4f} "
        f"(95% CI {summary['ci95_low']:+.4f} to {summary['ci95_high']:+.4f}, t={summary['t_statistic']:+.2f})",
        f"- Win/loss/tie: {summary['wins']}/{summary['losses']}/{summary['ties']}",
        f"- 5th-percentile outcome: baseline {summary['baseline_p5']:+.4f} -> candidate {summary['candidate_p5']:+.4f}",
        f"- Evaluated on holdout: {summary['evaluated_on_holdout']} ({summary['holdout_description']})",
        "",
        "## Checks",
        "",
        "| Check | Result | Observed | Threshold |",
        "|---|---|---:|---:|",
    ]
    for check in verdict["checks"]:
        observed = check["observed"]
        observed_text = f"{observed:.4f}" if isinstance(observed, float) and math.isfinite(observed) else str(observed)
        threshold = check["threshold"]
        threshold_text = f"{threshold:.4f}" if isinstance(threshold, float) else str(threshold)
        lines.append(f"| {check['name']} | {'pass' if check['passed'] else 'FAIL'} | {observed_text} | {threshold_text} |")
    for report in verdict["subgroups"]:
        if not report.get("rows"):
            continue
        lines += ["", f"## Subgroups: {report['dimension']}", "", "| Subgroup | n | Mean effect |", "|---|---:|---:|"]
        for row in report["rows"]:
            lines.append(f"| {row['label']} | {row['n']} | {row['mean_effect']:+.4f} |")
    return "\n".join(lines) + "\n"
