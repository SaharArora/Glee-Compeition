# Frozen research question — revision 1

Status: frozen before treatment implementation or factorial evaluation.

## Question

Does adding (1) a formally valid anytime-evidence process and/or (2) a grounded
language intervention to the same theory-plus-empirical-residual economic agent
improve normalized payoff?

The experiment is the following 2x2 factorial comparison:

| | Language off | Language on |
| --- | --- | --- |
| E-process off | Baseline | Baseline + Language |
| E-process on | Baseline + E | Baseline + E + Language |

The unrestricted competition champion is not an experimental arm. Research arms
remain frozen even if the champion changes.

## Outcomes and eligible populations

The primary outcome is equal-family-weighted normalized payoff: the arithmetic mean
of the bargaining, negotiation, and persuasion family means, with payoff normalized
by each family's existing production scale. Each family's normalized payoff is a
mandatory reported secondary outcome. Agreement, rounds, purchase/recommendation
rates, downside quantiles, and action reach are diagnostics, not substitutes for
payoff.

The overall estimand includes every structurally eligible scenario in the frozen
offline evaluation population. The language-eligible estimand includes only scenarios
whose frozen contract both exposes a textual message to the treated agent and delivers
that message to a text-responsive opponent/evaluator. Eligibility is determined from
the paired pre-treatment scenario and cannot depend on an arm's action or outcome. If
no causally defensible language-eligible population exists, the study reports that
verifier-backed limitation and does not substitute a text-blind zero-effect result.

## Treatments

E-process off means the shared economic baseline has no heuristic `E_*` mode gate and
no anytime-evidence state. E-process on may alter behavior only through an implementation
that is mathematically established to be an e-process under the declared filtration and
null; a plug-in score or favorable crossing simulation is not the treatment.

Language off means no language intervention is generated or consumed beyond the exact
messages already required by the shared baseline contract. Language on may alter only
the preregistered grounded message surface. It may not directly change numeric offers,
acceptance thresholds, random seeds, support filtering, opponent draws, or hidden state.
Any economic action change must occur through the receiving policy's documented response
to the delivered message.

All four arms use the same frozen theory-plus-validated-empirical-residual economic core,
scenario, opponent draw, candidate role, random-number substreams, stopping rule, and
support mask. With both treatments off, all four wrappers must be behaviorally identical.

## Estimands

For paired scenario payoff `Y(e,l)`, the e-process main effect is
`0.5 * [(Y(1,0)-Y(0,0)) + (Y(1,1)-Y(0,1))]`. The language main effect is
`0.5 * [(Y(0,1)-Y(0,0)) + (Y(1,1)-Y(1,0))]`. The interaction is
`Y(1,1)-Y(1,0)-Y(0,1)+Y(0,0)`. Report these overall and by family, plus the
language main effect and interaction on the language-eligible population.

## Splits and final paired study

Any learned treatment component is trained only on the repository's FIT partitions.
The final factorial study uses the frozen structural-holdout opponent population and
config-holdout catalogue selected and hash-locked by R1/R4 before treatment outcomes
are measured. The intended final design is 3,600 paired scenarios at master seed
`20260829`, exactly 1,200 per family, with candidate roles balanced within every family
and identical scenarios reused by all four arms. If R1 or R4 proves that these inputs do
not implement the stated population or pairing contract, the route records a decisive
obstruction; this file is not edited to make an observed result pass.

The three primary factorial contrasts use Holm family-wise error control at 0.05.
An effect is called an improvement only when its Holm-adjusted confidence interval is
strictly above zero. An interval not strictly above zero is a negative/non-confirming
result, not permission to retune the treatment. A contrast strictly below zero is
reported as harm. Effect sizes and unadjusted intervals are always reported, including
the existing competition-policy practical reference of `0.0100`, but research success
does not silently inherit the competition promotion label.

## Completion interpretation

A successful result, a null/negative result, or a verifier-backed impossibility can each
complete the relevant route if it satisfies the route's frozen completion condition.
Leaderboard placement is not a research outcome.
