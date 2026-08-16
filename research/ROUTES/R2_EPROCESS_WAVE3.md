# R2 Wave 3 — acting reference-relative e-process

Status: **implemented research candidate; payoff and live use prohibited.**

The Wave 2 theorem remains unchanged. Wave 3 does not pretend the failed Model B
supplies a null and does not reuse any historical `E_*` score. The acting candidate is
the smaller fixed-reference construction below, backed only by an explicitly supplied,
SHA-verified accepted Model-C response artifact.

## Exact supported stream

| Family / candidate role | Sequential variable available before a later candidate action | Reference law | Acting status |
| --- | --- | --- | --- |
| Bargaining, either role | Opponent acceptance of the candidate's offer | Model C has an acceptance prediction, but an acceptance terminates the episode and is not visible before another callback. Observed callbacks select rejections. | Unsupported: terminal censoring would make an online acting stream outcome-selected. |
| Negotiation, seller or buyer | Opponent acceptance of the candidate's offer | Same terminal-callback obstruction as bargaining. | Unsupported. |
| Persuasion, seller | Whether the buyer follows the seller's completed prior-round recommendation: buy after `yes`, or decline after `no`. | The SHA-locked Model-C persuasion bucket fixes the predictable buy probability for the recommendation, quality, round, public configuration, source, and delivered message style. | **Supported acting scope.** |
| Persuasion, buyer | Purchase after a recommendation | This is the candidate's own decision, not an opponent response. | Unsupported. |
| Continuous offer movement | Offer size or concession | No accepted continuous conditional density/e-factor exists. | Unsupported; never filled with heuristic evidence. |

For the persuasion-seller stream, before buyer outcome `X_t` is observed, let `p0_t`
be the fixed Model-C probability that the buyer follows the recommendation. For `yes`,
this is the fitted buy probability; for `no`, it is one minus the fitted buy probability.
Only non-global buckets with training support at least the artifact's frozen minimum,
support quality at least `.5`, and `p0_t` in `[.01,.99]` enter the process. These checks
depend only on the reference and pre-outcome state.

The fixed alternative is

`q_t = p0_t + .5 * (1 - p0_t)`.

The update is

`L_t = q_t/p0_t` when the buyer follows and
`L_t = (1-q_t)/(1-p0_t)` otherwise, with `M_t=M_(t-1)L_t` and `M_0=1`.

Under the declared composite null
`P(X_t=1 | F_(t-1)) <= p0_t`, conditional expectation is at most one. Thus this
single within-game process is an e-process if—and only if—the hash-locked reference
really is a conditional upper bound. A fitted point prediction does not prove that
premise. The narrower simple-reference claim `P(X_t=1|F)=p0_t` is a likelihood-ratio
martingale. No failed correlated opponent population enters either claim.

## Filtration, reset, and multiplicity

`F_(t-1)` contains only the candidate-visible transcript through its own prior
recommendation, the nature quality visible to an informed seller, public configuration,
the fixed reference artifact, and all earlier completed buyer decisions. The extractor
reconstructs each reference state without the current buyer outcome, rejects current or
future rounds, uses stable event IDs, and is idempotent.

State resets to one at every new `game_id`. It never resets on a mode change. There is
exactly one stream per persuasion-seller game. Threshold `20` corresponds to Ville
crossing control `.05` for that one game if the null holds. There is no across-game,
across-role, or across-family familywise claim; no maximum or favorable signal selection
is performed.

## Acting rule

Before crossing, the treatment records its state but leaves the economic decision and
message unchanged. On the first `M_t >= 20` crossing, a persuasion seller changes a
baseline `no` recommendation to `yes` (`recommend_yes_after_crossing`). Language remains
a separate rendering layer. Unsupported cells retain the exact baseline economic action
and merely log the reason when the e-process arm is on.

This rule operationalizes the hypothesis that obedience exceeds the accepted response
surface. It does **not** establish that the null describes live opponents or that the
override improves payoff. Full payoff and live evaluation remain prohibited.

## Implementation and checks

- `EProcessController` exposes explicit state, full update trace, current e-value,
  crossing record, reset status, exact null/alternative, and unsupported scopes.
- The exact horizon-12 fair-null enumeration is below `1/20`; algebraic checks cover
  several `p <= p0` values. These tests check code, not the supermartingale proof.
- Tests cover idempotence, new-game reset, current/future-outcome exclusion, threshold
  action change, unsupported cells, and absence from the control arm.

Smallest remaining validity gap: accepted Model C supplies a fixed training-only point
reference, not a certified conditional upper bound. Therefore the strongest honest
guarantee is reference-relative; economic calibration and payoff relevance remain open.
