# Research failures and closed routes

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
