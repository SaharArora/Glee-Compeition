# R4 — paired factorial evaluation

## Wave 2 implementation and hostile verdict

Status: **blocked for active-treatment scoring; usable only as an inert-parity
canary and paired-scenario constructor.**

Wave 2 added `glee_eval/experiments/factorial.py`, a four-arm row surface with
one frozen scenario per row, balanced roles, arm-invariant support and eligibility,
named candidate/environment/opponent seeds, fixed arm order, immutable manifest
hashes, factorial contrasts, and a hard `require_inert_parity` mode.  The seven
requested canaries pass: four no-op wrappers, extra treatment draws on an isolated
stream, inert-language zero effect, four-way scenario/role/mask parity, arm-order
invariance, label-stripped parity, and a contaminated fixture rejected in inert mode.

The independent hostile audit found that this is not an active-treatment isolation
certificate.  With `require_inert_parity=False`, the same language fixture can consume
the economic RNG and is accepted because the evaluator records declared seeds, not
capability-separated RNG use or realized draw traces.  It produces nonzero effects in
4 of 12 synthetic rows; the first spurious language main effect is approximately
`-0.05`.  This is an evaluator failure, not a treatment result.

The exact obstruction and reproduction are version-bound in
`research/AUDITS/R4_FACTORIAL_VERIFICATION.md`.  No payoff study is eligible.  A
future repair must enforce stream capabilities/traces during active treatment and add
the frozen estimand/Holm report validator; another inert-parity test or seed is not a
material repair.

## Wave 1 kill-check

Status: candidate obstruction; no treatment result has been measured.

## Exact claim tested

The existing offline evaluator can certify that four frozen wrappers see the same
scenario, role, opponent draw, support mask, and named random-number substreams, and
that each arm differs only on its declared treatment surface.

No close prior route. Existing promotion work establishes two-arm payoff pairing,
not four-arm treatment-isolation or factorial estimands.

## Cheap kill-check

At revision `bce578597dbfacf2ebca38399edb41a5dde2f936`,
`glee_eval.experiments.ab.run_paired_ab` samples one scenario and reuses it in its two
episodes. A 60-scenario adversarial parity check with two independently instantiated
`RandomLegalAgent(seed=7)` instances produced exactly zero payoff differences. This
supports the narrow scenario-pairing claim.

The stronger factorial claim fails at the evaluator boundary:

1. The entry point accepts exactly two factories and emits only baseline/candidate
   payoff. It has no four-arm row, factorial contrast, language-eligibility field,
   or Holm-adjusted report.
2. Each agent is instantiated once and then reused across all scenarios. The runner
   provides no named per-scenario/per-surface RNG substreams and no state snapshot or
   reset certificate.
3. The evaluator records no action-level treatment-isolation certificate. It cannot
   reject an arm whose wording logic consumes the economic RNG stream and thereby
   changes a recommendation, offer, or acceptance decision outside the declared text
   surface.
4. Optional baseline predicates are arbitrary callables over the live baseline object.
   The evaluator does not enforce that they are pure, so a predicate can mutate only
   the baseline before the next paired scenario.

`tests/test_r4_pairing_kill_check.py` supplies an executable counterexample. A
purported wording-only wrapper consumes one extra draw before selecting the same
economic recommendation. On an otherwise fixed persuasion scenario the current
runner reports a normalized payoff difference of `+0.125`; it does not diagnose the
RNG contamination. That number is not a language effect.

## Verdict

The current two-arm runner has real scenario pairing, but it is not an executable
certificate for the frozen four-arm study. R4 remains active with an exact
implementation obstruction; no outcome or mechanism inference is authorized.

## Decisive next test

After R1 freezes the baseline interface and R2/R3 freeze or rule out their treatment
surfaces, add an isolated four-arm runner that:

- materializes one immutable scenario manifest and replays its hash in all arms;
- assigns named, arm-invariant RNG substreams for economic policy, opponent/nature,
  language, and evidence updates;
- derives support and language eligibility once from pre-treatment scenario fields;
- records action/transcript hashes and asserts that every non-treatment field is equal
  under single-factor toggles;
- emits all four payoffs in one row and reconstructs the three frozen contrasts,
  family/eligible cells, intervals, and Holm correction from those rows; and
- rejects rather than scores a contaminated row.

The smallest acceptance certificate is a four-wrapper off/off byte-parity fixture plus
the RNG-contamination counterexample above becoming a hard evaluator rejection. The
final 3,600-scenario study is not eligible until that certificate is verifier-backed.
