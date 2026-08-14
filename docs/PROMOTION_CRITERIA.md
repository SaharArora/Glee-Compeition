# Promotion criteria

The standard a policy change must clear before it becomes a default. Implemented in
`glee_eval/experiments/promotion.py` and enforced by `python -m glee_eval promotion-check`.

## Why this exists

Every policy change shipped in this repo so far was promoted on a single paired A/B run:
no threshold agreed in advance, no check that the gain was spread across opponents rather
than concentrated in one, and no slice of data withheld from fitting. Two concrete failures
followed from that.

The first debug report described its negotiation finding as *"a confirmed, live bug… not a
testbed artifact"* on the strength of a paired comparison over roughly 33 negotiation games
against hand-picked opponents. It was a testbed artifact. The bargaining time-preference
change then measured as a clear loss (−0.040, t=−5.83) against those same hand-picked
opponents and a clear win (+0.046, t=+6.60) against fitted ones — the same code, opposite
conclusions, decided entirely by who it was measured against.

Neither error was a statistics mistake. Both were the absence of a standard fixed before
the result was known.

## The criteria

A change is promoted only if **every** check passes.

| Check | Default | Reasoning |
|---|---|---|
| `sample_size` | ≥ 200 paired episodes | Below this a 0.01 effect is not detectable, so a pass would be luck. |
| `minimum_effect` | ≥ 0.01 paired mean | Payoffs are normalized surplus fractions, so this is one point of normalized payoff. Smaller than that is not worth the added policy surface even when real. |
| `significance` | paired t ≥ 1.96 | Ordinary two-sided 95%. **Not anytime-valid** — see below. |
| `downside_p5` | ≤ 0.02 regression | The candidate's own 5th-percentile *outcome* must not be materially worse than the baseline's. |
| `subgroup_concentration` | ≤ 0.50 | Share of the total gain contributed by the single best subgroup. Above half, it is a subgroup-specific fix wearing a general change's clothes. |
| `subgroup_breadth` | ≤ 0.40 | Fraction of subgroups where the candidate is worse. Some regression is normal; most is not. |
| `structural_holdout` | required | The evaluation must run on a slice withheld from fitting. |

Subgroups are checked on two dimensions by default: **opponent archetype** and **config
regime**. A change that helps only against `conceding` opponents, or only in
gains-from-trade configs, has to be described that way rather than shipped as a general
improvement.

### Two deliberate choices worth stating

**The downside check is on outcomes, not on paired differences.** The 5th percentile of a
difference distribution is negative for almost any change with variance, so gating on it
would reject everything including changes that are clearly good. What actually matters is
whether the change makes our *bad cases* worse, which is a question about the outcome
distribution: `p5(candidate) ≥ p5(baseline) − 0.02`.

**"Significance" here means the ordinary paired t statistic and nothing stronger.** This is
a fixed-sample check on a comparison declared in advance. It is not an e-process and carries
no anytime-valid guarantee — the agent is named for that idea but does not implement it, and
this file must not be read as having quietly introduced it. Running the gate repeatedly
against the same candidate until it passes would invalidate it, exactly as it would for any
fixed-sample test.

## The structural holdout

Implemented in `glee_eval/population/splits.py`. Two axes, because they answer different
questions:

- **`model`** — partition by the LLM behind each player. A game is held out if *either*
  player is a held-out family, since requiring both would leak held-out behavior into the fit
  slice through cross-family games. With the default 25% key fraction this withholds five
  entire families — `gpt-4o-mini`, `otree`, `otree_LLM`, `llama-3.3-70b`, `mistral-large` —
  that the fit slice never observes, and puts 43.1% of games on the holdout side. Answers
  *does this generalize to an opponent type we did not tune against?*
- **`config`** — partition by configuration. Answers *does this generalize to a configuration
  regime we did not fit on?*

Assignment is by SHA1 bucket of a stable key, never by RNG, so partitions are reproducible
across machines and runs without storing split state. Every fitted artifact records its
`provenance` block, so an evaluation cannot silently claim a holdout it did not use.

## Defect fixes

A gate designed for "should we adopt behaviour B over behaviour A" becomes incoherent when
A is not a policy but a defect. Concluding "do not fix the bug" because the fix helps
unevenly would be the wrong answer, and the obvious way to dodge that is to relabel tuning
changes as bug fixes. So the carve-out is written down and deliberately narrow.

A change may ship despite a failing gate only when **all** of the following hold, and the
verdict is recorded as failing rather than quietly re-run until it passes:

1. The pre-change behaviour is **provably defective against real data**, with the evidence
   stated — not merely worse on a synthetic A/B.
2. The only failing checks are `subgroup_breadth` or `subgroup_coverage`. A failure of
   `minimum_effect`, `significance`, `downside_p5`, `sample_size` or `structural_holdout`
   blocks the change outright, defect or not.
3. The mechanism behind the regressing subgroups is identified and filed as follow-up work.

### Invoked once so far

**Persuasion transcript-accessor fix.** The buy rule read the round quality from a key that
exists only on synthetic transcripts, so on real data it learned nothing and its posterior
stayed pinned at the prior. Condition 1: the agent would have bought **0 of 66,480** real
buyer decisions, while real buyers bought 52.1% and earned +1.016 surplus per purchase.
Condition 2: it passed effect (+0.0160), significance (t=7.25), downside, sample size and
holdout, failing only `subgroup_breadth[opponent_archetype]` at 0.4375 against 0.40.
Condition 3: the seven regressing archetypes are the deceptive end of the honesty
distribution — `deceptive` −0.025, `rational` −0.011, `level_2` −0.009 — because a posterior
learned from a short history over-trusts a seller who lies at a rate the early sample
underestimates. Filed as the next persuasion work item.

## Shadow mode

Some changes cannot be gated at all, and the honest response is to say so rather than
lower the bar quietly.

The persuasion message composer is the first. Nothing in the simulator reads message text --
replacing every template with `"."` moves persuasion payoff by 0.000000 -- so an
in-simulator A/B of a language change measures exactly nothing. Building a message-consuming
opponent calibrated on the same step-3 effects we would be testing would be circular.

So it ships in **shadow**: it decides what it would send and records that alongside what was
actually sent, both with their feature vectors, while the transmitted message stays the
existing template. Real logged games accumulate the only non-circular evidence, and the
change can be gated properly once there are enough of them.

Every shadow record carries `gate_status: "not_gate_passed_pending_real_data"`, so it can
never be mistaken in a log or a report for a change that cleared the real gate the way the
bargaining theory anchor did.

## Changes the gate has rejected

Recording these matters as much as recording the passes. Every change before this one
shipped, which makes a gate look decorative until something is actually turned away by it.

**Negotiation acceptance conditioned on remaining rounds.** The debug report suspected the
`p=0.34` acceptance-at-zero-gain figure of pooling genuine acceptances with end-of-game
closing ones, and the marginal statistics confirmed exactly that: at the same responder gain,
real acceptance runs 0.240 early against 0.468 in the final round, and roughly triples for
small gains.

It was still rejected, on both endpoints:

- **Payoff.** Paired over 1,600 holdout negotiation episodes: +0.0002, t=0.81. Failed
  `significance` outright, which the defect carve-out explicitly may not waive. Almost every
  subgroup showed exactly 0.0000, because the agent consults the response model in only 160
  of 600 episodes — 61.7% of real configs are no-trade zones where it walks away before ever
  pricing.
- **Predictive accuracy**, the endpoint that actually suits a predictor rather than a policy.
  Trained on the fit slice and scored on 41,601 decisions from LLM families never seen in
  training: log loss 0.29400 → 0.29426, Brier 0.08334 → 0.08349. No improvement; marginally
  worse on both proper scoring rules.

The lesson is narrower and more useful than "the hypothesis was wrong". The hypothesis was
right *about the pooled bucket* and wrong *about the model*: the specific key levels already
carry `round_bin`, whose "late" bucket captures most of the effect wherever there is enough
data to reach them. The pooled level only takes over when there is not — so fixing it changed
almost nothing. A true statement about a statistic is not automatically a diagnosis of the
system that computes it.

Kept behind an `include_remaining` flag, defaulted off, so the experiment can be rerun in one
line if the key ladder changes rather than being deleted and rediscovered.

## Applying it

```bash
python -m glee_eval promotion-check --observations runs/<name>/promotion_observations.jsonl \
    --change "bargaining theory anchor" --holdout
```

The gate is a floor, not a ceiling. Passing it means a change is not obviously an artifact;
it does not mean the change is understood. A mechanism that explains *why* the effect exists
is still required, and remains the thing that caught both errors above.
