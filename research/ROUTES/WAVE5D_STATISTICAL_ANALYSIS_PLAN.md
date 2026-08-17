# Wave 5D Statistical Analysis Plan

Version: `glee.research.wave5d.sap.v1`  
Status: **prospective recommendation; production pins unset; no treatment outcomes inspected.**

## 1. Activation conditions

The study must not start until all of the following reconstruct and pass a fresh independent
audit:

1. an independently selected and capability-certified controlled receiver;
2. exact receiver, prompt, adapter, dependency, parser, retry, cache, and failure hashes;
3. a 3,600-row A300 scenario manifest with 300 unique base-stratum IDs per family, both candidate
   roles and exactly two receiver-replicate tags per base stratum;
4. frozen Model-C, support-index, non-Model-B opponent-population, and configuration-catalogue
   bytes;
5. a report implementation that reconstructs base-stratum clusters and uses clustered inference;
6. a treatment-blind rule mapping every receiver failure status to continued environment behavior
   and terminal-payoff availability;
7. separate authorized hashes for the exact pre-outcome manifest and report contract.

Failure of any condition closes the run before treatment outcomes. Capability passage alone is
not payoff authorization.

## 2. Design and indexing

The recommended design is A300: three families `f`, 300 base economic strata `b` per family, two
candidate roles `r` per family, two receiver/environment replicates `k`, and all four factorial
arms `(e,l)`. The manifest contains `3 × 300 × 2 × 2 = 3,600` paired rows and the evaluator runs
14,400 episodes. `base_stratum_id`, role, replicate tag, scenario ID, and all RNG-stream hashes are
pre-outcome fields.

The experimental comparison is within paired scenario row `(f,b,r,k)`. The independent sampling
cluster is `(f,b)`. Arm episodes and the 20 within-episode receiver decisions are repeated
measurements, not independent sample units.

## 3. Analysis populations

- `P_E`: rows with pre-outcome `eprocess_eligible=true`.
- `P_L`: rows with pre-outcome `language_eligible=true` under a passed receiver certificate.
- `P_I`: rows with both labels true.
- `P_all`: every manifest row, used for mandatory secondary all-family estimates.
- Negative controls: complements of the treatment-specific eligibility labels and the interaction
  complement.

Eligibility is reconstructed only from scenario bytes, role, public horizon, Model-C/support
bytes, message mode, and receiver contract. Treatment reach, crossing, actions, receiver output,
terminal state, and payoff are forbidden inputs. No failed or apparently uninformative row is
replaced.

## 4. Row contrasts

For every assigned row with a terminal normalized payoff in all four arms, compute

```text
D_E = 0.5 * ((Y10 - Y00) + (Y11 - Y01))
D_L = 0.5 * ((Y01 - Y00) + (Y11 - Y10))
D_I = Y11 - Y10 - Y01 + Y00
```

Arm order is irrelevant. The evaluator must reconstruct pairing, artifact identity, eligibility,
support, role, environment/opponent/nature streams, economic RNG identity, and treatment-specific
capability claims before admitting the row.

## 5. Clustered estimator

For contrast `c`, eligible family `f`, and base stratum `b`, average all eligible row contrasts in
that cluster:

\[
\bar D_{fbc}=m_{fb}^{-1}\sum_{i\in(f,b)\cap P_c}D_{ic}.
\]

Let `B_f` be the number of nonempty eligible base-stratum clusters. The family estimate and
standard error are

\[
\hat\theta_{fc}=B_f^{-1}\sum_b\bar D_{fbc},\qquad
SE(\hat\theta_{fc})=s(\bar D_{fbc})/\sqrt{B_f}.
\]

The headline estimate averages family estimates equally over nonempty structurally eligible
families, with variance equal to the sum of squared family standard errors divided by the squared
number of included families. All currently possible headline populations occur in persuasion
candidate-seller text cells, so their maximum `B_f` is 300. Analyses must report both paired-row
`n` and independent-cluster `B_f`; episode and request counts may not be shown as sample size.

The current `factorial_report.py` row-level variance estimator does not implement this cluster
step. It is acceptable for the synthetic arithmetic canary only and is prohibited for A300
production inference until repaired and freshly audited.

## 6. Confirmatory hypotheses and Holm procedure

At two-sided family-wise alpha `0.05`, test:

1. `H_E: theta_E = 0` on `P_E`;
2. `H_L: theta_L = 0` on `P_L`;
3. `H_I: theta_I = 0` on `P_I`.

Compute two-sided normal p-values from clustered standard errors. Sort them ascending and apply
Holm step-down multipliers `3`, `2`, and `1`, preserving monotonic adjusted p-values. Show
unadjusted effects and intervals plus Holm-adjusted intervals. A positive claim requires both a
Holm-adjusted p-value below `0.05` and the corresponding adjusted interval strictly above zero.
A strictly negative adjusted interval is harm. Otherwise report nonconfirmation. If any primary
population is empty or not reportable, the three-hypothesis family is nonreportable; do not reduce
the multiplicity family after seeing data.

## 7. Missingness and execution failures

All assigned rows and arm statuses remain in the ITT ledger. Record receiver status (`ok`,
`timeout`, `refusal`, `malformed`, or `missing`), attempts, and terminal-payoff availability by arm.
No arm-specific retry, silent fallback, row substitution, or complete-case deletion is allowed.

Before activation, freeze exactly one rule for how an absent receiver decision advances the game.
If that rule still yields all four terminal payoffs, analyze those payoffs by assignment and report
failure-rate contrasts. If any terminal payoff is absent, the primary estimator is nonreportable;
report bounded best/worst-case sensitivity over the normalized payoff range and do not claim
improvement. The MDE `information_loss` grid is planning sensitivity only and never authorizes
deletion or post-outcome imputation.

## 8. Secondary and diagnostic reporting

Always report:

- all-family `D_E`, `D_L`, and `D_I`, equal-family weighted;
- every family and candidate-role cell;
- every configuration cell meeting the frozen minimum reporting count;
- e-process, language, and interaction negative controls;
- agreement/purchase/recommendation rates, rounds, downside quantiles, treatment reach, first
  e-process crossing, receiver failure and retry rates;
- replicate disagreement rates and base-stratum ICC estimates as descriptive diagnostics.

Diagnostics cannot replace payoff or redefine eligibility. No subgroup becomes confirmatory after
outcomes. A receiver-replicate difference is a robustness diagnostic, not a second experiment.

## 9. Power and precision reporting

Prospective calculations use 80% power, the most stringent two-sided Holm level `0.05/3`,
contrast-SD grid `{0.10, 0.20, 0.30, 0.50, 0.75, 1.00}`, ICC grid
`{0, 0.25, 0.50, 0.75}`, and information-loss grid `{0, 0.05, 0.10, 0.20}`. Report the entire grid from
`glee_eval.experiments.wave5d_paper_design.mde_grid`, not a data-selected cell.

The central planning cell (`SD=.20`, `ICC=.50`, loss=.10`) yields:

| Design | clusters | eligible paired rows | effective N | MDE |
| --- | ---: | ---: | ---: | ---: |
| A300 | 300 | 600 | 360 | 0.03411 |
| A200 | 200 | 400 | 240 | 0.04177 |
| A140 | 140 | 280 | 168 | 0.04993 |
| A100 | 100 | 200 | 120 | 0.05907 |

These are planning assumptions, not observed variance or evidence of adequacy. A300 is not
described as powered for the `0.0100` practical reference.

## 10. Resource envelope

The exact request accounting includes the 100-request capability stage and reserves one
conditional retry per request. Prices are the Wave 5C planning snapshot and must be reverified
before any later authorization.

| Design | paired rows | episodes | nominal/max attempts | primary USD nominal/max | fallback USD nominal/max |
| --- | ---: | ---: | ---: | ---: | ---: |
| A300 | 3,600 | 14,400 | 48,100 / 96,200 | 203.174400 / 406.348800 | 40.6348800 / 81.2697600 |
| A200 | 2,400 | 9,600 | 32,100 / 64,200 | 135.590400 / 271.180800 | 27.1180800 / 54.2361600 |
| A140 | 1,680 | 6,720 | 22,500 / 45,000 | 95.040000 / 190.080000 | 19.0080000 / 38.0160000 |
| A100 | 1,200 | 4,800 | 16,100 / 32,200 | 68.006400 / 136.012800 | 13.6012800 / 27.2025600 |

At concurrency 32, idealized receiver service times (excluding all local execution, scheduling,
cache, and report overhead) are:

| Design | 1 s nominal/max | 5 s nominal/max | 30 s nominal/max |
| --- | --- | --- | --- |
| A300 | 25m04s / 50m07s | 2h05m20s / 4h10m35s | 12h32m00s / 25h03m30s |
| A200 | 16m44s / 33m27s | 1h23m40s / 2h47m15s | 8h22m00s / 16h43m30s |
| A140 | 11m44s / 23m27s | 58m40s / 1h57m15s | 5h52m00s / 11h43m30s |
| A100 | 8m24s / 16m47s | 42m00s / 1h23m55s | 4h12m00s / 8h23m30s |

The 12-hour wall cap supersedes the attempt ceiling. A300 cannot guarantee exhausting even its
nominal requests if every attempt reaches 30 seconds, and cannot exhaust the retry ceiling under
that condition. Any later manifest must state this truncation explicitly rather than presenting
96,200 attempts as simultaneously guaranteed. Total wall runtime is not identifiable before a
provider latency/capability check and local orchestration benchmark; the table is an exact
parameterized receiver-service envelope, not a fabricated total-runtime forecast.

## 11. Prohibited analyses and claims

- No Model-B input, refit, or interpretation.
- No treatment tuning, threshold change, prompt change, receiver switch, subgroup selection, row
  replacement, or estimator change after outcomes.
- No population-valid e-process claim beyond the stated fixed Model-C-relative conditional null.
- No causal language claim before receiver certification and the authorized payoff study.
- No claim that synthetic output, a passing pipeline test, episode count, or API call count is
  scientific evidence.
- No competition, leaderboard, deployment, or live-performance claim from this study.
