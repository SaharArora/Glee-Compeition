# Approach registry

Durable status for policy, scoring, and evidence work. Statuses follow
`docs/HANDOVER.md` §0.9 exactly: `candidate`, `gate-passed`, `confirmed`, `shipped`, or
`retracted`. A status never outruns the weakest supporting run.

| Family | Exact change | Remaining gap | Last gate/evidence | Status | Owner | Dependencies / shared surfaces | Evidence |
|---|---|---|---|---|---|---|---|
| `theory_anchor` | Bargaining offer policy uses the theory anchor by default. | None recorded. | Revalidated under corrected simulator: gate seed 112358 n=1600 +0.0551, t=10.95; independent confirmation seed 2718281 n=3200 +0.0601, t=16.77; every ordinary check passed. | `shipped` | none | Bargaining offer path. | `bargaining_opponent_timing_parity`; corrected gate/confirmation reports; `docs/PROMOTION_CRITERIA.md` |
| `bargaining_opponent_timing_parity` | Correct fitted bargaining `concession_rate` from global-round units to successive-own-offer units `(round-1)//2`, and remove the unfitted `conceding` `.05*round` acceleration. Audit theory-on against isolated theory-off under the corrected simulator; production theory default is unchanged. | No production policy changed, so the pre-authorized live candidate-confirmation condition was not reached and its one-batch authorization remains unconsumed. | Gate seed 112358 n=1600: +0.0551 (95% CI +0.0452 to +0.0650), t=10.95, 788W/355L/457T. Independent confirmation seed 2718281 n=3200: +0.0601 (95% CI +0.0531 to +0.0671), t=16.77, 1612W/703L/885T. Every ordinary check passed in both. Closest FAILED entries are the rejected live role-policy defect and rejected confirmation-gap attribution; material difference is a deterministic fit/runtime unit mismatch. | `shipped` | none | Shared `BargainingPolicy` and shipped `theory_anchor` evidence surface. No live policy or adapter change. | Declarations below; `reports/promotion/bargaining_theory_anchor_corrected_seed112358`; `reports/promotion/bargaining_theory_anchor_corrected_confirmation_seed2718281`; `glee_eval/opponents/policies.py` |
| `time_concession` | Optional Boulware time-dependent negotiation concession (`use_time_concession=False`). | Below minimum effect; offline population rarely reaches long negotiations. | +0.0003, t=+2.11, 6W/76L/1518T, n=1600; failed `minimum_effect`. | `candidate` | unassigned | Shared negotiation counteroffer path with `guarantee_own_margin` and `debias_counterpart_value`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2-§0.4 |
| `guarantee_own_margin` | Optional own-profitability offer clip and live `counter_price` plumbing (`guarantee_own_margin=False`). | Independent confirmation failed; no retry permitted and default remains false. | Gate seed 4242 conditional n=1068: +0.0102835, t=8.770, 96W/0L, passed. Declared confirmation seed 104729 n=3200: ordinary +0.0071239 with concentration 0.5620; conditional n=2155, +0.0091320, t=11.40, 166W/0L; failed conditional effect. | `candidate` | unassigned | Zero losses/regressing conditional subgroups held, but every declared check was mandatory. | `docs/PROMOTION_CRITERIA.md`; `docs/FAILED.md` |
| `debias_counterpart_value` | Optional correction of opening-price inference using measured median shading/markup (`debias_counterpart_value=False`). | Below minimum effect and too concentrated by config regime. | +0.0072, t=+7.52, 64W/1L/1535T, n=1600; failed `minimum_effect` and concentration 0.5951. | `candidate` | unassigned | Shared negotiation counteroffer path with `time_concession` and `guarantee_own_margin`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2/§0.5 |
| `combined_counteroffer_path` | Enable time concession, own-margin guarantee/counter-price, and value de-bias as one coupled mechanism. | Confirmation failed; do not rerun unchanged. A retry must be materially new. | Gate seed 4242: +0.0109, t=+10.07, n=1600, passed. Declared confirmation seed 9999: +0.0094, t=+12.49, n=3200, failed `minimum_effect` and concentration 0.5539. | `retracted` | unassigned | Owns the shared negotiation counteroffer surface; depends on `minimum_effect_policy`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.3 |
| `unknown_horizon_counter_fallback` | Default-off live-contract candidate for negotiation rejections where the agent supplies no counter-price and the horizon is hidden: never move farther from agreement than the candidate's last own offer, then apply a fixed `max(0.02, 0.15 * 0.99 ** (round - 1))` positive own-margin schedule. | Gate rejected; branch-conditional amendment ineligible, do not rerun unchanged, and keep default false. | Seed 8675309, n=1600 config structural holdout: +0.0003, t=1.9644, 4W/0L/1596T. Failed `minimum_effect` and config concentration 0.5980. A later 193/193 live fallback-reach finding does not cure amendment condition 4; the scheduled concession also exceeds the smallest invariant-restoring clamp required by condition 3. No conditional evaluation ran. | `candidate` | unassigned | Shares negotiation live adapter/counteroffer simulation; capped fallback, policy offer curve, value inference, and existing rejected flags remain unchanged. | `reports/promotion/unknown_horizon_counter_seed8675309`; `docs/FAILED.md` |
| `persuasion_explore` | Optional negative-EV purchase to break the no-observation cold start (`persuasion_explore=False`). | Need a materially new formulation that is not the three rejected variants. | Best formulation: +0.0051, t=+3.36, n=1600; failed `minimum_effect`, concentration 0.627, breadth 0.5. | `candidate` | unassigned | Persuasion buyer policy; coordinate with calibration/deceptive-seller work. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2 |
| `persuasion_accessor` | Read persuasion quality from the production transcript shape. | A separate uncertainty-aware deceptive-seller guard is proposed but remains hypothesis-only. | +0.0160, t=+7.25, n=1600; failed breadth 0.4375 and shipped under the documented defect carve-out. | `shipped` | none | Persuasion buyer posterior; coordinate any guard with calibration and exploration work. | `docs/PROMOTION_CRITERIA.md` |
| `persuasion_calibration_bins` | Optional default-off Platt map of `P(high|recommend=yes)` using model-FIT parameters `a=0.3651090145`, `b=1.1369808568`; apply only to the buy decision after a yes recommendation and retain raw posterior diagnostics. | Gate rejected; do not rerun unchanged. A retry must change the mechanism or prospectively target a justified population, and must account for shared deceptive-seller regressions. | Seed 271828, n=1600 structural holdout: +0.0057, t=+5.07, 84W/44L/1472T. Passed significance, downside, holdout, concentration, and breadth; failed only `minimum_effect` 0.0057 < 0.0100. Worst archetypes: level_2 -0.0037, deceptive -0.0016. | `candidate` | unassigned | Shared `_persuasion_beliefs`/buy path with `persuasion_accessor`, `persuasion_explore`, and deceptive-seller work. Default remains false; no confirmation declared or permitted. | `reports/promotion/persuasion_platt_seed271828/promotion_verdict.json`; `docs/FAILED.md`; `tests/test_persuasion_mechanics.py` |
| `deceptive_seller_guard` | Default-off persistent-buyer one-standard-deviation lower bound after a production-visible prior lie. | Rejected mechanism diagnosed: the shipped posterior already uses this seller's visible yes/high and yes/low history; the guard double-penalizes that evidence and blocks mostly profitable purchases. | Seed 161803: -0.0052, t=-5.40. Replay found 401 buy-to-decline changes: 309 high-quality/profitable versus 92 low-quality/loss-making, blocked mean surplus +0.4121. | `candidate` | unassigned | Default remains false; any revision must use the diagnosed state-dependent latent structure. | `reports/promotion/deceptive_seller_guard_seed161803/promotion_verdict.json`; `docs/FAILED.md` |
| `persuasion_memory_channel` | Diagnose seller-specific honesty history separately from myopic purchased-product aggregates. | Mechanism diagnosed; no acting fix declared. Persistent per-game history improves prediction, while treating myopic totals as honesty evidence worsens it. | 88,910 released yes decisions. Per-game versus cross-fit population Brier delta: model holdout -0.02968 persistent/+0.01144 myopic; config holdout -0.03510/+0.00828. | `candidate` | unassigned | Shares `_persuasion_beliefs`; future policy must be memory-mode specific. | Fresh diagnostic 2026-08-15; `docs/FAILED.md` |
| `persuasion_informedness_honesty` | Diagnose seller informedness and production-visible prior dishonesty as separate interacting latent effects. | Real mechanism diagnosed; not an acting policy. Any future candidate must be calibrated/state-dependent and newly gated. | Stable FIT-to-holdout log-odds: informedness +0.4085/+0.4254, prior lie -1.5267/-1.5613, interaction -0.4620/-0.4968 (model/config). Improved Brier, log loss, and ECE beyond Platt on both axes. | `candidate` | unassigned | Diagnostically supersedes blanket Platt/guard formulations. | Fresh diagnostic 2026-08-15; `docs/FAILED.md` |
| `message_mode` | Confidence/social-proof persuasion composer runs in shadow (`message_mode="shadow"`). | Simulator cannot test message text; requires non-circular real evidence. | Replacing text with `"."` changes simulated payoff by 0.000000. | `candidate` | unassigned | Live evidence only; no live games without per-instance user authorization. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.6 |
| `minimum_effect_policy` | Permanent rare-path conditional-effect amendment for changes proved defective by construction. | None; candidates still require prospective predicates, zero conditional losses/regressing subgroups, and independent confirmation. | Amendment committed before application as `87c688d`; unconditional gate remains authoritative for ineligible work. | `shipped` | none | Governance only; promotes no candidate by itself. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.7 |
| `live_schema_history` | Align fixtures/contracts/adapter with current glee-sdk `history` and persuasion `current_player` schema. | None recorded for these fields. | Fifty authorized real games produced 1,423 turns; captured payloads contain the documented history/current-player shapes and translated without fallbacks. | `shipped` | none | Continue monitoring real observations for new shapes. | `reports/live/observations.jsonl`; `tests/test_live_adapter.py` |
| `live_persuasion_value_visibility` | Require `u/v` only when visible: buyer turns and informed-seller turns; preserve legitimate absence for `is_seller_know_cv=false` seller turns. | Contract fixed and replay-verified. Decision-impact claim narrowed: direct rule ignores values, but optional coverage control can reach them; live activation is not logged. | Raw log: 120 turns = 6 uninformed-seller games x 20 rounds; no alternate names. Corrected contract replays all 1,423 payloads with zero violations; 348 tests pass, 7 skip. | `shipped` | none | Contract change is validation-only; do not infer policy equivalence through the coverage gate. | `reports/live/observations.jsonl`; `docs/FAILED.md`; `tests/test_contracts.py` |
| `uninformed_seller_coverage_key` | Preserve missing hidden persuasion `v/c` in coverage keys instead of coercing them to numeric-zero bins; record support-index identity in future launch manifests. | Batch activation remains inconclusive because the 109-game run predates the manifest and its summary has no environment data. | Regression test proves hidden values cannot resolve a populated real-zero coarse bucket; 31 focused tests pass. | `shipped` | none | Information-boundary/keying fix only; no claim about historical action impact. | `glee_eval/data/dataset_audit.py`; `glee_eval/live/run.py`; `docs/FAILED.md` |
| `live_observation_cli` | Let `stats` summarize `reports/live/observations.jsonl` directly and expose real subcommand help; document why `shadow-score` requires episode summaries. | None. Live turn logs have no terminal payoff/scenario, so shadow scoring them would fabricate percentile inputs. | `stats --observations` reports 1,423 turns, zero fallbacks, 120 historical violation turns/240 field alerts. CLI/shadow focused tests pass. | `shipped` | none | Reporting only; does not alter scoring semantics. | `docs/LIVE_INTEGRATION.md`; `tests/test_cli_observations.py` |
| `live_terminal_results` | Audit terminal outcomes with `live-episodes`, capture full SDK move responses, and GET-backfill games ending on opponent moves. | Historical pre-fix log remains incomplete; new capture path is verified. | Authorized confirmation: 31/31 authoritative terminal payoffs (15 direct +16 backfill), zero capture errors. Means B .383075, N .116996, P .235000. Manifest records support index off. | `shipped` | none | Account counter advanced 30 while capture has 31 terminal games; retain both denominators. No further live games without explicit authorization. | `docs/LIVE_INTEGRATION.md`; `glee_eval/live/episodes.py`; `glee_eval/live/run.py` |
| `live_strict_game_limit` | Replace reliance on SDK `max_games` with bounded matchmaking waves and a unique-game-ID cap including opponent-ended games. | Upstream `--max-games 12` produced 31 terminals; repository wrapper no longer delegates this limit. | Two real verifications completed exactly 75/75 each, balanced 25 per family. The second had 35 direct +40 backfill, 860 clean turns, and zero capture errors/fallbacks/schema violations. | `shipped` | none | Do not call upstream `GleeClient.run(max_games=...)` directly. No further live games without explicit authorization. | `docs/FAILED.md`; `tests/test_live_run.py`; `reports/live/volume2_20260815` |
| `live_simulator_alignment` | Diagnose live/offline payoff differences against fitted opponent/config assumptions without changing policy. | Bargaining's deterministic simulator timing defect is fixed, but it explains only part of the live gap and produced no acting-policy candidate. Persuasion's residual buyer-rate/role premise is killed after message-mode conditioning. Negotiation's true no-trade exit rate remains unidentified. | Bargaining authoritative n=61 mean .407409; all agreed, gross share .54511 minus .13770 mean discount loss. Live opponent offer-transition mean .00657/median 0 versus fitted concession median .025. Corrected theory audit +.0551 and confirmation +.0601 both pass. A production-visible low-delta/stagnation override is killed at n=2 with opposite signs; flat theory-off replay is only +.00484/61 with 4 gains/7 losses. | `candidate` | unassigned | Fitted opponent marginals are independently sampled and do not preserve real joint player/config behavior; this is model risk, not an identified live policy fix. Persuasion/negotiation conclusions remain as recorded in FAILED. | `bargaining_opponent_timing_parity`; `docs/FAILED.md`; three terminal-complete live batches |
| `model_b_joint_opponents` | Fit and empirically sample one correlated opponent-parameter bundle per stable `(player_model, config_id, role)` segment instead of independently drawing marginal quantiles. | Frozen predictive validation failed. Config-holdout whole bundles were significantly worse than the same-support conditional shuffle for bargaining and negotiation; persuasion was below the declared coverage floor. This exact fit/validation formulation may not be retried. | Model axis: all families unreportable at 4 actor-model clusters; retention B/N/P .680/.499/.202. Config axis: energy delta joint-minus-shuffle B +.003458, CI upper +.004512; N +.001593, upper +.002490; P retention .374. | `retracted` | none | The v2 sampler remains an experimental compatibility surface only and is not trusted for payoff gates. | `reports/model_b_validation`; `docs/FAILED.md`; declaration below |
| `model_b_crossfit_joint_opponents` | Four-by-four actor/config out-of-fold joint opponent model with hierarchical decision-level response estimates. | Retracted at the mandatory pre-fit kill-check: the corpus contains 15 acting-model identities, not the declared 16, so four balanced actor folds of four cannot exist. No fold artifact or predictive score was produced. | Streaming full-corpus manifest scan stopped before actor fold 0 with `actor cross-fit requires exactly 16 identities, found 15`. | `retracted` | none | The hierarchical estimator remains reusable, but this exact manifest/fold declaration may not be repaired in place. | `docs/FAILED.md`; declaration below |
| `model_b_mixed_fold_crossfit` | Exhaustive three-fold actor-model OOF (5 of the 15 real identities per fold) plus four-fold canonical-config OOF, retaining hierarchical response estimates and joint-bundle validation. | Replace the failed numerical instrument without changing the frozen statistical model, then prove predictive value on every fold before any tournament or policy gate. | Mixed manifest passed 5/5/5. Three failed optimizers are retained in FAILED. The stationarity-certified sparse coordinate-Newton fit completed actor fold 0, but every B/N/P ridge was ineligible because at least one inner fold missed projected-KKT `<=1e-7`; the best recorded residuals were still about .00237-.00303 and many were much larger. The run stopped immediately after fold 0; actor fold 1 was interrupted, and no holdout was scored. | `candidate` | unassigned | Per-axis manifest/router, hierarchical response fit, joint validator. A new solver may change numerical parameterization/linear algebra only; ridge/folds/model/KKT contract remain frozen. No payoff gate or live play authorized. | Prospective mixed-fold declaration below; `docs/FAILED.md` |
| `persuasion_text_stance` | Default-off buyer parser for unequivocal natural-language recommendations when the live text payload contains no structured yes/no stance; ambiguous text remains a conservative decline and binary inputs are unchanged. | Gate rejected; do not rerun unchanged and do not flip the default. Production mechanism remains diagnosed: 180/180 text buyer turns across nine complete live games defaulted to no despite 101 clearly positive and 79 clearly negative messages. | Frozen 420-turn replay: 0 polarity errors, 420 raw messages preserved, 240/240 binary actions unchanged, 84 text actions reached. Seed 314159, n=1600 structural holdout: +0.1390, t=13.04, 241W/12L/1347T; all archetypes nonnegative, but config-regime concentration 0.5437 > 0.50. | `candidate` | unassigned | Default remains false. Shares persuasion transcript parsing with the live adapter, synthetic runner, fitted opponent policy, and buyer decision path. No live payoff claim is allowed from declined rounds because their qualities are unobserved. | `reports/promotion/persuasion_text_stance_seed314159`; `reports/live/confirmation_20260815`; `reports/live/volume_20260815`; `docs/FAILED.md` |
| `h6_percentile` | Preserve official-style percentile/rating and add a separate run-specific trade-zone diagnostic using the identical exact-to-family fallback ladder. | Candidate implemented; real-log replay unavailable locally. | Adversarial review caught and corrected an initial family-wide comparison that dropped config conditioning. Zone-suffixed buckets now mirror primary fallback/min-support semantics; exact-bucket equality and fallback divergence are tested. | `candidate` | root | Scoring/reporting only; primary percentile/rating contract unchanged. | `glee_eval/scoring/shadow.py`; `tests/test_shadow_scoring.py`; `docs/HANDOVER.md` §2/§6 |

## Session kill-checks

- `deceptive_seller_guard`: inconclusive against live observations because
  `reports/live/observations.jsonl` is absent locally. A synthetic one-lie probe still buys;
  this is hypothesis-generating only. Closest FAILED entry is the frozen-posterior retraction;
  the new direction models uncertainty rather than retrying the accessor or exploration.
- `persuasion_calibration_bins`: inconclusive against live observations because the log is
  absent. The released-data audit independently confirms under-confidence across both model and
  config holdouts, while falsifying channel mismatch as the main aggregate explanation. Closest
  FAILED entry is the frozen-posterior retraction; this audit targets conditional calibration
  without reviving its blanket payoff claim.
- `h6_percentile`: inconclusive against live observations because the log and reproducible run
  artifacts are absent. Code evidence narrows pooling to fallback/coarse cases rather than all
  exact buckets and exposes the dead warning path. No close prior FAILED entry.
- Fresh persuasion pass: the live observation log remains absent, so the live kill-check is
  inconclusive. Released logged decisions support seller-specific honesty tracking only for
  persistent buyers; the broad myopic version is killed. Separating seller informedness from
  observed dishonesty survives both structural axes. The blanket guard is killed by trajectory
  replay because it blocked 309 profitable purchases and only 92 loss-making purchases.
- Seller archetype targeting: killed as a direct-policy hypothesis. No fitted archetype label is
  available in production state, while the seller already adapts to observable within-game
  receiver obedience. Stipulated archetype trust differences are not an actionable live signal.
- Live adapter: the official-documentation mismatch for `history` and persuasion
  `current_player` was repaired in fixtures, contracts, and translation tests. Server
  compatibility remains unverified; no live game was used to resolve it.
- Real-server correction (50 user-run games): `history` and `current_player` are confirmed, but
  `u/v` are intentionally absent on uninformed-seller turns. The earlier unconditional contract
  produced 240 false alerts on 120 turns. There were no renamed fields: all six affected games
  had `is_seller_know_cv=false`. The conditional contract replays all 1,423 payloads cleanly.

## Confirmation declarations

Add sample size and seed here before executing any independent confirmation run.

- `bargaining_opponent_timing_parity` theory-anchor corrected-simulator confirmation (declared
  2026-08-15 after the seed-112358 gate passed every ordinary check and before confirmation
  measurement): compare unchanged theory-on `MyAgent` against the same isolated theory-off
  baseline, bargaining only, paired on identical scenarios from the same fitted model-holdout
  opponent population and config-holdout catalogue, with exactly the declared timing-unit and
  unfitted-acceleration corrections. Fixed seed **2718281**, **n=3200**. Require every ordinary
  promotion check unchanged: sample size, mean >=.0100, paired t>=1.96, downside p5,
  archetype/config concentration and breadth, and structural holdout. Any failure leaves the
  production default unchanged pending root review, records the exact failure in FAILED, and
  permits no unchanged retry. A pass only revalidates the shipped theory-anchor evidence and
  makes live authorization potentially eligible; it does not authorize a live/rated run.

## Ordinary gate declarations

- `model_b_joint_opponents` implementation/validation declaration (declared 2026-08-15 before
  predictive measurement): the empirical unit is a stable
  `(player_model, config_id, role)` segment after the requested structural split is applied.
  Raw identifiable segment endpoints match production policy units: bargaining mean first-own-
  offer self-share, per-successive-own-offer concession, interpolated acceptance threshold and
  residual uniform half-width; negotiation mean first-own-offer normalized aspiration, role-
  oriented per-successive-own-offer concession, interpolated 50% acceptance threshold in own
  normalized gain and residual uniform half-width; persuasion seller P(yes|high) and
  P(yes|low), plus buyer P(buy|yes) and P(buy|no). Residual half-width is
  `sqrt(3) * residual_sd` around the fitted intercept/slope, matching policy uniform-noise units.
  A serialized bundle is retained only when it has at least two identified parameters and at
  least two distinct contributing games; action counts and distinct-game support are serialized,
  while missing parameters remain explicitly absent and are not silently imputed. At draw time one
  role-compatible whole bundle is sampled with distinct-game empirical weight through a frozen
  exact-config-signature, coarse-config-signature, then role-only fallback ladder; its identified
  parameters stay correlated, and missing policy parameters use existing policy defaults rather
  than independently sampled fitted marginals. The sampled bundle's latent percentile derives
  the compatibility archetype label after the draw; stipulated uniform archetypes are not the
  Model-B sampling prior. The latent score is the
  equal-weight mean of fit-only empirical strategic-parameter percentiles after orienting higher
  values toward extraction (concession and trust inverted; buyer aspiration inverted; residual
  noise excluded), ranked
  separately inside each family-role cell; ties are broken by stable bundle id. No learned
  statistic may cross a model/config split boundary. Model splits serialize actor-model
  holdout eligibility; config validation uses the new backward-compatible `config_signature`
  split keyed by the same family-aware canonical defining fields/defaults used by bundle draws,
  never the legacy source-prefixed `config_id` split.
  Schema v2 preserves v1 marginal tables only as an explicit comparator and compatibility
  surface. Validation is predictive/distributional on separately extracted raw model- and
  config-holdout bundles, with fit-artifact normalization only; it is not a payoff promotion
  gate and cannot ship an acting-policy change. No live/rated run is authorized.

  **Prospective validation endpoints (corrected before artifact rebuild or holdout
  extraction/scoring):** fit two completely separate schema-v2 artifacts, one on model-FIT
  events and one on normalized-`config_signature`-FIT events, and evaluate each only on its
  corresponding model-HOLDOUT or `config_signature`-HOLDOUT. Both axes use the frozen
  deterministic holdout fraction **0.25**; legacy `config`/`config_id` FIT/HOLDOUT assignments
  are not inputs. On the model axis, retain only a bundle whose actor model is itself a
  held-out model; fit-model actors appearing in cross-model held-out games are excluded. The
  observed unit is one raw
  `(player_model, config_id, role)` bundle from `extract_joint_bundle_observations`; retain it
  only when at least two production parameters are identifiable, the bundle contains at
  least two distinct games, and every scored parameter has support from at least two distinct
  games. These support thresholds may not be relaxed after counts or results are seen. Scale
  each parameter through its family/role FIT-artifact empirical CDF (mid-rank, finite tails);
  no holdout value may set a scale, rank, default, band, weight, or missing-value rule. Score
  the parameter values actually delivered to the opponent policy, including the same existing
  policy value actually delivered when a draw has an explicitly missing parameter: neutral
  Model-B defaults for whole-bundle and conditional-shuffle draws, and the current
  archetype-dependent/default behavior for the v1 operational comparator. Residual
  `action_noise` is a scored production parameter; it may not be dropped merely because an old
  v1 artifact lacked that marginal.

  For each retained bundle, take exactly **256** predictive draws per sampler using master seed
  **20260815** and a stable bundle/sampler-derived sub-seed. Schema v2 must use the production
  `sample_bundle(family, role, heldout_configuration, rng)` path: condition on the held-out
  configuration through the immutable `exact_config_signature -> coarse_config_signature ->
  role` fallback ladder, sample with the artifact's empirical distinct-game weights, and derive
  the archetype label only after the bundle draw. The **same-support conditional-shuffle
  comparator** uses that identical exact/coarse/role eligible pool, empirical game weights,
  held-out configuration and neutral default rules, but independently samples a bundle for
  each requested parameter; it changes joint dependence only. The schema-v1 operational
  comparator must reproduce its
  actual production prior: cycle evenly over all 16 archetype labels (16 draws per label) and
  draw every scored parameter independently from its retained marginal quantile table. The
  held-out configuration is an input to v2 conditioning only and may not alter either FIT
  artifact. Report v2 fallback-level counts in every cell. The two mandatory energy endpoints
  are paired multivariate deltas `whole_bundle - conditional_shuffle` (the primary joint-
  dependence estimand) and `whole_bundle - v1_independent` (total operational replacement
  value), both lower-is-better. Use **2,000** deterministic cluster-bootstrap replicates,
  clustering by `player_model` on the model axis and canonical `config_signature` on the config
  axis. A family/axis cell is
  reportable only with at least **5** distinct split-unit clusters; otherwise it is insufficient
  evidence, not a pass. Success requires the mean and 95% bootstrap upper bound to be strictly
  below zero for **both** energy endpoints in **all six family x structural-axis cells**; no
  pooled result may hide a failed or unreportable family.

  Coverage is a hard part of the verdict, not a diagnostic selected after measurement. In each
  family/axis cell, scored bundles must cover at least **50%** of eligible distinct holdout
  games and each family role must contribute at least **25** scored bundles. Role-only v2 draw
  fallback may be at most **25%** on the model axis and **50%** on the config-signature axis;
  the latter axis must have exactly **zero exact-signature draws** as a leakage assertion.
  Neutral defaults may fill at most **25%** of requested whole-bundle plus conditional-shuffle
  parameter values. Failing any coverage assertion, or having fewer than five split-unit
  clusters, makes the cell unreportable and failed; thresholds may not be relaxed.

  **Safety endpoints:** on the same FIT-CDF scale, the joint sampler's paired mean marginal
  CRPS delta against **each** comparator must have a 95% cluster-bootstrap upper bound at most
  **+0.005** in every one of the six cells, and every reported family/axis/parameter mean CRPS
  delta against either comparator must be at most **+0.010**. Every whole-bundle and
  conditional-shuffle draw must be finite and inside the parameter's observed FIT support after
  ordinary policy bounds; any such support/non-finite violation fails that cell. Operational-v1
  support violations are reported separately and cannot make Model B pass by making the legacy
  comparator fail. The frozen FIT artifact's SHA-256 and split provenance must match the
  requested validation axis or the validator refuses to run. Report role cells,
  bundle/cluster counts, exclusions by reason, parameter missing/default rates, correlation and
  covariance error, but these are diagnostic and may not replace or select the endpoints.
  This predictive all-pass result, if achieved, authorizes only a later prospectively declared
  payoff gate; it does not promote Model B or change a production default.

- `model_b_crossfit_joint_opponents` materially-new validation declaration (declared
  2026-08-15 after the frozen one-shot verdict failed, and before any cross-fit model is fit or
  scored): the closest failure is `model_b_joint_opponents`. A new seed, relaxed retention
  floor, pooled in-sample bundle, or marginal imputation is not new. This formulation changes
  the estimand to exhaustive out-of-fold prediction and changes sparse response estimation to
  decision-level partial pooling.

  Use exactly four immutable outer folds on each axis. Actor-model folds are the SHA-256-sorted
  set of the 16 observed model identities assigned round-robin, exactly four identities per
  fold. Canonical-configuration folds are
  `int(SHA256(canonical_config_key)[:16], 16) % 4`. An acting role's own model determines its
  actor fold even when the other player belongs to another fold. Each event, bundle, actor and
  canonical signature is evaluated in exactly one outer fold and excluded from every statistic
  fitted for that fold. Serialize fold membership, training-identity/signature hashes, artifact
  SHA-256s and routing provenance; duplicate OOF rows or a routed artifact containing its held-
  out identity/signature are fatal leakage errors. Pool OOF predictions only after all four
  fold-specific predictions are frozen.

  Preserve production units and attach all estimates belonging to an actor/config/role segment
  to that one bundle. For bargaining and negotiation acceptance, fit all legally visible FIT
  response decisions, with outside-option responses labeled non-acceptance. Bargaining x is
  responder share; negotiation x is role-oriented normalized own gain. Use a monotone logistic
  slope plus role intercept and actor-model/canonical-config offsets, with fixed ridge grid
  `[0.1, 1, 10, 100]`. Select the penalty by training-only three-fold game-hash cross-validation,
  minimum log loss with ties choosing the larger penalty; an outer-fold row may never select a
  penalty. The p=.5 threshold is transformed back to policy units, clipped only to the FIT
  decision-margin range, and serialized with source, decision/game support, accepts/rejects,
  coefficients, penalty, convergence and clipping metadata. Fit persuasion seller
  P(yes|high)/P(yes|low) and buyer P(buy|yes)/P(buy|no) from all corresponding FIT decisions
  using the same outer-fold isolation and training-only ridge selection, with explicit
  actor/config partial pooling. Existing first-offer, successive-own-offer concession and
  residual-noise endpoints retain their corrected production units; missingness remains
  explicit and no held-out outcome is used to fill it.

  Bundle validation retains the prior fixed master seed **20260815**, exactly **256** draws per
  sampler/bundle, and **2,000** deterministic cluster-bootstrap replicates. It retains the
  same-support conditional shuffle as the primary dependence comparator, the actual v1 sampler
  as the operational comparator, FIT-only ECDF scaling, both energy-delta mean/upper-bound < 0
  requirements, both marginal-CRPS safety ceilings, zero Model-B/shuffle support or nonfinite
  violations, role counts, neutral-default ceiling and the exact/coarse/role production ladder.
  Pool only OOF rows. Model-axis inference clusters by all eligible actor models and requires at
  least **12** overall and **3 per outer fold**; config-axis inference clusters by canonical
  signature and requires at least **20** overall and **3 per fold**. Every family/axis cell must
  still cover at least **50%** of eligible distinct games and at least **25** bundles per role;
  role fallback remains <=25% model and <=50% config, and config-axis exact fallback remains
  exactly zero. No failed or unreportable cell may be pooled away.

  Add a mandatory OOF decision endpoint for each bargaining and negotiation axis/role cell.
  Against both the neutral-default response model and v1 response model, hierarchical Model B
  must improve clustered log loss with paired mean and 95% upper bound < 0, and Brier score with
  paired mean < 0 and upper bound <= 0. Require both outcomes, >=25 evaluation games, >=5 split
  clusters, >=50% decision/game reach, finite in-domain thresholds and complete support/
  convergence provenance; report calibration intercept/slope without selecting on them. For
  persuasion, apply the same log-loss/Brier requirements separately to seller high/low
  recommendation and buyer yes/no purchase channels. Any family, role, channel or structural
  axis failure retracts this formulation. A full predictive pass authorizes only the later
  prospectively declared payoff comparisons and negotiation gates; it cannot itself ship a
  production policy or authorize live play.

- `model_b_mixed_fold_crossfit` prospective correction (declared 2026-08-15 after the
  four-by-four pre-fit kill-check failed and before changing the manifest code, fitting an
  artifact, or scoring a holdout): the complete event stream has exactly **15** acting-model
  identities. Replace the impossible common four-fold assumption with per-axis fold contracts.
  The actor axis uses exactly **3** SHA-256-sorted round-robin folds, five identities per fold,
  holdout fraction 1/3. The canonical-config axis retains exactly **4** hash-modulo folds and
  holdout fraction 1/4. Every identity/signature is evaluated exactly once and appears in all
  other folds' training sets. Serialize and verify the fold count and fraction separately for
  each axis; a router may not infer one axis's values from the other. Fit exactly three actor
  artifacts and four config artifacts. The pre-fit command must reject any count other than
  15 actor identities or any actor fold not sized 5/5/5.

  All model, sampler and predictive endpoints from the preceding hierarchical cross-fit
  declaration remain unchanged: production-aligned bundle parameters; training-only response
  shrinkage; same-support conditional shuffle and v1 comparators; FIT-only ECDFs; seed
  **20260815**; 256 draws; 2,000 clustered bootstraps; both energy and CRPS requirements; every
  bargaining, negotiation and persuasion response-channel log-loss/Brier requirement; coverage,
  role, fallback, default, support, convergence and exact-config leakage assertions. Model-axis
  pooled inference still requires >=12 actor clusters and now requires >=3 clusters in each of
  the three actor folds. Config-axis inference still requires >=20 signatures overall and >=3
  in each of four config folds. No threshold is relaxed. Any failed/unreportable family, role,
  channel or axis retracts this mixed-fold formulation. A predictive pass still authorizes only
  later prospectively declared payoff work and no live play.

- `model_b_response_newton_pcg` numerical-instrument declaration (declared 2026-08-15 after
  the stationarity-certified coordinate solver failed actor FIT fold 0, and before code or a
  new corpus fit): preserve the exact summed binomial-logistic likelihood, `.5 * ridge *
  (||model_offsets||^2 + ||config_offsets||^2)` penalty, ridge grid `[.1, 1, 10, 100]`,
  three training-only game-hash CV folds, pooled validation-decision log-loss selection,
  larger-ridge exact tie rule, standardized production-unit response feature, slope lower bound
  `1e-8`, 300 outer-Newton limit and original-coordinate projected-KKT tolerance `1e-7`.
  Neither response rows nor any predictive/payoff endpoint may change.

  Fit each family/role response channel in a deterministic zero-sum contrast basis for actor and
  canonical-config offsets. The last level equals minus the remaining levels, and the full ridge
  penalty is evaluated after reconstructing every raw offset; this is an exact reparameterization,
  not reference coding. At every outer iteration, form stable sorted sufficient-statistic
  gradient and sparse Hessian-vector products. Solve the active-set Newton system by deterministic
  preconditioned conjugate gradients. The preconditioner is an exact channel intercept/slope
  `1x1`/`2x2` block plus ridge-and-weighted diagonals for contrasts. The zero initial PCG vector,
  fixed coefficient ordering and stable summation make output deterministic. The PCG residual
  target is `max(1e-12, min(.5, sqrt(KKT)) * KKT)`; its iteration cap is
  `min(2000, max(50, 4 * free_parameter_count))`. A nonpositive-curvature or nondescent solve may
  retry only the deterministic Newton-system shift schedule `[0, 1e-12, 1e-10, 1e-8, 1e-6,
  1e-4]`; the shift never enters the fitted objective, and exhaustion makes the fit unavailable.

  Globalize with projected Armijo backtracking (`c1=1e-4`, factor `.5`, floor `2^-30`). A failed
  line search is nonconverged. Declare convergence only after reconstructing raw coefficients and
  independently recomputing the original-coordinate projected-KKT infinity norm `<=1e-7`; step
  size, contrast-space gradient, relative loss and elapsed iterations cannot substitute. Serialize
  coefficient-order hash, contrast reconstruction, KKT/objective histories, active slopes, every
  PCG target/residual/iteration/curvature/shift/descent product, every Armijo alpha/backtrack/pass,
  and stop reason. Every inner CV fold must pass the same contract before a ridge is eligible.

  Pre-corpus kill-checks: sparse HVP must match a dense Hessian and finite-difference gradient;
  PCG direction must match a dense constrained Newton solve; original and zero-sum objectives
  must match; raw/aggregated and input-order variants must be deterministic; bound-slope,
  near-separation, nonfinite/negative-curvature, forced-line-search and 300-limit fixtures must
  fail or pass without false convergence. After those tests, actor fold 0 is again the only
  permitted FIT checkpoint. All B/N/P final and inner fits must be `status=ok`, finite and KKT
  certified before later folds continue. Any failure retracts this solver; iterations/tolerance,
  PCG cap/forcing, shift schedule or Armijo constants may not be relaxed in place. No holdout may
  be scored until all seven mixed-fold artifacts freeze, and no payoff/live work is authorized.

- `bargaining_opponent_timing_parity` theory-anchor evidence audit (declared 2026-08-15 before
  measurement): make exactly two simulator-fidelity corrections and no fitted-parameter changes:
  apply fitted `concession_rate` by successive own-offer index `(state.round - 1) // 2` rather
  than global elapsed round, and remove the separate unfitted `conceding` subtraction
  `.05 * state.round`. Compare the unchanged theory-on `MyAgent` with an isolated theory-off
  baseline (`use_theory_anchor=False`), bargaining only, paired on identical scenarios from the
  fitted **model-holdout** opponent population and **config-holdout** catalogue. Fixed first
  audit: seed **112358**, **n=1600**, ordinary promotion criteria in full (sample size, mean
  >=.0100, paired t>=1.96, downside p5, archetype/config concentration and breadth, structural
  holdout). This is an evidence audit: one pass cannot flip the already-on production default.
  If and only if every check passes, declare the independent confirmation below before running
  it. Any failed check invalidates the old fitted-simulator evidence for root review, appends the
  exact result to FAILED, and permits no unchanged retry.

- `unknown_horizon_counter_fallback` (declared 2026-08-15 before measurement): immutable reach
  predicate is true iff a baseline candidate-role pre-action state is negotiation decision,
  the baseline decision is `RejectOffer`, its structured action contains neither
  `counter_price` nor `product_price`, and `horizon_known` is false. The predicate is evaluated
  from the baseline state/action before either terminal payoff and identically labels both arms.
  Candidate algorithm only on that branch: recover the candidate's most recent own offer; form
  a fixed scheduled own margin `max(0.02, 0.15 * 0.99 ** (round - 1))`; seller counter is the
  lesser of the last own offer and `own_value + margin`, buyer counter is the greater of the last
  own offer and `own_value - margin`, preserving a positive own margin and never worsening the
  prior own offer. If no own offer exists, use the scheduled price. Capped-horizon behavior and
  all three rejected negotiation flags are unchanged. Evaluate a live-contract simulator that
  hides `max_rounds` from both candidate arms while retaining the sampled catalogue cap in the
  engine, and treats rejection counter-price as the next offer. Fixed gate: config structural
  holdout, fitted holdout opponent/config artifacts, seed **8675309**, **n=1600** paired
  negotiation episodes. Require every ordinary promotion check: n>=200, mean>=.0100, paired
  t>=1.96, downside p5 regression<=.02, max subgroup concentration<=.50, subgroup regression
  fraction<=.40 on opponent archetype and config regime, and structural holdout. No
  branch-conditional amendment is invoked. Any failure keeps the default off and forbids an
  unchanged seed retry. If all pass, declare an independent confirmation before running it.

- `guarantee_own_margin` (declared 2026-08-15, before execution): independently repeat the
  identical immutable `negotiation_collapsed_margin_window` predicate on the structural
  holdout with seed 104729 and n=3200. Require the ordinary gate to fail at most
  `minimum_effect`, and require conditional n>=30, mean>=0.0100, t>=1.96, exactly zero losses,
  and exactly zero regressing observed archetype/config-regime subgroups. Any failure returns
  the family to `candidate`; no seed retry is permitted.

## Construction-defect conditional declarations

- `unknown_horizon_counter_fallback` eligibility audit (2026-08-15; **ineligible, no
  evaluation run**): the baseline pre-state predicate previously declared above is immutable,
  and the `16950 -> 17250` seller counter supplies an arithmetic example of moving away from
  agreement. The later 193/193 live fallback-reach finding strengthens reach evidence only.
  Amendment condition 4 fails because the ordinary seed-8675309 gate also failed config-regime
  concentration at **0.5980 > 0.50**, not only `minimum_effect`. Condition 3 also fails for the
  unchanged candidate: `max(0.02, 0.15 * 0.99 ** (round - 1))` selects a new concession path,
  whereas clamping the fallback to the last own offer is the smaller change that alone restores
  the stated no-worsening invariant. No predicate, seed, or sample size is declared because the
  amendment forbids this evaluation; no branch-conditional gate or confirmation was run.

- `guarantee_own_margin` (declared 2026-08-15 before conditional evaluation): proof is the
  collapsed baseline clip above. Immutable branch predicate
  `negotiation_collapsed_margin_window` is true iff at least one baseline candidate-role
  pre-decision state is negotiation, has `valid_action_schema.kind == "offer"`, and the
  baseline's beliefs computed from that state satisfy `buyer_value <= seller_value`. It is
  evaluated from baseline visible state identically for both arms, before either paired payoff
  is inspected; action divergence and nonzero paired differences are not inputs. Re-evaluate
  n=1600 at seed 4242 on the fitted-population/config-catalogue structural holdout. Ordinary
  checks must fail only `minimum_effect`; the conditional sample must have n>=30, mean>=.0100,
  t>=1.96, zero losses, and zero regressing observed archetype/config subgroups.

## Construction-defect eligibility audit

- `guarantee_own_margin`: eligible as declared above; arithmetic proof and immutable pre-state
  predicate both exist, and the prior ordinary run failed only `minimum_effect`.
- `time_concession`: ineligible. Round independence is a policy property, not a violated
  arithmetic invariant; no immutable defect predicate exists independent of desired behavior.
- `debias_counterpart_value`: ineligible. Its justification and constants are empirical, and
  its ordinary run also failed config concentration.
- `combined_counteroffer_path`: ineligible bundle of three mechanisms and its confirmation
  failed both effect and concentration.
- `persuasion_explore`, `persuasion_calibration_bins`, and `deceptive_seller_guard`: ineligible
  policy/predictive candidates justified by empirical patterns, not implementation proofs.
- `message_mode` and `h6_percentile`: no default-flipping payoff candidate eligible for this
  gate; message text remains structurally untestable and H6 is reporting-only.

## Predictive declarations

- `persuasion_calibration_bins` (declared 2026-08-15 before evaluation): fit exactly one
  two-parameter Platt map `sigmoid(a + b*logit(p_raw))` on yes-recommendation FIT rows, with
  probabilities clipped to `[1e-6, 1-1e-6]` only for numerical stability. Evaluate separately
  on model and config structural holdouts. Primary endpoint is paired per-decision Brier delta
  (calibrated minus raw), successful only if the mean and game-cluster bootstrap 95% CI upper
  bound are below zero on both axes. Safety endpoint is paired clipped log-loss delta with 95%
  CI upper bound at most zero on both axes. Fixed-bin ECE and the 0.5-0.8 gap are diagnostic
  only and may not select or tune the candidate. Predictive success cannot flip a policy
  default; any acting change requires the promotion gate and a separately declared confirmation.
