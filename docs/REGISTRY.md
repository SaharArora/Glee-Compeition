# Approach registry

Durable status for policy, scoring, and evidence work. Statuses follow
`docs/HANDOVER.md` §0.9 exactly: `candidate`, `gate-passed`, `confirmed`, `shipped`, or
`retracted`. A status never outruns the weakest supporting run.

| Family | Exact change | Remaining gap | Last gate/evidence | Status | Owner | Dependencies / shared surfaces | Evidence |
|---|---|---|---|---|---|---|---|
| `theory_anchor` | Bargaining offer policy uses the theory anchor by default. | None recorded. | Holdout: +0.0737, t=+12.43, n=800, 389W/91L; earlier fitted-population run +0.046, t=+6.60. | `shipped` | none | Bargaining offer path. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.1/§2 |
| `time_concession` | Optional Boulware time-dependent negotiation concession (`use_time_concession=False`). | Below minimum effect; offline population rarely reaches long negotiations. | +0.0003, t=+2.11, 6W/76L/1518T, n=1600; failed `minimum_effect`. | `candidate` | unassigned | Shared negotiation counteroffer path with `guarantee_own_margin` and `debias_counterpart_value`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2-§0.4 |
| `guarantee_own_margin` | Optional own-profitability offer clip and live `counter_price` plumbing (`guarantee_own_margin=False`). | Independent confirmation failed; no retry permitted and default remains false. | Gate seed 4242 conditional n=1068: +0.0102835, t=8.770, 96W/0L, passed. Declared confirmation seed 104729 n=3200: ordinary +0.0071239 with concentration 0.5620; conditional n=2155, +0.0091320, t=11.40, 166W/0L; failed conditional effect. | `candidate` | unassigned | Zero losses/regressing conditional subgroups held, but every declared check was mandatory. | `docs/PROMOTION_CRITERIA.md`; `docs/FAILED.md` |
| `debias_counterpart_value` | Optional correction of opening-price inference using measured median shading/markup (`debias_counterpart_value=False`). | Below minimum effect and too concentrated by config regime. | +0.0072, t=+7.52, 64W/1L/1535T, n=1600; failed `minimum_effect` and concentration 0.5951. | `candidate` | unassigned | Shared negotiation counteroffer path with `time_concession` and `guarantee_own_margin`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.2/§0.5 |
| `combined_counteroffer_path` | Enable time concession, own-margin guarantee/counter-price, and value de-bias as one coupled mechanism. | Confirmation failed; do not rerun unchanged. A retry must be materially new. | Gate seed 4242: +0.0109, t=+10.07, n=1600, passed. Declared confirmation seed 9999: +0.0094, t=+12.49, n=3200, failed `minimum_effect` and concentration 0.5539. | `retracted` | unassigned | Owns the shared negotiation counteroffer surface; depends on `minimum_effect_policy`. | `docs/PROMOTION_CRITERIA.md`; `docs/HANDOVER.md` §0.3 |
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
| `live_strict_game_limit` | Replace reliance on SDK `max_games` with bounded matchmaking waves and a unique-game-ID cap including opponent-ended games. | Upstream `--max-games 12` produced 31 terminals; repository wrapper no longer delegates this limit. | Focused strict-runner test queues exactly 8 IDs in balanced rotating waves; 66 live/adapter tests pass. | `shipped` | none | Real 75-game volume run is the first server verification. Do not call upstream `GleeClient.run(max_games=...)` directly. | `docs/FAILED.md`; `tests/test_live_run.py` |
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

- `guarantee_own_margin` (declared 2026-08-15, before execution): independently repeat the
  identical immutable `negotiation_collapsed_margin_window` predicate on the structural
  holdout with seed 104729 and n=3200. Require the ordinary gate to fail at most
  `minimum_effect`, and require conditional n>=30, mean>=0.0100, t>=1.96, exactly zero losses,
  and exactly zero regressing observed archetype/config-regime subgroups. Any failure returns
  the family to `candidate`; no seed retry is permitted.

## Construction-defect conditional declarations

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
