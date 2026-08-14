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

## Applying it

```bash
python -m glee_eval promotion-check --observations runs/<name>/promotion_observations.jsonl \
    --change "bargaining theory anchor" --holdout
```

The gate is a floor, not a ceiling. Passing it means a change is not obviously an artifact;
it does not mean the change is understood. A mechanism that explains *why* the effect exists
is still required, and remains the thing that caught both errors above.
