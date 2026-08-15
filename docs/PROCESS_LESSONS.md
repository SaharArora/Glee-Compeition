# Process lessons

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
