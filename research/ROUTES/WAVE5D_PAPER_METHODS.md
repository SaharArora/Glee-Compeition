# Wave 5D paper-ready Methods: paired e-process × language experiment

Status: **prospective, outcome-blind methods specification.** No treatment outcome or hosted
receiver capability output was inspected. No production authorization hash is set. The design
recommendation below is not authorization to call a receiver or run a payoff study.

## Study objective and shared economic baseline

The study asks whether adding an acting e-process (`E`) and/or a fixed language-rendering
intervention (`L`) to one shared theory-plus-Model-C economic policy changes normalized candidate
payoff. The unrestricted competition agent is not an experimental arm. Four forced entrypoints
implement the complete `2 × 2` assignment:

| Entrypoint | `E` | `L` | Composition |
| --- | ---: | ---: | --- |
| `Factorial00Agent` | 0 | 0 | shared treatment-off economic core |
| `Factorial10Agent` | 1 | 0 | core, then e-process |
| `Factorial01Agent` | 0 | 1 | core, then language rendering |
| `Factorial11Agent` | 1 | 1 | core, then e-process, then language rendering |

All four arms share the same hash-locked theory-plus-Model-C core, support rules, economic RNG,
scenario, configuration, opponent draw, role, stopping rule, and exogenous/nature stream.
Composition order is `economic core -> e-process -> language`. The language policy receives the
post-e-process stance and cannot independently change the numeric action. Model B is not an input.

## E-process intervention

The e-process is defined only for completed prior rounds in persuasion games in which the
candidate is the seller. Let `X_t=1` if the buyer follows the seller's recommendation in completed
round `t`. A fixed, hash-locked Model-C reference supplies the predictable follow probability
`p_{0,t}` from legally visible history before `X_t`; define

\[
q_t=p_{0,t}+0.5(1-p_{0,t}),
\qquad
M_t=\left(\frac{q_t}{p_{0,t}}\right)^{X_t}
    \left(\frac{1-q_t}{1-p_{0,t}}\right)^{1-X_t},
\qquad
E_t=\prod_{s\le t}M_s.
\]

Under the explicitly conditional, model-relative null

\[
\Pr(X_t=1\mid\mathcal F_{t-1})\le p_{0,t},
\]

`E_t` is a nonnegative supermartingale. The treatment crosses at the first `E_t >= 20`; Ville's
inequality gives a within-process bound of `0.05` under that null. Following a crossing, the acting
treatment may change a supported baseline seller recommendation from `no` to `yes`. The process
does not establish that Model C upper-bounds real-opponent behavior, does not control multiplicity
across games or Model-C buckets, and is not defined for bargaining, negotiation, or persuasion
candidate-buyer decisions.

## Language intervention and controlled receiver

Language is a fixed rendering intervention after the economic stance is complete. It is eligible
only for a persuasion candidate-seller in a text configuration. It chooses between prespecified
templates for the already-fixed `yes` or `no` stance. Unsupported families and roles are language
negative controls.

Identification requires a controlled receiver contract that sends only the public state,
economic stance, and candidate text while hiding arm, scenario identity, private quality,
template identity, e-process state, future events, terminal state, and payoffs. The Wave 5C
proposal names a primary and nonautomatic fallback, strict JSON output, two receiver replicate
tags (`530011`, `530017`), timeout/retry/cache rules, and a treatment-blind capability gate. No
hosted receiver has been called or capability-certified, and neither proposed identity is a study
input until separately selected and authorized.

## Experimental unit, repeated measures, and clustering

The arm-comparison unit is one **paired scenario row**. Each row is executed under all four forced
arms, so four episode payoffs create within-row repeated measures rather than four independent
observations. For row `i`, let `Y_i(e,l)` be normalized candidate payoff. The row contrasts are

\[
\begin{aligned}
D_{E,i} &= \tfrac12\{[Y_i(1,0)-Y_i(0,0)]+[Y_i(1,1)-Y_i(0,1)]\},\\
D_{L,i} &= \tfrac12\{[Y_i(0,1)-Y_i(0,0)]+[Y_i(1,1)-Y_i(1,0)]\},\\
D_{I,i} &= Y_i(1,1)-Y_i(1,0)-Y_i(0,1)+Y_i(0,0).
\end{aligned}
\]

In recommended Design A300, each family contains 300 prospectively selected base economic strata,
crossed with both candidate roles and two receiver/environment replicates. Thus each family has
`300 × 2 × 2 = 1,200` paired rows. Receiver replicates and role views sharing a base economic
stratum are repeated observations in the same cluster. For the eligible persuasion-seller primary
population, each cluster contributes at most two paired rows, one per receiver replicate; hence the
maximum primary count is 600 paired rows in 300 independent base-stratum clusters. The 20 receiver
decisions within each episode are serial process measurements and never increase the inferential
sample size.

The exact number of structurally e-process-eligible clusters may be below 300 because eligibility
also requires a prospectively supported, non-global Model-C follow reference. It must be computed
from the frozen manifest before outcomes, never replaced after observing reach or payoff.

## Randomization and RNG isolation

The master seed remains `20260829`. Deterministic, independently named streams govern scenario
selection, environment/nature, opponent policy, candidate economic policy, e-process treatment,
language treatment, controlled receiver, and evaluator. Every arm reuses the same scenario,
environment, opponent, and economic stream identity. Treatment objects receive only their own
capability-scoped RNG. Scenario ordering, base-stratum identities, role crossings, receiver
replicate tags, eligibility, and support masks must be committed in the pre-outcome manifest.

Because all four arms are run for every row, this is paired forced assignment, not a parallel-arm
allocation. Arm execution order must be mechanically order-invariant and may not control a shared
mutable RNG or cache.

## Outcomes, estimands, and multiplicity

The outcome is normalized terminal candidate payoff on the existing family-specific scale. The
three confirmatory hypotheses are:

1. the mean `D_E` on immutable structurally e-process-eligible rows;
2. the mean `D_L` on immutable language-eligible rows under a certified text-responsive receiver;
3. the mean `D_I` on the conjunction of those eligibility labels.

Family effects are estimated from base-stratum cluster means and averaged equally over nonempty
eligible families. Under the implemented intervention scopes, all three headline populations can
be nonempty only in persuasion candidate-seller text cells, so their maximum design size is 300
independent clusters. Overall all-family contrasts, every family/role/configuration cell, and
predeclared negative controls are secondary. The three headline two-sided normal tests use Holm
step-down family-wise error control at `0.05`. Improvement requires a Holm-adjusted interval
strictly above zero; harm requires it strictly below zero; every other result is nonconfirming.
The acting e-process is a treatment and never replaces this fixed-sample analysis.

## Missingness and failures

Analysis is intent-to-treat. Every prospectively assigned row remains in the manifest; failed,
timed-out, refused, empty, or malformed receiver results are labelled, are not replaced, and do
not trigger arm-specific fallback. The current contracts validate that admission rule, but they
do not yet specify how a retained absent receiver decision produces a numeric terminal payoff,
while the current report accepts only numeric payoffs. Therefore production activation requires a
single treatment-blind failure-to-environment/payoff rule frozen before calls. If terminal payoff
is still unavailable under that rule, no complete-case confirmatory claim is permitted: the
headline analysis becomes nonreportable and must show prespecified bounded sensitivity analyses.

For planning only, the MDE grid includes an `information_loss` sensitivity factor. It describes
variance/information degradation and is not a post-assignment exclusion rule.

## Prospective precision audit and recommendation

For a balanced primary cluster with `K` base strata, `m=2` receiver replicates, intraclass
correlation `rho`, and conservative information loss `a`, planning effective sample size is

\[
n_{eff}=\frac{Km(1-a)}{1+(m-1)\rho}.
\]

Using 80% power and the most stringent first Holm step (`alpha/3`, two-sided), the planning MDE
for a row-contrast standard deviation `sigma_D` is

\[
\operatorname{MDE}=
\left[z_{1-0.05/(2\cdot3)}+z_{0.80}\right]\frac{\sigma_D}{\sqrt{n_{eff}}},
\]

where the two quantiles sum to approximately `3.2356`. For A300 and `sigma_D=0.20`, exact grid
values are:

| ICC | loss 0% | loss 5% | loss 10% | loss 20% |
| ---: | ---: | ---: | ---: | ---: |
| 0.00 | 0.02642 | 0.02710 | 0.02785 | 0.02954 |
| 0.25 | 0.02954 | 0.03030 | 0.03113 | 0.03302 |
| 0.50 | 0.03236 | 0.03320 | 0.03411 | 0.03618 |
| 0.75 | 0.03495 | 0.03586 | 0.03684 | 0.03907 |

The values for `sigma_D` equal to `0.10`, `0.30`, `0.50`, `0.75`, and `1.00` are exactly `0.5×`,
`1.5×`, `2.5×`, `3.75×`, and `5×` the table. The larger values cover the wider support of the
interaction contrast. The executable evidence contains all 96 grid cells.

No outcome-blind variance estimate or smallest effect of scientific interest has been frozen.
Consequently, 3,600 rows are not proven adequate in an absolute power sense. Under the explicit
central planning case (`sigma_D=0.20`, `rho=0.50`, 10% information loss), A300 has
`n_eff=360` and MDE `0.03411`; smaller A-shaped designs with 200, 140, and 100 strata have MDEs
`0.04177`, `0.04993`, and `0.05907`. Detecting the existing `0.0100` practical reference under
the same assumptions would require 3,490 base strata per family (41,880 paired rows), far beyond
the proposal.

**Recommendation:** retain **Design A300** as the single prospective design because a
nondeterministic hosted receiver requires direct replication and every evaluated smaller design
materially worsens already limited precision. Interpret it as designed for effects around `0.035`
or larger under the central assumptions, not as powered for `0.0100`. This recommendation does not
set either production pin. Activation is blocked until cluster identity/inference and the exact
ITT failure-to-payoff rule are implemented and independently audited.

## Evidence limitations

The design arithmetic uses no treatment or capability outcomes. Synthetic tests show only that a
small pre-outcome manifest, four-arm evaluator, ITT admission envelope, report builder, and report
reconstruction can execute with local fixtures while both production pins remain `None`. They do
not validate hosted-receiver behavior, treatment effects, payoff gains, population-level
e-process validity, Model A or B, or leaderboard performance.
