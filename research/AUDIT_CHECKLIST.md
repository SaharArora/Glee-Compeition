# Audit checklist — revision 1

This checklist is append-only for newly discovered failure modes. Candidate audits bind
to the exact revision used.

## Universal

- Exact commit, data/artifact hashes, command, seed, sample size, and claim are present.
- No held-out identities, configurations, actions, outcomes, or future transcript fields
  enter fitting, eligibility, or treatment selection.
- Paired arms share scenario, role, opponent, support mask, and named RNG substreams.
- Missingness, censoring, and language eligibility are pre-treatment and arm-invariant.
- Treatment-off wrappers are action- and transcript-identical to the frozen baseline.
- Every expensive job has a route, input manifest, bounded stop, log, atomic output, and
  small certificate. A live PID or quiet terminal is not progress evidence.
- Negative and failed candidates remain immutable; no seed/threshold/prompt retry is
  called materially new.

## R1 — baseline

- No heuristic e-process gates or language intervention remain when treatments are off.
- All four wrappers produce identical actions and state on adversarial fixtures.
- Production and offline adapter paths consume the same agent output rather than fallback.
- Baseline artifacts and structural holdout are valid, hash-locked, and verifier-backed.

## R2 — e-process

- Filtration, null, alternative, likelihood ratio, nuisance handling, and stopping rule are
  explicit.
- Supermartingale/e-process validity is a mathematical result under the stated composite
  null; simulation is only an adversarial check.
- Optional stopping, zero/near-zero likelihoods, adaptivity, dependence, and numerical
  clipping cannot inflate evidence.
- Crossing simulations under null include adversarial and misspecified cases.

## R3 — language

- The evaluator and opponent actually receive text in every claimed eligible family/cell.
- Text can causally affect the receiving policy; a text-blind simulator is labelled a
  feasibility obstruction.
- Message generation cannot leak hidden values, future actions, treatment assignment, or
  outcomes.
- Language treatment cannot directly change numeric economic actions or RNG streams.
- Observational live-message associations are not treated as causal treatment evidence.

## R4 — factorial evaluation

- Four arms differ only on their declared treatment surfaces.
- No arm changes seeds, draw order, opponent/config selection, support filtering, horizon,
  role balance, terminal capture, or numerical tolerances.
- Overall and language-eligible estimands, family cells, interaction, uncertainty, and Holm
  correction are reproduced from paired rows.
- Failures, nonreportable cells, and treatment contamination are terminal findings, not
  silently pooled away.

## R5 — competition champion

- Research wrappers are not merged into the unrestricted champion without normal competition
  gates and confirmations.
- Live adapter parity, strict cap, fresh output directory, full terminal capture, and launch
  manifest are verified before authorized rated play.

## Wave-1 additions

- Mutual equality among all wrappers does not certify the off baseline; compare against an
  independently specified treatment-free economic core.
- Every treatment uses a named RNG substream. Consuming wording/evidence randomness cannot alter
  the economic-policy stream in the same or a later scenario.
- Diagnostic predicates and eligibility functions are pure over immutable pre-treatment state;
  they may not receive a mutable live agent instance.
- Message delivery and receiver consumption are separate audited boundaries. A delivered string
  read only as a pre-existing structured stance is not a language-responsive cell.

## Wave-2 additions

- In active-treatment mode, declared stream names and equal seeds are insufficient. The
  evaluator must fail closed when treatment code consumes the economic, opponent, or nature RNG.
- An inert-parity equality check cannot be the only contamination detector because a legitimate
  treatment may change actions. Active-mode provenance must distinguish intended treatment
  mediation from direct cross-stream consumption.
- Factorial reports reject duplicate scenario identities, missing mandatory cells,
  nonreportable estimands, and a Holm decision that cannot be reconstructed from paired rows.
- A mathematically valid e-process certificate is scoped to its declared conditional null and
  multiplicity design; it is not evidence that the null describes economic opponents.
- Empty candidate-language-to-responsive-receiver cells are reported as an identification
  obstruction, never as a zero language effect.
