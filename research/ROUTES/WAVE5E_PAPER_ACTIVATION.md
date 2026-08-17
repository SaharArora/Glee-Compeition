# Wave 5E paper activation preparation

Status: **implementation frozen pending fresh independent audit; no capability or factorial outcome.**

## Decision

Retain **A300**, but reorder the confirmatory family:

1. the language main effect on immutable language-eligible persuasion-seller rows is the single
   confirmatory primary;
2. the model-relative e-process main effect and interaction are key mechanistic secondaries;
3. equal-family all-row effects, negative controls, and every family/role/configuration cell remain
   mandatory secondary reports.

The prospective SESOI is **0.035 normalized eligible-population payoff**. It is not the competition
gate's `0.010`. The judgment is that a smaller effect does not justify 48,000 confirmatory receiver
requests, approximately `$203.17` nominal primary-receiver spend, and a multi-day attended run.
Under the unchanged central planning assumptions (contrast SD `.20`, ICC `.50`, 10% information
loss, 80% power), A300's single-primary MDE is `.02953` and its old three-hypothesis first-Holm-step
MDE is `.03411`; A200's single-primary MDE is `.03617`. Thus A300 can target `.035` under the
central case, while A200 and every evaluated smaller design cannot.

This reordering is prospective and outcome-blind. It is justified by intervention exposure, not a
favorable treatment result: language is rendered and delivered on all 20 rounds of every eligible
episode, while e-process threshold crossing and actual economic action change remain unknown and
may be sparse. The e-process remains scientifically reportable as a secondary model-relative
mechanism; it is not erased or redefined.

## Experimental unit and cluster repair

Each paired row is indexed by `(family, base_stratum_id, candidate_role, receiver_replicate)`. The
four arm episodes reuse that row. The independent inference unit is `(family, base_stratum_id)`.
A300 requires exactly 300 base strata per family and the exact cross product of both candidate
roles and receiver replicates `{0,1}` within every stratum.

The implementation now:

- writes `base_stratum_id`, `base_stratum_hash`, and `receiver_replicate` in evaluator rows and the
  pre-outcome manifest;
- hashes a role/replicate-invariant projection of family, configuration, public parameters,
  source, and opponent parameters without its replicate seed;
- rejects a production cluster unless all four role/replicate cells exist once and share that
  projection hash;
- averages eligible row contrasts inside each base stratum, then computes family means and
  standard errors from those cluster means;
- reports both paired-row `n` and independent-cluster count; episodes, rounds, and requests are
  never sample size.

Synthetic fixtures may use one-row synthetic clusters, remain explicitly nonproduction, and do
not set either production pin.

## Receiver-failure ITT rule

The treatment-blind frozen rule is hash-addressed in
`glee_eval/experiments/receiver_itt.py`. A timeout or malformed output receives its one allowed
retry. A refusal or empty/missing result receives no retry. A final timeout/malformed result is
labelled `exhausted_retry`. Every failure state maps to the legal controlled-receiver decision
`pass` and persuasion buyer action `no` for that round. The ordinary fixed-horizon environment
then continues on the preassigned nature stream and computes its ordinary finite role payoff.

This is deterministic environment behavior, not post-outcome payoff imputation. Every assigned
row remains in ITT. An engine failure that prevents a terminal payoff is a global stop and a
nonreportable study, not an invented payoff or complete-case deletion.

## MDE interpretation

The central A300 Holm-3 MDE `.03410623` means:

- bargaining: `0.03410623 × money_to_divide` raw pie units before timing discount (3.4106 on a
  100-unit pie; 341.0623 on a 10,000-unit pie);
- negotiation: `0.03410623 × product_price_order` raw price/value units (3.4106 when the order is
  100), with role sign and no-trade mass retained;
- persuasion: `0.03410623 × product_price × total_rounds` raw terminal payoff. For a 20-round
  seller this is `.68212` net additional sale-equivalents, or a 3.4106-point purchase-rate shift.

If an effect exists only for persuasion candidate-seller rows, equal weighting across three
families and two roles dilutes `.03410623` to `.00568437` in a full-GLEE aggregate, before any
additional nontext-configuration prevalence factor. GLEE's documented local shadow mapping is
`rating = 2000 + 8000 × (within-configuration-role percentile - .5)`, but payoff units do not
identify percentile movement without a prospectively frozen reference-CDF density. No rating or
rank improvement follows from the MDE alone.

Language is structurally exposed on 20/20 eligible rounds, but actual receiver-decision change is
unknown before outcomes. Capability passage requires generic text-only changes in at least 5/25
states per receiver seed; that is a plumbing threshold, not the treatment's exposure estimate.
For either mechanism, if only a proportion `q` of eligible scenarios is actually affected, the
conditional affected-scenario effect needed to attain `.03410623` is `.03410623/q`: `.68212` at
5%, `.34106` at 10%, `.17053` at 20%, `.13642` at 25%, and `.06821` at 50%.

The e-process changes a baseline `no` to `yes` only after `E >= 20`. Its `1/20=.05` single-stream
crossing bound applies only if the fixed model-relative null holds; it is not an alternative
exposure forecast. If merely 5% of eligible 20-round seller episodes were affected, the MDE would
require about 13.64 net extra sales per crossed episode, illustrating why it is secondary rather
than co-primary.

## Wall-clock reconciliation

A300 has 48,100 nominal requests including capability and 96,200 attempts at the retry ceiling.
At 32-way saturated concurrency and 30 seconds per attempt, exact receiver service is 12h32m
nominal and 25h03m30s at the retry ceiling, excluding orchestration and episode/report overhead.

The prospective full-study wall cap is therefore **32 hours**, leaving 6h56m30s beyond the exact
worst receiver-service envelope. The wall cap takes precedence: at 32 hours the supervisor stops
new submissions, cancels pending requests, checkpoints atomically, and marks an incomplete study
nonreportable. It never replaces missing rows. This is a resource contract, not authorization to
start the study.

## Remaining blockers

- a fresh independent hostile audit must issue GO for cluster identity/inference, ITT execution,
  MDE evidence, adapter security, source hashes, and dependency lock;
- the protected API key file is absent, so the capability route has not run;
- the exact A300 scenario rows, production manifest root, and both production pins remain unset;
- a capability PASS would certify only the frozen receiver route and would not authorize the
  full study or set either pin.

The deterministic evidence is generated by
`python -m glee_eval.experiments.wave5e_paper_activation` and committed separately as
`research/EVIDENCE/WAVE5E_PAPER_ACTIVATION.json`.
