# Process lessons

## A real parser defect can still fail a payoff promotion gate

The live text persuasion failure was deterministic—free text carried no structured stance, so
the buyer declined every text round—and the candidate parser passed a frozen production replay.
That did not waive the policy gate because interpreting language changes actions. Its first
payoff run passed effect, significance, downside, holdout and breadth, but failed config-regime
concentration. Keep schema correctness evidence and payoff promotion evidence separate; do not
turn a diagnosed input defect into permission to ship a concentrated acting policy.

Transferable process guidance only. Game-specific mathematical and empirical claims belong in
`docs/REGISTRY.md` and `docs/FAILED.md`.

- Group the unit of change by the mechanism diagnosed before measurement; related flags tested
  in isolation can hide a coupled path.
- Declare confirmation sample size, seed, and shipping condition before seeing confirmation
  results.
- A statistically stronger result does not compensate for missing a prospectively chosen
  minimum practical effect.
- Treat a marginal pass after multiple related experiments as a reason for independent
  confirmation, not as permission to ship.
- Check round-one and horizon-one edge cases before trusting any time-dependent curve.
- Trace the production call path before diagnosing the layer responsible for an observed
  action; unreachable code cannot explain live behavior.
- Test confident causal or severity claims adversarially against real logged data in the same
  session.
- Preserve the semantics and direction of one-sided bounds when shrinking or regularizing
  estimates.
- A true marginal statistic does not prove that adding it to a model improves prediction or
  policy.
- Keep concurrent work on shared functions and flags mutually visible through explicit
  registry dependencies.
- A failed gate is durable evidence. Retry only when the candidate, endpoint, or mechanism is
  materially different—never merely with a fresh seed.
- Never run or schedule live/rated play without explicit authorization for that specific
  instance.
- Name the estimand and evidence channel explicitly before treating two posterior summaries as
  interchangeable.
- Compute diagnostics from the current run; historical constants are evidence, not a runtime
  warning.
- When comparing primary and diagnostic metrics, hold the fallback ladder and conditioning
  dimensions fixed so the reported delta isolates only the intended stratification.
- Keep a confirmed symptom separate from a rejected mechanism: evidence may preserve the
  calibration gap while showing that the initially suspected channel mismatch is too rare to
  explain it.
- Predictive calibration evidence and policy-payoff evidence are different gates; improving
  Brier and log loss does not authorize changing an acting threshold or default.
- Even a well-confirmed predictive improvement can have a small acting effect when most paired
  episodes never cross the decision boundary; measure the policy consequence separately.
- Adversarially match or stratify observational cohorts before attributing an aggregate gap to
  a mechanism; include a constructed Simpson-reversal test so config mix cannot silently set
  the sign.
- Even a matched one-step observational association can reverse under trajectory simulation;
  changing an action changes later information and behavior, so only the paired episode gate
  can establish policy value.
- Treat third-party run limits as untrusted until their counting unit is verified against unique
  terminal IDs; concurrency and opponent-ended work can make a documented completion cap exceed
  the user's authorized total.
- Do not attribute a small live/offline mean gap to policy when role, configuration, and opponent
  distributions differ and the live interval still contains the offline target; replicate at
  volume and diagnose conditional cells first.
- When a live adapter can replace or reinterpret an agent action, reproduce that boundary in
  the gate. A policy-only simulator can make the actually reached production path invisible.
- Preserve units between fitting and simulation: a rate measured per same-player action cannot
  be multiplied by global turns. Also measure realized branch reach before attributing an
  aggregate live gap to a broad latent curve difference.
- Make a structural split key identical to the conditioning key used by the fitted model.
  Source-prefixed configuration IDs do not test unseen canonical configurations when the model
  conditions on normalized public parameters.
- Validate the semantics of every fitted endpoint against its runtime consumer before fitting:
  a mean offer is not an opening intercept, accepted surplus is not an acceptance threshold,
  and pooled truthfulness is not P(recommend=yes | quality=high).
- To test joint dependence, compare against independently shuffled parameters from the same
  conditional pool with the same weights and defaults. Beating a stale global marginal sampler
  can come from repaired conditioning or marginals and does not validate correlation.
- Count split clusters and coverage before expensive scoring, while retaining the declared hard
  failure if they are insufficient. A nominal 25% split over 16 models has only four model
  clusters and cannot satisfy a preregistered minimum of five.
- Sparse segment crossings select behavior-rich players and silently turn missing response
  parameters into defaults. Use leak-free decision-level partial pooling and validate all held-
  out decisions rather than claiming population validity from retained crossings alone.
- A descent step is not a convergence certificate. For hierarchical logistic fits, require a
  projected-KKT/stationarity check, treat backtracking stagnation as failure, and disqualify
  nonconverged inner-CV fits before an outer-fold artifact can be accepted.
- A correct convergence certificate can expose an unsuitable solver without refuting the model:
  coordinate-wise descent on a coupled actor/config system may be exact yet too ill-conditioned
  to reach an absolute KKT target. Keep numerical-instrument failures separate from predictive
  failures, and never score an artifact whose training status is unavailable.
- Numerically stable accumulation must also be memory-stable. Materializing every contribution
  for exact summation can turn a sparse matrix-free optimizer into an O(nonzeros) temporary-
  allocation loop; use deterministic compensated or fixed-block accumulation and test peak
  storage before the full corpus run.
- Never accept a serialized `converged` flag as its own proof. Before holdout extraction or
  scoring, independently reconstruct the frozen solver constants, original-coordinate terminal
  KKT certificate, every inner-fold eligibility decision, pooled validation-loss ridge choice,
  and deterministic tie rule. Preserve enough bounded-memory provenance to audit the original
  estimand—zero-sum reconstruction, coefficient ordering, PCG residual/curvature/descent and
  projected line-search records—without reintroducing row-scale temporary storage.
- A bounded-memory computation can still fail when its result graph repeats shared evidence.
  Recursive serializers expand every repeated reference and may also hold the logical tree and a
  complete encoded copy at once. Normalize large audit objects to one canonical owner, use
  verified compact references at high-cardinality leaves, stream atomic output, and test peak
  memory against leaf count as well as numerical row count. Release phase-local state only after
  its last semantic consumer so memory repair cannot silently change the estimator or provenance.
- An absolute objective difference is not a reliable line-search verdict when the objective is
  large: two rounded values can straddle Armijo while differing by only a few representable
  numbers. Declare an ULP-scaled ambiguity band before measurement and use higher precision only
  to reevaluate the identical objective and inequality inside that band. Do not turn higher
  precision into a new step, tolerance, search direction or post hoc acceptance rule.
- A conditional empirical bundle is not automatically a latent type. Segment means combine
  finite-game estimation noise, endpoint missingness and configuration selection; resampling the
  whole row can preserve correlations that are less predictive out of fold than shuffling the
  same conditional marginals. Validate dependence against that same-support shuffle and learn or
  shrink residual dependence separately from marginal conditioning before calling the result a
  joint opponent model.
- Keep a compact verdict separate from high-cardinality scored rows. The exhaustive Model-B
  validator successfully completed, but materializing a sorted 1.86 GB report spent a long final
  phase in JSON encoding and garbage collection before the atomic write. Future validators should
  stream a content-addressed row artifact and atomically write a small summary that records its
  hash; report layout must not change the frozen metrics or expose partial results.
