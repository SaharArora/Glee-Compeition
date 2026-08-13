# Debugging Pass Report

Follows `POST_GAP_FIX_REPORT.md`. That report's task list was re-verified rather than
trusted, and two of its headline findings did not survive. Tests went 41 → 130.

Commits: `76e57ae` `83fea94` `386d070` `357b595` `8ee828b` `f17f5af` `718edd2` `c390bd3`
`a5c2eaf` `6612d45` `c201e8c`.

---

## 1. What didn't hold up

**The previous report's #1 negotiation finding was ~95% a metric artifact.** It ranked
`smoke_runs_show_under_aggressive_negotiation_outcomes` (81% of rows) as the top negotiation
cause. `_episode` scored regret against `max(candidate, opponent, 0.5)` — and 0.5 is not a
payoff obtainable in a negotiation config with no gains from trade, where the ceiling is 0. So
walking away correctly was charged 0.5 regret and then labelled UNDER_AGGRESSIVE. Against
config-derived benchmarks, negotiation UNDER_AGGRESSIVE labels drop from 37 to 2 and mean
regret from 0.326 to 0.090. The same correction shows **persuasion is by a wide margin the
worst family** (regret 0.080 → 0.368), which the old self-referential persuasion reference had
hidden entirely. The priority ranking in that report is inverted.

**The previous report's response-model finding also does not survive.** It reported the trained
model costing −0.040 payoff per game (t=−3.47) and called it "a confirmed, live bug… not a
testbed artifact". It was a testbed artifact. Measured against the fitted opponent population on
real configs, the same confounded model *helps*: +0.0066 (t=+3.00). I also over-claimed the
mechanism — I predicted deconfounding would stop the agent asking for the whole surplus, and it
does not (details in §3.4).

Both errors have the same root cause, which is the thing this pass was really about: every
measurement in that report was taken against invented opponents playing invented configurations.

---

## 2. Found independently, not on any list

**2.1 — The synthetic harness leaked private values to both players.** `runner._state` handed
every policy the whole scenario config, so `seller_value`, `buyer_value`, `delta_1/delta_2`, `p`,
`v` and `c` were visible to both sides regardless of the game's information structure. About 49%
of real bargaining and negotiation games are `complete_information=False`, so roughly half the
benchmark was being simulated as a complete-information game. Worse, the agent's
`_negotiation_beliefs` read `public_parameters.get("buyer_value")` as a fallback — it *depended*
on a leak that will not exist in a real submission. Root cause: correct filters
(`ingest.public_parameters`, `ingest.visible_private_parameters`) already existed and were used
for real data; the synthetic path just never called them. Cost of removing the leak, paired over
150 identical scenarios: −0.0143 negotiation payoff (t=2.79).

**2.2 — The agent was completely blind to bargaining discount factors.** Neither agent
referenced `delta_1`/`delta_2` anywhere; hiding versus showing them changed measured bargaining
payoff by exactly 0.0000. In alternating-offers bargaining the equilibrium split is determined
entirely by those two numbers, and 75% of the 33,739 real games have asymmetric ones. The offer
share was also hard-clipped to `[0.50, 0.72]`, so the agent structurally could not concede below
half even in configs where its equilibrium share is 0.000.

**2.3 — Sixteen opponent archetypes were cosmetic.** `sample_opponent_spec` always supplied every
parameter, so `policies.py`'s archetype-specific defaults (`_target_share`, `_honesty`, `_trust`)
were dead code. Archetype had *no* effect on negotiation or persuasion behavior and only a
marginal one on bargaining — every `by_opponent_archetype` breakdown ever produced was 16 labels
on identically-distributed policies.

**2.4 — Persuasion rates were applied as thresholds, not probabilities.** A seller lied on every
low-quality round iff `honesty < 0.5`; a buyer bought on every recommendation iff
`trust >= 0.35`. That turns a population with a measured 78% obedience rate into a mixture of
always-buy and never-buy opponents.

**2.5 — Three crashes and a logic bug reachable only from malformed state.** A `None` horizon or
round raised TypeError and killed the decision; one non-dict transcript entry raised
AttributeError. And the persuasion buyer read the seller's recommendation as
`visible_transcript[-1]`, so any trailing row made it read as absent and defaulted to "no". None
of these arise from our own runner, which is exactly why they survived — the test suite and a
200-game tournament only ever feed the agent well-formed state.

**2.6 — The shadow-score reference was computed with a different payoff function than the
episodes it scores**, once the negotiation clamp was removed. Fixed by re-ingesting; the
reference now contains 1,908 negative real payoffs (2.8%) that the clamp had been hiding.

---

## 3. What changed, and how it was verified

### 3.1 Measurement integrity (these gate everything else)

| Fix | Verification |
|---|---|
| Information hiding via the existing ingest filters | 5 of 6 new assertions failed before, all pass after |
| Regret against config-derived benchmarks (`glee_eval/theory/`) | SPE verified against Rubinstein: common delta, long horizon → 1/(1+delta) |
| `terminal_negotiation` clamp removed | Accepting below your own value now scores negative and is distinguishable from exiting |
| Opponents fitted from 1.19M real events | Every hand-picked range was wrong (table below) |
| Configs sampled from the real catalogue | No-trade-zone rate 0.607 vs real 0.612; all 16 delta pairs present |

Fitted versus invented opponent parameters:

```
bargaining accept_threshold  real 0.41-0.50   was U(0.30, 0.55)
bargaining target_share      real 0.49-0.66   was U(0.48, 0.78)
bargaining concession_rate   real -0.05-0.12  was U(0.00, 0.08)
negotiation concession_rate  real 0.01-0.30   was U(0.00, 0.08)
negotiation accept_margin    real -0.10-0.45  was U(0.00, 0.08)
persuasion honesty           real 0.70-1.00   was U(0.20, 0.95)
persuasion trust_prior       real 0.30-1.00   was U(0.10, 0.90)
```

Real opponents are pickier, concede ~4× faster, are far more honest and far more trusting than
the ones every prior measurement was taken against. Real concession rates also go *negative* —
players harden over rounds — which the old non-negative range could not express.

Configs were wrong in four independent ways: `max_rounds` was 6 (real: 12 or 99 for bargaining;
10, 30 or **1** for negotiation — 10,823 real negotiation games are single-round ultimatums),
`complete_information` was always True, `buyer_value` was drawn as `uniform(seller_value, 1.25)`
so a no-trade zone never occurred, and values were continuous while the real grid is discrete.

**This resolves H1.** Coverage lookups, before → after: `exact` 0 → 162, `coarse` 56 → 352, mean
coverage 0.9932 → 0.9216, out-of-support decisions 0.3% → 7.4%. The signal is no longer
saturated, so the Gap 2 coverage term can bind and the counterfactual trigger fires on real gaps.

### 3.2 The measurement that justified itself

The delta-awareness change **reverses sign** depending on who the opponent is. Paired over 800
bargaining episodes across the real delta grid:

| Opponents | Effect | Agreement rate |
|---|---|---|
| Hand-picked | −0.040 (t=−5.83) | 0.986 → 0.871 |
| Fitted real population | **+0.046 (t=+6.60)** | 0.641 → **0.752** |

I shipped it disabled on the first measurement and enabled it on the second. The negative result
was the artifact: hand-picked opponents accepted anything above a `U(0.30, 0.55)` threshold, and
the delta-blind constants of 0.52–0.58 sat right on top of that range, so the flat policy was
fitted to invented behavior.

Worth recording plainly: **absolute performance against calibrated opponents is far lower** than
against invented ones (bargaining mean payoff 0.269 vs 0.469; agreement 0.641 vs 0.986). Real
opponents are materially harder.

### 3.3 The outside option (H3)

Checked upstream before implementing: `final_value = product_price_order * seller_value` and the
family has no discounting, so `SellToJhon`/`BuyFromJhon` are worth exactly zero surplus — the
same as running the clock out. **This is a fidelity fix, not a payoff win**, and the previous
report's framing of it as a likely gain was optimistic. It matters because 19.2% of real
decisions are an action our action distribution could not contain.

The larger fix was the belief behind it: `_negotiation_beliefs` inferred the counterpart value as
`max(prior, observed_prices, own_value + 0.12)`, using the prior and an arbitrary +0.12 as
*floors*, so as a seller the agent could never believe the buyer valued the good below 1.08 — and
therefore never believed a no-trade zone existed, in the 61% of real configs where one does. Now
an evidence bound. Result over 400 real configs: 86% of no-trade-zone games end on the outside
option (real population: 88%), mean payoff exactly 0.0000, zero negative payoffs.

### 3.4 The response model (H4) — partly a correction of my own claim

The surface shape *is* fixed and verifiable. Before, acceptance rose with price across the whole
working range (0.008 at 0.60–0.65 up to 0.228 at 1.05–1.10), which is causally backwards. Keyed
on the responder's own gain it is monotone with a sharp discontinuity exactly at the
individual-rationality boundary: p ≈ 0.001–0.04 below the responder's own value, jumping to 0.34
immediately above.

But the behavioral prediction was wrong. I claimed the rising curve pushed the argmax to the
ceiling and that deconfounding would stop it. It does not — the agent still asks for ≥95% of the
surplus on 35% of offers (was 31%). Under the corrected surface that genuinely *is* the argmax,
because the elasticity is low: giving the responder half the surplus lifts acceptance only from
0.34 to 0.61 while halving our payoff. Payoff evidence for the change is neutral (+0.0015,
t=+0.66); the case for it is that the surface no longer makes a claim the data cannot support.

---

## 4. Standard pipeline against real data

`--games 200 --search-population 50 --search-generations 3`, real configs, calibrated opponents.

```
TOURNAMENT            agreement_or_sale_rate: 0.795
  bargaining   n=69  mean=+0.4850  [+0.4794, +0.4906]  median=+0.5000
  negotiation  n=56  mean=+0.0927  [+0.0576, +0.1278]  median=+0.0000
  persuasion   n=75  mean=+0.4285  [+0.3292, +0.5279]  median=+0.3500

PROBES        1000 probes, legal_action_rate 1.0, format_failure_rate 0.0

COVERAGE      decisions=2104  out_of_support=156  mean_coverage=0.9216
              bucket_levels: exact 162, coarse 352, family_role_round 1590

TRIGGERS      adversarial ran x3      counterfactual ran x1, skipped x2
              long_horizon skipped x3 policy_optimization ran x1
              rare_type ran x2                      <- all five now reachable

SHADOW        overall_displayed_rating 1413.5
  bargaining   payoff +0.4854  pctile 0.6043  rating 1540.3  levels {exact: 71}
  negotiation  payoff +0.0895  pctile 0.5638  rating 1368.1  levels {exact: 58}
  persuasion   payoff +0.4369  pctile 0.4848  rating 1332.1  levels {coarse: 30, family_role: 47}
```

Shadow scoring resolves at the `exact` bucket level for the first time — the config catalogue
pays off in the scoring path as well as the coverage path. Negotiation's median payoff of 0.0000
is correct, not a failure: 61% of real configs have no gains from trade, where 0 is the ceiling.

This run also surfaced a defect in my own work: 149 `budget_exhausted` requests, 140 of them for
one persuasion bucket, because the budget check ran before the bucket was recorded. Fixed, and
the budget raised from 3 to 8 (3 was sized when a run produced 6 out-of-support decisions).

---

## 5. Couldn't verify, or verified only partially

- **Whether the official metric clamps negative negotiation payoffs.** I removed our clamp
  because it made value destruction indistinguishable from walking away, and because bargaining
  and persuasion never clamped. I could not confirm what the private leaderboard does.
- **Whether `reference_payoff = max(candidate, opponent, theory)` is the right composite.**
  Including `opponent_payoff` makes regret partly a relative measure, not purely distance from
  achievable. Defensible, but it is why the anchor-on run shows higher payoff *and* higher regret.
- **Persuasion's ceiling.** I use `p*(v-1)`, the truthful-sender benchmark, deliberately rejecting
  a perfect-foresight bound that would charge the buyer for information it never had. Whether
  that is the right benchmark against a strategic sender is unresolved.
- **Whether p=0.34 acceptance at zero responder gain is real.** It most likely pools
  closing-round acceptances with genuine ones. This is the single most load-bearing unverified
  number in the agent's negotiation policy.
- **Archetype bands are an assumption, not a fitting.** Mapping `aggressive_extractor` to the
  0.80–0.98 quantile window is a stipulation. The learned latent-type model (Model B) stays
  deferred, so which real players cluster together is still unmeasured.

---

## 6. Is submitting reasonable yet?

**Not yet — but for one specific reason, and it is no longer an architectural one.**

What is now sound: the agent emits legal, parseable actions on 1000/1000 real-data probes and
survives every malformed-input probe; measurement is taken against real configurations and
opponents fitted to real behavior; regret is measured against benchmarks a player could actually
achieve; all five simulation triggers are reachable and every decision they make is in a ledger;
information hiding matches the real game; and the agent no longer depends on a leak that will not
exist at submission time.

What blocks it: **persuasion is the weakest family and we have not touched its policy.** It
carries the lowest shadow percentile (0.4848), the worst corrected regret (0.368 against 0.198
bargaining and 0.090 negotiation), and the only IR violation observed. Every fix this pass landed
was in measurement, bargaining or negotiation. Submitting now would mean submitting with the
worst family untouched and known to be worst — the previous report ranked it third and was wrong.

The honest summary is that this pass fixed the instruments and two of three game families, and in
doing so proved the instruments had been wrong enough to invert the previous priority list. The
next pass should assume the same is possible again, and should start with persuasion:

1. **Persuasion policy against the corrected benchmark.** Compare the agent's break-even rule
   against real buyer accept rates conditioned on `(p, v, c, recommendation)`. Real-data analysis,
   no simulation.
2. **Condition negotiation acceptance on remaining rounds** before trusting the argmax that
   currently asks for ~all the surplus (§3.4).
3. **Re-run the H1–H6 list from the previous report**, since two of six were already invalidated
   by fixing the instruments and the rest were prioritized using the same broken metric.
