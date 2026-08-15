# Approach registry

Durable status for policy, scoring, and evidence work. Statuses follow
`docs/HANDOVER.md` §0.9 exactly: `candidate`, `gate-passed`, `confirmed`, `shipped`, or
`retracted`. A status never outruns the weakest supporting run.

| Family | Exact change | Remaining gap | Last gate/evidence | Status | Owner | Dependencies / shared surfaces | Evidence |
|---|---|---|---|---|---|---|---|
| `theory_anchor` | Bargaining offer policy uses the theory anchor by default. | None recorded. | Holdout: +0.0737, t=+12.43, n=800, 389W/91L; earlier fitted-population run +0.046, t=+6.60. | `shipped` | none | Bargaining offer path. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.1/§2 |
| `time_concession` | Optional Boulware time-dependent negotiation concession (`use_time_concession=False`). | Below minimum effect; offline population rarely reaches long negotiations. | +0.0003, t=+2.11, 6W/76L/1518T, n=1600; failed `minimum_effect`. | `candidate` | unassigned | Shared negotiation counteroffer path with `guarantee_own_margin` and `debias_counterpart_value`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2-§0.4 |
| `guarantee_own_margin` | Optional own-profitability offer clip and live `counter_price` plumbing (`guarantee_own_margin=False`). | Human decision on `minimum_effect` policy; then a materially new candidate and preregistered confirmation are required. | +0.0076, t=+9.46, 117W/0L/1483T, n=1600; failed only `minimum_effect`. | `candidate` | unassigned | Shared negotiation counteroffer path with `time_concession` and `debias_counterpart_value`; blocked from shipping by `minimum_effect_policy`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2/§0.7 |
| `debias_counterpart_value` | Optional correction of opening-price inference using measured median shading/markup (`debias_counterpart_value=False`). | Below minimum effect and too concentrated by config regime. | +0.0072, t=+7.52, 64W/1L/1535T, n=1600; failed `minimum_effect` and concentration 0.5951. | `candidate` | unassigned | Shared negotiation counteroffer path with `time_concession` and `guarantee_own_margin`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2/§0.5 |
| `combined_counteroffer_path` | Enable time concession, own-margin guarantee/counter-price, and value de-bias as one coupled mechanism. | Confirmation failed; do not rerun unchanged. A retry must be materially new. | Gate seed 4242: +0.0109, t=+10.07, n=1600, passed. Declared confirmation seed 9999: +0.0094, t=+12.49, n=3200, failed `minimum_effect` and concentration 0.5539. | `retracted` | unassigned | Owns the shared negotiation counteroffer surface; depends on `minimum_effect_policy`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.3 |
| `persuasion_explore` | Optional negative-EV purchase to break the no-observation cold start (`persuasion_explore=False`). | Need a materially new formulation that is not the three rejected variants. | Best formulation: +0.0051, t=+3.36, n=1600; failed `minimum_effect`, concentration 0.627, breadth 0.5. | `candidate` | unassigned | Persuasion buyer policy; coordinate with calibration/deceptive-seller work. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2 |
| `persuasion_accessor` | Read persuasion quality from the production transcript shape. | Deceptive-seller regression remains follow-up work. | +0.0160, t=+7.25, n=1600; failed breadth 0.4375 and shipped under the documented defect carve-out. | `shipped` | `deceptive_seller` investigating follow-up | Persuasion buyer posterior and deceptive-seller work. | `docs/PROMOTION_CRITERIA.md` |
| `persuasion_calibration_bins` | Diagnose buyer under-confidence in posterior bins 0.5-0.8; no policy change selected yet. | Kill-check and mechanism diagnosis in progress. | Handover reports buyer ECE 0.0826 and residual under-confidence; no candidate gate run. | `candidate` | `calibration_bins` | Persuasion buyer posterior; coordinate with `persuasion_accessor` and `persuasion_explore`. | `docs/HANDOVER.md` §0.7/§4 |
| `message_mode` | Confidence/social-proof persuasion composer runs in shadow (`message_mode="shadow"`). | Simulator cannot test message text; requires non-circular real evidence. | Replacing text with `"."` changes simulated payoff by 0.000000. | `candidate` | unassigned | Live evidence only; no live games without per-instance user authorization. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.6 |
| `minimum_effect_policy` | Decide whether rare-path defect fixes retain the unconditional 0.0100 threshold or use a preregistered variant. | Explicit human decision required before changing `docs/PROMOTION_CRITERIA.md`; no retrospective conditioned endpoint. | Current rule: unconditional paired mean >=0.0100; four candidates remain below it. | `candidate` | user decision pending | Blocks default flips for rejected negotiation candidates; policy must be written before new measurements. | `docs/HANDOVER.md` §0.7; `docs/PROMOTION_CRITERIA.md` |
| `h6_percentile` | Decide whether shadow negotiation percentiles should stratify gains/no-trade regimes. | Human decision: better skill measure versus unknown alignment with official pooled scoring. | Diagnostic confirmed: no-trade 0.385 pooled vs 0.508 stratified; gains 0.769 pooled vs 0.599 stratified. Reported, not corrected. | `confirmed` | `h6_scoring` investigating reporting candidate | Scoring/reporting only; does not touch agent policy. | `docs/HANDOVER.md` §2/§6 |

## Session kill-checks

Each active investigation must add its smallest real-log contradiction check here before any
implementation. Active read-only owners: `deceptive_seller`, `calibration_bins`, and
`h6_scoring`.

## Confirmation declarations

Add sample size and seed here before executing any independent confirmation run. None is
currently declared.
