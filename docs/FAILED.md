# Failed and retracted approaches

Append-only record. Do not delete old entries when later evidence changes the interpretation;
append a correction and update `docs/REGISTRY.md` instead.

## Treating the live bargaining role split as a role-policy defect — rejected

- In the strict 75-game batch bargaining player 1 averaged .314893 (n=12) and player 2
  .557605 (n=13), but role detection and action serialization were exact on every captured
  callback.
- The cells are not comparable: all 12 player-1 games were complete-information, versus only
  6/13 player-2 games, and only two observable exact-config strata contained both roles.
  Historical real games have a much smaller effect in the opposite direction (player 1
  .45485 versus player 2 .42889).
- The offline sampler chooses the candidate role uniformly and preserves player 1 as the
  first proposer. The live batch was nearly balanced by role, but matchmaking did not balance
  configurations or opponents within role.
- Therefore a role-specific bargaining policy is killed. A materially new retry needs matched
  role cells with adequate overlap; tuning to these 12/13 confounded games is not permitted.
- Independent correction: the next balanced 25-game bargaining batch produced player-1
  .382355 (n=12) and player-2 .386329 (n=13). The large earlier split did not replicate, which
  strengthens the rejection rather than opening a new role-policy family.

## Turning off bargaining theory or adding a stagnation acceptance override — rejected

- Across 61 authoritative bargaining games, theory-on and the old flat policy disagree on 100
  of 237 candidate decisions. Taking only the first theory-reject/flat-accept opportunity per
  game, immediate acceptance would add .294986 total, only **+.004836 per 61 games**; four
  games improve and seven regress. This one-step hindsight diagnostic is below the ordinary
  effect floor and is not trajectory-causal.
- The narrowed production-visible proposal, `own_delta=.8` plus two opponent offers whose
  retained share stagnates or hardens, reaches only two games. Their immediate-accept-minus-
  actual-terminal effects are −.0842 and +.0862. A matched non-stagnating game reverses the
  proposed direction, and allowing one point of concession yields four games averaging −.0325.
- Therefore neither a global theory-off change nor a low-delta stagnation override has a stable
  real mechanism. A materially new retry needs prospectively supported reach and sign across
  matched delta/round/horizon/role/config cells under the corrected opponent simulator.

## Attributing the full bargaining gap to the opponent timing-unit defect — rejected

- The defect is exact: fitting measures concession between successive offers by the same role,
  while the old runtime multiplied it by global `round-1`, doubling the rate by that role's
  second offer and adding an unfitted `.05*round` acceleration for conceding opponents.
- It is not the whole live explanation. The two clearest patient/stagnant games account for
  about .0152 of the .0776 pooled live/offline gap, roughly 20%. A separate non-gate n=100
  holdout diagnostic reached no timing-divergent realized trajectory and left the theory effect
  unchanged at +.06897.
- The simulator correction was nevertheless required for evidence fidelity and subsequently
  passed both its preregistered gate and independent confirmation. Do not convert a corrected
  evaluation model into a claim that production policy caused, or now fixes, the full live gap.

## Assuming live text persuasion carried the simulator's structured stance — rejected

- Across the complete confirmation and strict-volume logs, the candidate was buyer for 180
  text turns in nine games and declined 180/180. The raw corpus contains 101 unequivocally
  positive and 79 unequivocally negative messages across 16 repeated templates.
- The production mechanism is exact: live translation records non-`yes`/`no` text as a
  message with `buy_no_buy=None`; the buyer then finds no recommendation and defaults to no.
  Binary games are healthy: 101 purchases in 240 rounds, all after a yes recommendation.
- The fitted simulator hides this defect by attaching the seller's latent `buy_no_buy` value
  to text. A normal gate on that representation would be falsely inert, so the prospectively
  declared gate must use a live-contract text path with no hidden structured stance.
- Declined-round quality is not observable, so these logs prove a parsing defect but do not
  prove that every missed positive message was truthful or quantify counterfactual payoff.

## Promoting the first conservative text-stance parser — rejected by the normal gate

- The prospectively frozen 420-turn replay passed: all 180 directional text messages were
  classified with zero polarity errors (101 positive/79 negative), every raw message was
  preserved, all 240 binary actions were unchanged, and 84 text actions reached the candidate.
- The live-contract simulator gate used seed 314159, n=1600, a model-held-out opponent
  population and config-held-out catalogue. It measured +0.1390 mean payoff (t=13.04),
  241 wins, 12 losses and 1,347 ties; all 16 opponent archetypes were nonnegative.
- It nevertheless failed the mandatory config-regime concentration check: the largest regime
  supplied 0.5437 of positive gain, above the 0.50 ceiling. The default therefore remains off,
  no confirmation is declared, and no post-fix rated batch is permitted for this candidate.
- The first sandboxed execution completed simulation but could not create the artifact
  directory and exposed no verdict. The recorded result is the identical seed/sample rerun
  with output permission; it is not a statistical retry.
- A materially new retry must be declared before evaluation and explain why the change is not
  merely concentrated in high-prior text regimes. Re-gating the unchanged parser, changing
  subgroup definitions after seeing this result, or invoking the construction-defect
  minimum-effect amendment is not allowed: minimum effect passed and concentration failed.

## Attributing the live negotiation shortfall to a known rejected flag — rejected

- The complete terminal-capture scope is 35 games: 20 provable gains-from-trade games averaged
  .147313, one provable no-trade/equality game scored .037752, and 14 incomplete-information
  zero-payoff games have an unrecoverable hidden counterpart value.
- Because those 14 games include all nine candidate walkaways and five horizon no-deals, the
  true no-trade outside-option rate is not point-identified. Calling all 14 no-trade gives a
  9/15=60% sensitivity case, not an estimate comparable to offline 86% or real-population 88%.
- `guarantee_own_margin` has no realized harm signature: 20/20 candidate opening offers and
  21/21 accepted candidate outcomes retained positive margin. All 85 reached rejection
  counterprices came from the adapter fallback, but every fallback also retained positive
  margin. The missing plumbing is real; a payoff benefit is not established.
- The unbounded 50-callback 6800 repetition is reproduced, while capped games show the repaired
  adapter fallback conceding over time. This proves the old unknown-horizon static path remains
  reachable, not that the rejected `use_time_concession` flag would improve it. Counterpart
  de-biasing is truth-checkable in only one complete-information seller case, which matches the
  existing 1.50 markup prior.
- Therefore none of the three flags or their rejected combination gets a new gate, retry or
  status change from this batch. A materially new candidate requires the hidden true-zone
  problem to be resolved or a directly observed harmful action mechanism.
- Correction after the next complete batch: the pooled corpus is 60 games, with 37 known-GFT
  games averaging .127264, two known no-trade/equality games averaging .031414, and 21
  hidden-zone zero outcomes. The no-trade explicit-outside rate remains unidentified: its
  sharp sample bound is 0%--84.62% (11/23 only under the unsupported assumption that every
  hidden game is no-trade). The new logs did reveal a different, directly harmful action
  mechanism at the unknown-horizon adapter boundary; it was isolated and rejected by its own
  prospectively declared gate below, not used to revive these three flags.

## Treating four live boundary responses as a new zero-gain acceptance rate — rejected

- The released-data calculation reproduces the load-bearing statistic: exact zero gain accepts
  2,130/6,849=.3110; the response-model [0,.05) boundary bucket accepts
  2,794/8,471=.3298, consistent with the documented approximately .34.
- Complete live logs contain only four observable boundary responses across three games:
  zero accepts, two reject/counter actions and two outside-option walkaways. Its interval is
  wide enough to contain .34; after all three complete batches, 210/446 live responses cannot
  be binned because the responder's
  private value is legitimately hidden.
- The 0/4 point estimate is therefore underpowered evidence, not a replacement constant or a
  diagnosed policy mechanism. Outside-option actions remain failures in the denominator, as
  they were in the fitted response model.

## Treating SDK `max_games` as a strict total-game cap — rejected assumption

- The authorized confirmation invoked `--max-games 12`, but the SDK stopped after 15 games
  ending on our submitted move and the terminal capture found 31 distinct completed games.
- The SDK counter does not count games ending on an opponent move, and concurrency can overshoot
  even its own terminal-move count. Therefore `max_games` is not a safe expression of a strict
  user-authorized total-game limit.
- No further live games are authorized. Before any future run, the wrapper needs a strict cap
  whose accounting includes opponent-ended games; merely reducing `max_games` is not a proof.
- Correction: the repository wrapper now uses bounded one-game-per-family waves, counts unique
  IDs, and drains each wave before queueing the next. A focused test proves an eight-game cap
  queues exactly eight balanced/rotating games. The upstream SDK assumption remains rejected.

## Attributing confirmation-vs-offline payoff gaps to policy regression — rejected claim

- The complete 31-game confirmation measured bargaining 0.383075 and persuasion 0.235000,
  below section-4 offline means, but its n=11/n=10 intervals included the offline targets.
- A strict 75-game rated-volume run did not reproduce the large gaps: bargaining was 0.441103
  and persuasion 0.382000 on 25 games each, only −0.043897 and −0.017300 from offline.
- A second strict 75-game run also completed 25 per family: bargaining .384421 and persuasion
  .525600. Bargaining's interval again contains the offline .4850 target; persuasion moved
  above its .3993 target. Its bargaining role means were nearly identical (.382355/.386329),
  and its persuasion seller/buyer split narrowed to .567857/.471818.
- The samples are not distribution-equivalent. Live bargaining role cells differ sharply
  (player 1 .3149, player 2 .5576), and live pot frequencies differ from the fitted catalogue.
  Live persuasion seller games averaged .5292 while buyer games averaged .2462.
- A real simulator-alignment mechanism remains: live buyer-role persuasion purchased only
  61/260 rounds (23.5%) versus the offline documented 49.94%; fitted persuasion opponents use
  fixed trust/current stance and do not model language content or sampled memory. This warrants
  measurement/replay work, not an ungated policy change or more seed retries.

## Deriving complete live payoff from pre-action observations — rejected measurement

- `reports/live/observations.jsonl` records strategy callbacks before our action. It contains
  1,423 turns and 109 game IDs, but no authoritative `game_over`, result, or terminal payoff.
- A conservative reconstruction recovers 47 terminal economic outcomes and leaves 62
  indeterminate because the opponent's terminal response or the current persuasion quality is
  never followed by another callback. Only 40 have the exact local normalization inputs.
- Computing family means from the reconstructible subset is rejected: terminal-mover selection
  makes that subset non-comparable to the unconditional offline means in HANDOVER section 4.
  Coercing indeterminate games to zero is also rejected.
- Fix: `live-episodes` emits explicit reconstructed/indeterminate audit rows, and future runs
  capture SDK move responses and GET-backfill opponent-ended games. Exact historical comparison
  still requires an authoritative terminal-result export for this already completed batch.

## Attributing the remaining live persuasion buyer shortfall to a non-parser policy — rejected

- Across all 60 terminal-complete persuasion games, buyers purchased 164/620 rounds overall.
  The aggregate is entirely message-channel composition: binary buyers purchased
  164/320=.5125, matching offline .4994, while text buyers purchased 0/300 on the already-known
  missing-stance path.
- Binary yes-obedience was 164/209=.7847, matching the fitted population's .78; every one of
  111 binary `no` recommendations was declined. Binary buyer payoff was .590 versus binary
  seller .480, so the aggregate seller/buyer deficit reverses once message mode is held fixed.
- Apparent informedness/honesty differences collapse within exact `p/v` cells. `c` is always
  zero in these buyer games, every live history grows persistently from 0 through 19, and no
  production-visible `is_myopic` field exists. There is no supported myopic or role-specific
  acting branch to repair.
- Do not open a new buyer-policy family from 164/620 or the pooled role means. Materially new
  work requires a residual within matched binary `p/v`/history cells, or a parser mechanism
  that prospectively addresses the prior candidate's config-concentration failure.

## Missing persuasion values coerced to zero coverage bins — rejected keying

- `_coarse_config` used `as_float(value) or 0.0`, so an uninformed seller with hidden `v/c`
  could alias a real configuration whose values were numerically zero.
- Whether this affected the 109-game batch is inconclusive: the batch has no launch manifest,
  `run_summary.json` records no environment, and current or shell-history state cannot prove the
  completed process's `GLEE_SUPPORT_INDEX` setting.
- Fix: optional persuasion values retain a distinct missing value in coarse keys. A regression
  test proves that hidden values fall back to the family/role/round support bucket rather than
  resolving a populated real-zero coarse bucket. Future launches record support-index presence,
  resolved path, existence, and SHA-256 in `launch_manifest.json`.

## Unconditional live persuasion `u/v` requirement — rejected contract

- The docs-derived contract required buyer utility values on every persuasion turn. Fifty real
  games produced 120 alerts (240 missing-field reports), initially suggesting renamed server
  fields.
- Raw payload inspection contradicted that diagnosis. The alerts are exactly six games x 20
  seller turns, every one with `is_seller_know_cv=false`; no alternate key or nested location
  exists. The server intentionally withholds the buyer's `u/v` from an uninformed seller.
- The policy received normalized defaults (`v=1.2`, `c=0.0`) in its internal beliefs because
  those values were unknowable. The direct seller rule and persuasion response-model keys do
  not read them. However, they are not structurally unreachable: when `GLEE_SUPPORT_INDEX` is
  active, context coverage keys include persuasion `v/c`; coverage changes counterfactual
  uncertainty and can change SAFE/EXPLORE/EXPLOIT mode, and the late low-quality recommendation
  branch reads that mode. The live log does not record whether this environment-gated index was
  active. All 120 statuses were `ok`, with no fallback or timeout, and the contract correction
  itself changes validation only. Therefore there is no demonstrated action/rating harm from
  the false alerts, but the stronger claim of provably zero decision impact is retracted; exact
  terminal ratings and the coverage-mediated counterfactual are not reconstructible from this
  turn log.
- Fix: conditional visibility is now part of the contract. `u/v` remain mandatory for buyers
  and informed sellers, but are optional for uninformed seller-message/recommendation turns.
  Replaying all 1,423 captured payloads now yields zero violations.

## Persuasion cold-start exploration — rejected

- Tried: unconditional exploration; exploration only at zero evidence; exploration only when
  there is no transcript channel.
- Exact failures: unconditional concentration 0.649 and breadth 0.625; zero-evidence effect
  +0.0032; no-transcript effect +0.0051, t=+3.36, concentration 0.627, breadth 0.5.
- Materially new retry: must change the learning mechanism or target population, not merely
  rerun one of these candidates with a new seed.

## Persuasion Platt recalibration — rejected

- Tried: a single prospectively declared two-parameter Platt map fitted on model-FIT real
  decisions, applied only to post-yes buyer decisions behind `use_persuasion_platt=False`.
  Predictive evaluation had improved clustered Brier and log loss on both model and config
  holdouts before the acting candidate was defined.
- Exact payoff failure: paired structural holdout seed 271828, n=1600, effect +0.0057,
  t=+5.07, 84W/44L/1472T. It passed significance, downside, structural holdout, subgroup
  concentration, and subgroup breadth, but failed the non-waivable `minimum_effect` threshold
  of 0.0100. Level-2 (-0.0037) and deceptive (-0.0016) archetypes regressed.
- Materially new retry: must change the mechanism or prospectively target a population already
  justified by pre-gate calibration evidence, while explicitly addressing the dishonest-seller
  regressions. Do not rerun this global map with another seed, and do not treat predictive
  calibration success as payoff promotion evidence.

## Deceptive-seller lower-confidence guard — rejected

- Tried: for persistent buyers after at least one visible prior yes-on-low lie, replace the raw
  purchase posterior with a one-standard-deviation lower bound. The rule was default-off,
  isolated from Platt recalibration and exploration, and declared before its payoff run.
- Pre-gate evidence: exact-stratum observational contrasts on both structural holdouts showed
  overconfidence and worse one-step realized purchase surplus after prior lies, with 18.9-19.4%
  conservative effective reach. This established a measurable association, not a trajectory
  effect.
- Exact payoff failure: seed 161803, paired structural holdout n=1600, effect -0.0052,
  t=-5.40, 9W/61L/1530T. It failed `minimum_effect`, significance, archetype breadth 0.9375,
  and config breadth 0.5000. Every persistent regime lost; myopic regimes were unchanged.
- Materially new retry: must explain the reversal between one-step observational association
  and simulated trajectory payoff, rather than tuning the confidence multiplier or rerunning a
  new seed. The same blocking mechanism is not eligible for another gate.

### Diagnostic correction: why the guard was net negative

- A fresh replay of the exact seed-161803 gate found 401 changed buyer decisions, all
  baseline-buy to guard-decline. Of those, 309 were high-quality purchases with positive
  realized surplus and only 92 were low-quality purchases with negative surplus; mean blocked
  surplus was +0.4121.
- The persistent posterior already estimates this seller's `P(yes|high)` and `P(yes|low)` from
  visible within-game history. The lower-confidence penalty reused that lie evidence and
  double-penalized the posterior, systematically rejecting valuable trades.
- The loss is not a hidden myopic subgroup: myopic games were unchanged and every persistent
  message/prior regime was negative. A materially new retry must estimate informedness and
  honesty separately and make a calibrated state-dependent decision.

## Broad per-game persuasion honesty tracking — narrowed

- Persistent buyers benefit from seller-specific visible history on both structural holdouts,
  but myopic buyers observe purchased-product aggregates rather than recommendation truth.
- Against a cross-fit population baseline, the shipped per-game estimate improves Brier by
  0.02968/0.03510 for persistent buyers (model/config holdouts) but worsens it by
  0.01144/0.00828 for myopic buyers.
- The broad hypothesis is rejected. Future work may retain seller-specific honesty state only
  where truth is observable and must shrink myopic recommendation weight toward a fit-only
  population/config prior.

## Direct seller archetype targeting — rejected

- The production state does not expose the fitted opponent archetype label. The current seller
  already adapts to observable within-game receiver obedience through its evidence/control
  logic.
- Fitted archetypes differ in stipulated trust priors, but unavailable labels do not establish
  an implementable targeting mechanism. Do not add a policy family until a production-visible
  signal predicts a stable holdout response difference beyond the existing obedience estimate.

## Negotiation time concession — rejected

- Tried: Boulware time-dependent concession in place of the mostly round-independent offer.
- Exact failures: first defective candidate -0.0054, t=-7.57, including
  `rounds=1|gains_from_trade` at -0.0447; corrected candidate +0.0003, t=+2.11,
  6W/76L/1518T over n=1600, below the 0.0100 minimum effect.
- Materially new retry: must address reach or mechanism beyond the corrected curve; a new seed
  alone is not new.

## Unknown-horizon counter fallback concession — rejected

- Tried: on the proven live-adapter branch where a negotiation rejection had no supplied
  counter-price and the horizon was hidden, preserve a positive own margin, never worsen the
  candidate's last own offer, and concede by the fixed preregistered schedule
  `max(0.02, 0.15 * 0.99 ** (round - 1))`. A live-contract simulator hid the sampled terminal
  cap from both arms and treated rejection counter-prices as the next offer.
- Material difference from the prior rejected policy time-concession and combined paths: this
  acted at the adapter fallback boundary those policy curves never reached. Real evidence was
  `f29a…`, where a seller opened at 16950 before the fallback raised all 49 counters to 17250.
- Exact failure: config structural holdout seed 8675309, n=1600, effect +0.0003, 95% CI
  [+0.0000,+0.0006], t=1.9644, 4W/0L/1596T. It failed `minimum_effect` and
  `subgroup_concentration[config_regime]` at 0.5980; sample size, significance, downside,
  structural holdout, both breadth checks, and archetype concentration passed.
- Materially new retry: must change the response mechanism or prospectively target a
  production-visible population with demonstrated counter acceptance; do not tune the decay
  constant or rerun this fallback schedule on another seed.

### Branch-conditional eligibility audit — ineligible, not run

- New reach evidence found the adapter fallback on 193/193 relevant live rejection responses.
  That does not turn reach frequency into payoff evidence or waive the amendment's eligibility
  requirements.
- The immutable baseline predicate and the `16950 -> 17250` seller example support a logical
  no-worsening defect, but the unchanged candidate is not the smallest invariant repair:
  `max(0.02, 0.15 * 0.99 ** (round - 1))` adds a chosen concession schedule beyond simply
  clamping the fallback to the last own offer.
- Independently dispositive, the ordinary seed-8675309 gate failed config-regime concentration
  at **0.5980 > 0.50** as well as `minimum_effect`. Amendment eligibility condition 4 requires
  every ordinary non-effect check to pass. Therefore no branch-conditional predicate/seed/n was
  declared, no evaluation or confirmation ran, and the default remains false. A retry requires
  a materially new smallest fix and a fresh prospective ordinary gate; the 193/193 observation
  is not permission to reuse the rejected evaluation.

## Negotiation own-margin offer clip — rejected

- Tried: guarantee our own margin and attach the agent's counter price only while that
  guarantee is active.
- Exact failure: +0.0076, t=+9.46, 117W/0L/1483T over n=1600; failed only
  `minimum_effect` (0.0100 required).
- Materially new retry: requires a prospectively defined gate-policy decision and a changed
  candidate or endpoint declared before measurement. Retrospectively conditioning on the 117
  reached pairs is not valid.

### Construction-defect conditional re-gate — confirmation failed

- After the permanent criteria amendment was committed, the prospectively declared seed-4242
  conditional gate reached 1,068 baseline pre-state branch pairs and passed: +0.0102835,
  t=8.77, 96W/0L/972T, with zero regressing archetype/config subgroups.
- The independent seed-104729, n=3200 confirmation was declared before execution. Its ordinary
  effect was +0.0071239 with config concentration 0.5620. The identical conditional predicate
  reached 2,155 pairs at +0.0091320, t=11.40, 166W/0L/1989T.
- Confirmation therefore failed both ordinary concentration and conditional minimum effect.
  Zero losses and zero regressing conditional subgroups were not enough because every declared
  condition was mandatory. The family returns to `candidate`; no seed retry is permitted.

## Negotiation counterpart-value de-bias — rejected

- Tried: correct first asks by measured 1.50x seller markup and first offers by measured 0.75x
  buyer shading.
- Exact failures: +0.0072, t=+7.52, 64W/1L/1535T over n=1600; `minimum_effect` and
  `subgroup_concentration[config_regime]` 0.5951 (maximum 0.5000).
- Materially new retry: must reduce configuration concentration or change the inference model;
  rerunning the same constants is not new.

## Combined negotiation counteroffer path — retracted

- Tried: time concession, own-margin guarantee/counter-price, and counterpart-value de-bias as
  the single coupled mechanism they were diagnosed to be.
- Exact evidence: initial gate seed 4242, n=1600, +0.0109, t=+10.07, 136W/42L/1422T,
  concentration 0.4985, passed. Independent confirmation was declared before execution at
  seed 9999, n=3200; it returned +0.0094, t=+12.49, 233W/94L/2873T and concentration 0.5539.
- Why retracted: confirmation failed `minimum_effect` and concentration, so the initial
  marginal pass cannot support shipping.
- Materially new retry: a changed mechanism with a new preregistered hypothesis; never submit
  the unchanged candidate to another seed hoping for variance.

## One-shot empirical joint opponent bundles (Model B v2) — retracted

- Tried: replace stipulated independent parameter quantiles with one empirical
  `(player_model, config_id, role)` parameter bundle sampled through a canonical exact/coarse/
  role ladder. Parameter units, actor/config structural splits, policy defaults and the
  same-support conditional-shuffle comparator were frozen before holdout scoring.
- Model-axis failure: the 25% actor split contained only four held-out actor-model clusters in
  every family, below the prospectively required five, so no family was reportable. Bargaining
  retained 9,928/14,602 eligible games (.6799); negotiation 7,195/14,417 (.4991); persuasion
  1,174/5,800 (.2024). The latter two also failed the 50% coverage floor.
- Config-axis failure: bargaining and negotiation were reportable, but preserving whole-bundle
  dependence made the primary energy score significantly worse than independently shuffling
  parameters inside the identical conditional pool. Bargaining joint-minus-shuffle was
  +0.003458 with 95% CI [+0.002525,+0.004512]; negotiation +0.001593 with
  [+0.000703,+0.002490]. Both were much better than the old v1 operational sampler, showing
  that config conditioning/marginal repair helped while the claimed joint dependence did not.
  Persuasion retained only 1,192/3,185 eligible games (.3743) and was unreportable.
- The exact formulation is retracted and may not be retried with a new seed, relaxed cluster or
  retention threshold, or pooled in-sample rows. Closest earlier failure was attributing a
  live/offline gap to independently sampled marginals; this validation isolates and rejects the
  stronger claim that raw exact-segment bundles improve joint out-of-sample prediction.
- Materially new retry condition: exhaustive out-of-fold prediction over all actor identities
  and canonical configurations, plus decision-level hierarchical response estimates that cure
  sparse per-segment crossings without importing held-out outcomes. This is declared separately
  in REGISTRY before fitting; it must still beat the same-support conditional shuffle, not only
  the defective v1 sampler.

## Four-by-four exhaustive cross-fit manifest — retracted before fitting

- Declared: four actor folds of four identities and four canonical-config folds, with the full
  predictive and decision-level endpoints frozen before artifact fitting.
- Mandatory pre-fit kill-check: the memory-safe full-corpus manifest scan found exactly **15**
  acting-model identities. It stopped before actor fold 0 with
  `actor cross-fit requires exactly 16 identities, found 15`; no fold artifact, holdout score,
  payoff tournament, candidate gate or live game was produced.
- Why this is a failure rather than a silent repair: balanced 4/4/4/4 actor folds, .25 actor
  holdout fraction and >=3 clusters in every one of four actor folds were explicit prospective
  conditions. Relabeling or duplicating an identity would invent support; relaxing the count in
  place after the scan would change the declared structural estimand.
- Materially new retry: a per-axis manifest with three actor folds of the actual 15 identities
  (5/5/5, each evaluated once) and four canonical-config folds. That changes the fold/provenance
  contract and training population while preserving every predictive threshold. It is declared
  separately in REGISTRY before code changes or fitting.

## Diagonally scaled response-gradient solver — instrument retracted before scoring

- The first mixed-fold FIT artifact completed on actor fold 0, but bargaining, negotiation and
  persuasion all reached the fixed 300-iteration ceiling with `converged=false`. The fitting
  campaign stopped during fold 1 before any cross-fit validation, payoff tournament or policy
  gate. The partial artifact is not predictive evidence.
- Mechanism: each model/config offset was updated by its small local gradient divided by the
  global row count. Sparse offsets therefore moved orders of magnitude too slowly even though
  identical response rows were aggregated. Raising the iteration ceiling or loosening the
  convergence flag after observing FIT would change the instrument without solving that scaling
  defect.
- Permitted repair: preserve the identical penalized logistic objective, fixed ridge grid,
  outer/inner folds, slope constraint and convergence tolerance, but solve it with per-coordinate
  curvature and a deterministic descent safeguard. Require small-fixture objective equivalence,
  raw/aggregated equality, deterministic coefficients, and demonstrated convergence before the
  unchanged full fit restarts. No holdout result may inform the repair.

## Diagonal-Newton response solver — instrument retracted before fold completion

- Closest prior entry: the globally scaled response-gradient failure immediately above. The
  diagonal-curvature formulation was materially new as a numerical instrument, but it preserved
  the same penalized-logistic objective, ridge grid, folds, monotone slope, iteration ceiling and
  tolerance. It was therefore eligible for a FIT-only convergence preflight, not a changed
  predictive endpoint.
- Kill-check: 10/10 deterministic, nonseparable mixed model/config fixtures failed to converge in
  300 iterations, with final coordinate changes roughly `3e-5` to `3.5e-4`, well above the frozen
  `1e-7` tolerance. Ignoring intercept/model/config Hessian cross-terms did not cure the actual
  geometry that stalled the first corpus fit.
- A second correctness defect made apparent passes unsafe: convergence used only accepted step
  size. Extreme backtracking could accept an effectively stationary step and set
  `converged=true` even with a large projected gradient. Inner-CV ridge selection also admitted
  nonconverged fits. Objective history and a diagnostic gradient were serialized, but neither
  constrained artifact acceptance.
- The full-corpus rerun was interrupted during actor fold 0 as soon as the adversarial preflight
  returned. It completed no new fold artifact and produced no holdout score, tournament, policy
  gate or live game. Commit `888bf95` is retained as an auditable failed instrument checkpoint,
  not accepted evidence.
- Materially new repair: keep the exact declared statistical objective and data split, but use an
  identifiable/full-curvature or coordinate solver with a projected-KKT stopping rule; mark
  line-search stagnation nonconverged; serialize stop reason/damping/backtracks/stationarity; and
  make every inner-CV fit converge before its ridge is eligible. Raising iterations, loosening
  tolerance or trusting a small step alone is not an allowed retry.

## Sparse coordinate-Newton response solver — instrument retracted after FIT-only fold 0

- Closest prior entries: the global-gradient and diagonal-Newton numerical failures above. This
  retry was materially new because it updated coupled intercept/model/config coordinates
  sequentially, enforced a final projected-KKT certificate, rejected line-search stagnation,
  and made a ridge ineligible if any inner fold failed. It kept the exact penalized-logistic
  model, response rows, ridge grid, inner/outer folds, 300-sweep ceiling, slope bound and
  `1e-7` stationarity tolerance.
- Kill-check: actor fold 0 completed, but bargaining, negotiation and persuasion all serialized
  `status=unavailable` / `no_ridge_with_all_inner_folds_converged`. Across the 36 family/ridge/
  inner-fold fits, none produced an eligible ridge. Failures were either the 300-sweep limit or
  explicit line-search stagnation. The smallest residuals were still approximately `.00237`
  (bargaining ridge 100), `.00303` (negotiation ridge 100) and `.34015` (persuasion ridge .1),
  with several residuals above 1. The artifact therefore fails its own stationarity contract.
- The fitter advanced to actor fold 1 only after atomically writing fold 0; it was interrupted
  immediately after the fold-0 audit. No fold-1 artifact, cross-fit holdout score, tournament,
  policy gate or live game was accepted. The 176 MB fold-0 file is FIT-instrument evidence only.
- Mechanism: exact coordinate descent handles coupling eventually but the intercept/model/config
  system is ill-conditioned; 300 sweeps are insufficient for weak ridges, while local objective
  comparisons hit floating-point stagnation before the absolute raw-gradient tolerance for
  stronger ridges. This is a solver failure, not a predictive failure of Model B.
- Materially new repair may use a deterministic global Hessian-vector/Newton-CG, block-IRLS or
  identifiable reparameterization that solves the coupled system directly. It must preserve the
  frozen statistical objective and `1e-7` projected-KKT contract. Merely increasing sweeps,
  weakening tolerance, accepting relative gradients, or scoring the unavailable artifact is
  forbidden.

## List-materialized stable summation in Newton-PCG — instrument retracted before artifact write

- Closest prior entry: the sparse coordinate-Newton numerical failure above. The zero-sum
  Newton-PCG solver was materially new and passed dense-Hessian, PCG, projected-Armijo,
  raw-coordinate KKT, multi-channel and failure-path preflights. Its statistical model and
  validation contract remain eligible; this entry concerns only the corpus implementation's
  peak-memory complexity.
- Kill-check: the preregistered actor-fold-0 run stayed in its first fold and was terminated by
  the OS with exit code 137 after sustained computation. It printed no Python exception and did
  not advance to fold 1. The existing `actor_fold_0/opponent_population.json` retained timestamp
  `2026-08-15 23:52:36` and is the already-rejected coordinate-solver artifact, so the PCG run
  wrote no new fold and produced no holdout score.
- Mechanism: stable objective/gradient/HVP/raw-KKT evaluation collected every row contribution
  in per-coordinate Python lists before `math.fsum`. Repeated PCG Hessian-vector products thus
  allocated large nested lists at corpus scale, and zero-sum last-level contrasts made some rows
  dense. This makes peak memory grow with nonzero row-feature contributions instead of only the
  coefficient dimension.
- Materially new repair: replace term lists with deterministic compensated streaming
  accumulators (or fixed-size pairwise blocks) shared by production and tests. Require dense/
  fsum agreement to at least `1e-12` on adversarial cancellation, identical convergence/status
  on existing fixtures, and a memory-scaling test proving accumulator storage is O(parameters)
  rather than O(row-feature nonzeros). The statistical objective, folds, ridge grid, PCG forcing/
  cap/shifts, Armijo constants, 300 outer limit and raw KKT `1e-7` may not change.

## Repeated response-audit serialization after Neumaier repair — instrument retracted before artifact write

- Closest prior entry: the list-materialized stable-summation failure immediately above. That
  failure occurred inside repeated numerical evaluation because row contributions were retained
  in temporary lists. The materially different post-Neumaier attempt used shared fixed-state
  compensated accumulators, so objective, gradient/HVP and raw-KKT accumulation no longer grew
  with row-feature contributions; this failure exposed artifact object ownership and recursive
  serialization instead. The estimator, folds, ridge selection and Newton-PCG contract did not
  change.
- Kill-check: the repaired, preregistered actor-fold-0 FIT-only process was terminated by the OS
  with exit code 137. It wrote no new actor-fold-0 artifact and produced no holdout extraction,
  predictive verdict, payoff tournament, policy gate or live game. In particular, termination is
  not evidence that any family fit converged or passed its KKT contract.
- Mechanism identified by the post-run serialization-path audit: every retained bundle response
  parameter embedded the family's complete final audit and all ridge-by-inner-fold solver audits,
  including nested PCG shift attempts and Armijo histories. The same canonical family fit was
  also present at the artifact top level. Thousands of bundles therefore expanded a shared
  logical audit into a recursively serialized object graph many orders larger than its unique
  evidence content, while ordinary JSON construction/writing could additionally retain a whole
  tree and serialized copy concurrently.
- Materially new repair: normalize complete solver evidence to one canonical family audit and
  replace per-bundle copies with verified family/channel/fit references and parameter-specific
  metadata. Use an atomic streaming writer and release phase-local state only after its final
  consumer. Preserve every numerical record required by the declared independent validator;
  hashes alone may not replace auditable KKT/PCG/Armijo/CV evidence. The statistical estimator,
  solver, folds, ridge grid, endpoints and thresholds remain frozen. The prospective storage-only
  instrument is recorded in REGISTRY before implementation or another FIT attempt.

## Normalized Newton-PCG actor fold 0 — FIT instrument rejected

- Closest prior entries: the sparse coordinate-Newton convergence rejection and the two
  Newton-PCG memory failures above. Unlike either memory failure, this attempt completed and
  atomically wrote the normalized artifact; unlike coordinate Newton, Newton-PCG certified the
  bargaining and negotiation response fits. The exact declared all-family convergence and
  reference-integrity requirements nevertheless remained mandatory.
- Artifact: `models/opponent_population_model_b_crossfit/actor_fold_0/opponent_population.json`,
  63,070,064 bytes, SHA256
  `a6ac5e3b6873c99bfb6b538d33d864a0da45bb0d37a51d294ecdaad4371b0dae`.
- Numerical kill-check: bargaining and negotiation were KKT-clean. Persuasion was unavailable:
  `seller_high` ended with `line_search_stagnation` at original-coordinate projected KKT
  `2.132299274926197e-7`, above the frozen `1e-7` acceptance ceiling. A near miss is a failure;
  the passing families cannot waive the declared B/N/P all-pass rule.
- Construction kill-check: independent validation reported exactly 3,512 response-reference
  `parameter_presence` mismatches. This equals the artifact's 3,512 persuasion references, but
  equality alone does not authorize silently deleting the check or claiming a predictive result.
  Canonical parameter presence, support and reference attachment must be repaired and tested as
  one construction path.
- Fold 1 was stopped immediately after the actor-fold-0 rejection. No holdout extraction or
  score, predictive verdict, payoff tournament, policy gate, default change or live game occurred.
- Materially new retry must change the floating-point ambiguity mechanism and the reference
  construction, not loosen KKT tolerance, increase iterations, change the ridge grid/folds/seed,
  accept partial families, or retry the same line search. REGISTRY prospectively declares a
  fixed eight-ULP Decimal-Armijo ambiguity resolver and canonical source-of-truth attachment while
  preserving the statistical estimator and every predictive endpoint.

## Mixed-fold empirical-bundle Model B — predictive validation rejected

- Closest prior entries: `model_b_joint_opponents`, whose one-shot validation was
  unreportable on the model axis and failed the same-pool shuffle comparator on the config
  axis, and `model_b_crossfit_joint_opponents`, whose impossible four-by-four fold declaration
  was killed before fitting. This attempt was materially different: all 15 actor identities
  were evaluated exactly once through three actor folds, canonical configurations through four
  folds, all seven FIT artifacts were frozen, all 21 family fits were stationarity-certified,
  and the exhaustive holdout validator scored 69,440 raw bundles and 452,797 decisions on both
  axes.
- Artifact/instrument acceptance did not imply predictive acceptance. All seven routers,
  compact references and solver audits passed; worst final/inner raw KKT was
  `9.990772298351658e-08` under the frozen `1e-7` ceiling. The final validation report is
  `1,862,860,839` bytes with SHA256
  `1a86cac280b1cd6b0049bc9429a6662f9d33b754dcfb23b4044e5b04ebbdacec`.
- Primary joint-dependence kill-check failed decisively. Whole-bundle minus same-conditional-
  pool shuffled energy was positive on both reportable families and both axes: model
  bargaining `+.009718` with 95% CI `[+.008504,+.010911]`, model negotiation `+.005895`
  `[+.004780,+.006871]`, config bargaining `+.003199` `[+.002681,+.003684]`, and config
  negotiation `+.001164` `[+.000651,+.001675]`. The declared success condition required both
  mean and CI upper bound below zero. Persuasion was unreportable on both axes because only
  `4,464 / 13,506 = .330520` distinct games retained a supported two-parameter bundle, below
  the frozen `.50` floor.
- The decision-level hierarchical model is useful but cannot waive the family-level failure.
  All eight config-axis response cells passed, and bargaining/negotiation passed both model-axis
  roles. All four model-axis persuasion channels failed: buyer-no was worse than neutral in mean
  log loss (`+.004515`, CI upper `+.023229`); seller-low was worse than neutral (`+.111560`,
  upper `+.318440`); buyer-yes and seller-high failed the required v1 log-loss upper bounds
  (`+.024244` and `+.000891`). Partial response success is not validation of correlated latent
  parameter bundles.
- Consequence: no corrected-timing bargaining tournament comparison, negotiation candidate
  re-gate, confirmation, default change or live game was authorized by this result. In
  particular, `guarantee_own_margin`, `debias_counterpart_value`, `use_time_concession`, and the
  exact counteroffer-preservation repair remain at their prior statuses; a new population seed
  cannot make them eligible when the population itself failed its prerequisite.
- Materially new work must replace empirical segment-bundle resampling with a joint estimator
  whose dependence is learned and regularized separately from its conditional marginals and
  whose missing endpoints do not select only behavior-rich segments. It must retain the
  same-support independent conditional comparator, exhaustive actor/config OOF isolation and
  hard coverage rules. A new seed, relaxed coverage, dropping persuasion after seeing its
  failure, or merely keeping the successful response surface while calling it Model B is not a
  valid retry.

## Retracted claims from the 14 August session

### Frozen persuasion posterior guarantees zero payoff — retracted claim

- Contradicting evidence: across 13,506 real games, frozen bought in 67.0% of rounds versus
  60.6% informed; decisions agreed 80.1%; mean per-round EV forgone by freezing was +0.0286,
  meaning frozen was slightly better on net.
- Materially new retry: any severity claim must be evaluated against real logged decisions and
  distinguish an accessor defect from its payoff consequence.

### Static agent offer caused the live 6800 counteroffer — retracted claim

- Contradicting evidence: the agent did not attach a counter price, so the adapter fallback
  generated `8000 * 0.85 = 6800`; the proposed concession curve was unreachable from live play.
- Materially new retry: trace the production reader/adapter path end to end before attributing
  a visible live action to agent policy.

### Shrinking a lower evidence bound is conservative — rejected change

- Contradicting evidence: shrinking the lower bound restored an optimistic prior floor and
  broke `test_a_hidden_no_trade_zone_is_now_believable` in the 61% of real configurations with
  a no-trade zone.
- Materially new retry: preserve the direction of one-sided evidence bounds and validate the
  smallest no-trade example first.
