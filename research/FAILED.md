# Research failures and closed routes

## Wave 5E paper activation alternatives — rejected prospectively

- **Smaller A-shaped design:** rejected for the `.035` paper SESOI under the frozen central
  planning assumptions. A200's single-primary MDE is `.0361683`; A140 and A100 are worse. This is
  design arithmetic, not a treatment result. Reopen only with a prospectively justified larger
  SESOI, lower-variance evidence that is independent of treatment outcomes, or a materially
  different estimator/population.
- **Three co-primary hypotheses as the default order:** rejected prospectively. The language
  intervention is exposed on all 20 eligible rounds, whereas e-process crossing and action change
  are unknown and can be rare. Spending Holm precision on e-process and interaction as co-primary
  makes A300's central MDE `.0341062`, almost equal to the `.035` SESOI. Language is now the single
  primary; e-process and interaction remain mandatory key secondaries. Reopen the co-primary
  family only with outcome-independent evidence that their exposure supports the same precision.
- **Twelve-hour full-study wall cap:** rejected as internally infeasible. At 32-way concurrency
  and the frozen 30-second timeout, A300 requires 12h32m nominal receiver service and 25h03m30s at
  its retry ceiling before local overhead. The repaired prospective cap is 32 hours and still
  yields a nonreportable incomplete study if exhausted. This does not authorize a full run.
- **Receiver failure retained without environment behavior:** closed as an incomplete ITT rule.
  Timeout, malformed, refusal, missing, and exhausted retry now deterministically map to buyer
  pass/no, ordinary fixed-horizon continuation, and the ordinary finite terminal role payoff.
  Engine failure remains a global nonreportable stop; no constant payoff is imputed.

## R0 v1 — mixed-fold empirical-bundle Model B

- Closest prior route: no close research route. Competition evidence contained earlier Model-B
  implementation failures, but this was the exact frozen exhaustive mixed-fold validation.
- Version/commit: report generated before research branch creation; research input commit
  `bce578597dbfacf2ebca38399edb41a5dde2f936` preserves its registry and artifact references.
- Attempt: three actor folds and four canonical-config folds; compare joint empirical bundles
  with the identical conditional pool independently shuffled, plus marginal/decision checks.
- Obstruction: joint-minus-shuffle energy was worse for bargaining and negotiation on both
  model and config axes. Persuasion retained only `.330520` of games, below the frozen `.50`
  floor. Report SHA256:
  `1a86cac280b1cd6b0049bc9429a6662f9d33b754dcfb23b4044e5b04ebbdacec`.
- Classification: evidence against the proposed empirical-bundle dependence mechanism, not
  merely an implementation failure.
- Materially new retry: prohibited by the root contract unless the user explicitly reopens R0.
  A new seed, threshold, fold, or another automatic joint-model formulation is not enough.

## R0 post-closure actor-factor construction — interrupted

- Closest prior route is R0 v1; this differed materially by using hierarchical action-level
  marginals and actor factors, but it was started before the new contract declared R0 closed.
- Exact interrupted command is recorded in `research/RUN_STATE.md`. It was stopped during actor
  fold 0 and wrote no fold artifact or checkpoint. Only source-only manifests exist outside git.
- Classification: orchestration/scope interruption, not evidence for or against the actor-factor
  mechanism.
- Retry condition: only an explicit user decision reopening R0. Quiet runtime or completed
  pre-fit tests are not authorization.

## R1 input revision `bce5785` — not a treatment-off baseline

- No close prior research route. The closest competition surface is the shipped strategic
  agent, but research requires the heuristic `E_*` mode gate to be absent in all off arms.
- Attempt: map four fresh, same-seed `MyAgent` instances to the four off/off slots and compare
  them with the same theory/empirical-residual path under a fixed `SAFE` control projection.
- Obstruction: the four wrappers are mutually byte/state identical yet all select `EXPLORE`
  and offer `62.0`; the treatment-off projection selects `SAFE` and offers `56.0` on unchanged
  state. Both consume the empirical residual. Evidence: `research/ROUTES/R1_BASELINE.md`.
- Classification: method/contract failure of the baseline mapping, not evidence against the
  theory-plus-residual economic mechanism.
- Materially new retry: an isolated hash-locked baseline class in which heuristic `E_*` cannot
  affect control, plus family/role/action and adapter parity. Another same-seed wrapper alias is
  not new.

## R2 historical `E_*` fields — not e-values

- No close prior research route. This is the first exact e-value check of the historical mode
  scores.
- Attempt: interpret `E_receiver_obedient` as anytime evidence under a fair one-step null.
- Obstruction: after one fair Bernoulli outcome its expectation is exactly `4/3 > 1`.
  `E_sample` is likewise deterministically above one after a row, without a compensating factor.
- Classification: evidence against the historical score's mathematical e-value interpretation;
  it remains a heuristic and must be absent from the off treatment.
- Materially new retry: a distinct process with a declared filtration/null and a supermartingale
  certificate. Rescaling, capping, or renaming the old fields is not new.

## R3 frozen offline language path — candidate causal-feasibility failure

- No close prior route. Existing message generation does not establish receiver consumption.
- Attempt: perturb only text in one receiver state per family while holding numeric action,
  structured stance, state, opponent seed, round, and RNG draw fixed.
- Obstruction: all three offline opponent policies return identical actions; bargaining and
  negotiation also omit messages before receiver state construction. Evidence:
  `research/ROUTES/R3_LANGUAGE.md`.
- Classification: candidate evidence against language evaluability in the frozen offline
  environment, not evidence that language is behaviorally useless in a text-responsive world.
- Materially new retry: only a frozen evaluator/opponent that actually consumes text, or a
  causally valid data source. Prompt wording in the same text-blind path is not new.

## R4 current paired runner — not a factorial isolation certificate

- Closest prior surface is two-arm promotion A/B; this audit asks for four-arm treatment
  isolation and factorial estimands.
- Attempt: identical-seed parity plus a text-only RNG contamination counterexample.
- Obstruction: narrow scenario pairing passes, but the runner has only two arms, no named RNG
  substreams or action-surface checks, and reports a contaminated wording wrapper as `+0.125`
  payoff instead of rejecting it. Evidence: `research/ROUTES/R4_EVALUATION.md`.
- Classification: evaluator implementation failure, not a treatment-effect result.
- Materially new retry: a four-arm runner that emits immutable scenario/support hashes and hard
  rejects any non-treatment action/RNG difference. A new seed in the same two-arm runner is not
  new.

## R4 Wave 2 four-arm runner — inert parity is not active-treatment isolation

- Closest prior route: the Wave 1 two-arm obstruction above. Wave 2 is materially different
  because it implements four arms, one frozen scenario, named seed manifests, arm-invariant
  masks, fixed ordering, factorial contrasts, and a hard inert-parity mode.
- Version: `glee_eval/experiments/factorial.py` SHA256
  `bda3da00922ffcb9e931a95febfa885673a0f778b67d04771243398127011f14`;
  independent audit `research/AUDITS/R4_FACTORIAL_VERIFICATION.md` SHA256
  `f37dc7454ef90018e31dfb22d06ba51f838723b94108dee917628d02f56dfd35`.
- Attempt: pass all seven requested inert canaries, then adversarially rerun the contaminated
  language fixture with the equality-only inert guard disabled as an active treatment requires.
- Obstruction: active mode accepts language code consuming the economic RNG. Four of twelve
  synthetic rows acquire nonzero effects; the first language main effect is approximately
  `-0.05`. Declared seed hashes do not prove which RNG capability was consumed.
- Classification: verifier-backed evaluator-integrity failure, not a language effect and not a
  payoff result. The paired scenario constructor and inert canary survive as narrow utilities.
- Materially new retry: enforce capability-separated RNG objects or realized draw traces during
  active treatment and independently validate the frozen estimands/Holm report. More inert
  equality tests, a new seed, or merely hashing the declared seed again are not new.

## R2 Wave 3 unsupported-channel substitution — rejected

- Closest prior route: the valid Wave 2 fixed-half theorem and historical invalid `E_*` fields.
- Tempting attempt rejected before implementation: create bargaining/negotiation online
  acceptance streams by counting every observed next callback as a rejection, or fill continuous
  offer evidence with the historical multipliers.
- Obstruction: an acceptance terminates those games, so the candidate does not receive a later
  callback containing the success. The apparent online sample would be selected on rejection.
  No accepted Model-C continuous density supplies an offer/concession e-factor.
- Classification: filtration/censoring obstruction, not evidence that acceptance modeling is
  useless. Wave 3 therefore implements only the persuasion-seller obedience stream.
- Materially new retry: a callback/observer contract that records every terminal response before
  acting-state closure, or a separately proved continuous-time/value e-process. Relabeling
  observed rejections or restoring `E_*` is prohibited.

## R4 Wave 3 verifier-backed promotion — withheld

- The named-stream/capability repair is materially new and its 11 evaluator plus 12 agent
  canaries pass. The Wave 2 active contamination fixture is now rejected.
- Promotion is nevertheless withheld: the hostile audit was performed by the implementation
  owner in this task rather than a separately delegated verifier, and the frozen 3,600-row
  estimand/uncertainty/Holm report validator is not implemented.
- Classification: exact remaining verification/reporting obstruction, not failure of the RNG
  repair and not a treatment result.
- Reopen-only-if: a fresh independent audit of SHA
  `1ca9d360073cb59fa7df972ae140796f1585cae6d27ec7d5229ba9670be4bbb3`
  plus a report validator bound to the frozen research question. Another self-run canary or new
  seed is insufficient.

## R2 nontrivial population-valid bound from the training prefix — killed

- Closest prior route: the implemented fixed-reference persuasion-seller e-process. This check
  asked whether the same training corpus could make its fitted reference a conservative real-
  population conditional upper bound.
- Attempt: take the supremum over every future binary process compatible with a finite training
  prefix, while allowing arbitrary repeated-observation dependence.
- Obstruction: the sharp uniform next-step upper bound is `1`. Every bound below one excludes a
  compatible process and loses finite-sample conditional coverage. Optional-stopping validity
  cannot establish the missing conditional-null premise, and the implementation has no
  across-game/596-signal multiplicity control.
- Evidence: `research/EVIDENCE/R2_POPULATION_BOUND_KILL_CHECK.json`; Model-C SHA256
  `9daec869b3e4950945a1a370486e8841874fe9f5e611a7e8638dcdaa2b08b82c`; `2/2` tests pass.
- Classification: theorem-strength evidence against the nontrivial distribution-free population
  extension, not against the fixed-null mathematical e-process.
- Surviving exact label: `model-relative e-process against a fixed hash-locked Model-C reference`.
- Reopen-only-if: a prospectively justified conditional population bound and multiplicity design;
  not Model B, historical `E_*`, or another empirical plug-in score.

## R4 Wave 4 caller-trusting production report — rejected and fail-closed

- Closest prior route: the Wave 3 capability-isolated evaluator. The new report arithmetic was
  materially new, but its first version trusted caller-supplied eligibility and identity hashes.
- Rejected version: `glee_eval/experiments/factorial_report.py` SHA256
  `0fa1011120c32051c248ed88e45cfd1aff8b65406bb12e0d11da8085b69e8cf5`.
- Hostile obstruction: it accepted outcome-selected eligibility; aliased RNG-owner seeds plus
  arm-dependent economic traces; altered episode opponent/nature evidence; invented balanced
  roles; and a six-row custom contract as production evidence.
- Classification: verifier-integrity failure, not a treatment/payoff result.
- Material repair: production and synthetic schemas are now disjoint; future production evidence
  recomputes eligibility, named streams, opponent/nature evidence, exact roles, artifacts, and a
  pre-outcome manifest. Because the language environment is still unselected, the production
  contract authorization pin remains `None` and every payoff contract fails closed.
- Current independent result: verifier-backed exact obstruction at report SHA
  `23cdbe690170b1d7eb598590e43e9bd7833d013019903b6acda7899e3455f270`; see
  `research/AUDITS/R4_WAVE4_EXACT_OBSTRUCTION.md`.
- Reopen-only-if: user selects the receiver environment, all contract inputs are prospectively
  hash-frozen, and a fresh isolated audit passes the exact activated production pin.

## Wave 5A initial rehashable pre-outcome validator — rejected and repaired offline

- Closest prior route: the Wave 4 report verifier, which intentionally had no exact future
  scenario/receiver manifest because the language environment was unselected.
- Rejected implementation SHA: `glee_eval/experiments/preoutcome_manifest.py`
  `6ca804b18fc2c3986f2c21340d594de89657edef5f603551bf09a2b06ca421e3`.
- Hostile obstruction: coherent rehashing could replace same-count scenarios; change Model C,
  support masks, mirrored e-process/language/failure/missingness policies, top estimands/report
  schema, and parsed receiver shape; the validator also initially lacked exact scenario-stream,
  dependency, receiver/provenance, typed-output, and canonical-order reconstruction.
- Classification: implementation/verifier failure, not an outcome and not evidence against the
  2x2 hypothesis.
- Material repair: the fixed contract now binds and reconstructs exact scenario/configuration
  payloads, within-family indices and deterministic scenario seeds, canonical Model-C payload,
  support masks, receiver and source hashes, all mirrored policies, named streams, strict output
  fields, row order, and intent-to-treat admission. A fresh isolated auditor reports `39/39`
  general and `13/13` scenario-seed attacks rejected; production remains blocked by two `None`
  pins.
- Reopen-only-if: an exact receiver and 3,600-row factorization are selected and both production
  hashes are prospectively frozen; then audit the activated version afresh. Rehashing a synthetic
  fixture or setting only one pin is not sufficient.

## Wave 5A controlled receiver execution — blocked, not attempted

- The generic contract/cache/replay/capability infrastructure is implemented, but current project
  evidence supports no named hosted model or local artifact.
- Obstruction: thirteen independent inputs remain user-owned, including immutable identity,
  selection provenance, prompt bytes, visibility boundary, decoding/seeds, parser, failure/cache
  policies, prices/caps, scope, untouched probes, confirmatory design, and a reviewed adapter.
- Classification: environment/authorization obstruction. No receiver was selected, tuned, called,
  or promoted; all mock results are `infrastructure_only_non_evidence`.
- Reopen-only-if: those inputs and spend/external-call authorization are explicit and frozen
  before capability outcomes. Do not choose a receiver because it reacts strongly to the four
  treatment templates or factorial payoff.

## Wave 5B full-family Model-A necessity — narrowed to bargaining

- Closest prior route: the failed Model-B joint opponent formulations. This audit is materially
  different: it scores the deployed independent-marginal policy's next actions and offers rather
  than proposing correlated latent bundles.
- Attempt: advance a sequential Model A for any family whose preregistered residual reproduces on
  acting-model-holdout rows and candidate-reached live paths under the same direction/visibility
  contract.
- Result: bargaining offer undercoverage reproduces in both roles and player-2 MAE also exceeds
  `.08` in both sources. Negotiation and persuasion have large released residuals, but live cells
  are too small, have the opposite direction, or become unidentifiable once hidden values and
  ambiguous text are correctly excluded.
- Classification: a positive necessity result for bargaining, evidence against silently extending
  that result to all families. The frozen next campaign is bargaining-only.
- Reopen-only-if for negotiation/persuasion: an attributable live cell with the required support
  reproduces a released defect under identical role-visible features/parser rules. A released-only
  residual or imputed hidden value is insufficient.

## Wave 5B exact leaderboard-proxy validation — unidentifiable

- Attempt: quantify per-game bias, MAE, correlation, interval coverage, rank agreement and private
  adjustment errors against every existing live batch.
- Obstruction: launch manifests omit the exact agent commit; official per-game percentile/game
  rating/update and opponent adjustment fields were not captured. Confirmation also has one more
  terminal persuasion record than its official game-count increment.
- Surviving diagnostic: two count-reconciled 75-game batches show public-proxy displayed endpoint
  overprediction of about +55.6 bargaining, +125.8 negotiation and +70.0 persuasion points.
- Classification: partial-identification evidence against a confident single-number proxy, not a
  calibrated correction. No ground truth was reverse-engineered.
- Reopen-only-if: a prospective live manifest binds the exact commit and captures official
  per-game scoring plus every exposed adjustment input before outcomes.

## Wave 5B Factorial00 as immediate live-canary candidate — rejected

- Attempt: use the research treatment-off economic backbone as the competition canary because its
  paired 900-scenario mean is +.04757 over Jordan offline.
- Obstruction: the gain is highly family-specific (+.15995 bargaining, +.00895 negotiation,
  -.02620 persuasion), including -.05730 for persuasion seller. Factorial00 is research-only,
  requires frozen artifact injection, and has no competition promotion or live adapter.
- Classification: bounded architecture evidence, not permission to select from unrun treatments or
  deploy the research baseline. The unexecuted canary selects the already operational Jordan.
- Reopen-only-if: a competition-scoped candidate clears an independent ordinary gate and live-safe
  artifact/adapter review. The 900-game diagnostic or a different seed is insufficient.

## Wave 5D Design-A row-independent production inference — rejected pre-outcome

- Closest prior route: the Wave 5C Design-A recommendation of 300 base economic strata crossed
  with two roles and two receiver replicates per family.
- Attempt: justify 3,600 paired rows and exercise the frozen manifest/evaluator/report path without
  inspecting treatment or receiver-capability outcomes.
- Obstruction: the proposed 600 eligible persuasion-seller rows contain at most 300 independent
  base-stratum clusters, but the current report estimates variance from paired row contrasts as if
  the two receiver replicates were independent and the manifest does not enforce a base-stratum
  cluster identifier. In addition, outcome admission retains receiver failure statuses while the
  report requires numeric payoffs and no treatment-blind failure-to-environment/payoff rule is
  frozen.
- Precision result: under the explicitly prospective central grid cell (contrast SD `.20`, ICC
  `.50`, 10% information loss, 80% power, worst two-sided Holm step), A300 has effective N `360`
  and MDE `.03411`. It is not justified for the existing `.0100` practical reference; that target
  would require 3,490 base strata per family under the same assumptions.
- Classification: verifier/statistical-contract failure before production activation, not evidence
  against either treatment. A 12-row local synthetic happy path passed and is labelled
  `infrastructure_only_non_evidence`.
- Surviving recommendation: A300 remains the single prospective design because two receiver
  replicates are needed for a nondeterministic hosted receiver and every evaluated smaller
  A-shaped design worsens precision. Both authorization pins remain unset.
- Reopen-only-if: exact base-stratum/role/replicate factorization is manifest-bound; clustered
  inference and ITT failure-to-payoff handling are implemented; exact rows and both pins are
  prospectively frozen; and a fresh hostile audit passes before outcomes.
