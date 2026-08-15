# Failed and retracted approaches

Append-only record. Do not delete old entries when later evidence changes the interpretation;
append a correction and update `docs/REGISTRY.md` instead.

## Persuasion cold-start exploration — rejected

- Tried: unconditional exploration; exploration only at zero evidence; exploration only when
  there is no transcript channel.
- Exact failures: unconditional concentration 0.649 and breadth 0.625; zero-evidence effect
  +0.0032; no-transcript effect +0.0051, t=+3.36, concentration 0.627, breadth 0.5.
- Materially new retry: must change the learning mechanism or target population, not merely
  rerun one of these candidates with a new seed.

## Negotiation time concession — rejected

- Tried: Boulware time-dependent concession in place of the mostly round-independent offer.
- Exact failures: first defective candidate -0.0054, t=-7.57, including
  `rounds=1|gains_from_trade` at -0.0447; corrected candidate +0.0003, t=+2.11,
  6W/76L/1518T over n=1600, below the 0.0100 minimum effect.
- Materially new retry: must address reach or mechanism beyond the corrected curve; a new seed
  alone is not new.

## Negotiation own-margin offer clip — rejected

- Tried: guarantee our own margin and attach the agent's counter price only while that
  guarantee is active.
- Exact failure: +0.0076, t=+9.46, 117W/0L/1483T over n=1600; failed only
  `minimum_effect` (0.0100 required).
- Materially new retry: requires a prospectively defined gate-policy decision and a changed
  candidate or endpoint declared before measurement. Retrospectively conditioning on the 117
  reached pairs is not valid.

## Negotiation counterpart-value de-bias — rejected

- Tried: correct first asks by measured 1.50x seller markup and first offers by measured 0.75x
  buyer shading.
- Exact failures: +0.0072, t=+7.52, 64W/1L/1535T over n=1600; `minimum_effect` and
  `subgroup_concentration[config_regime]` 0.5951 (maximum 0.5000).
- Materially new retry: must reduce configuration concentration or change the inference model;
  rerunning the same constants is not new.

## Combined negotiation counteroffer path — retracted

- Tried: time concession, own-margin guarantee/counter-price, and counterpart-value de-bias as
  the single coupled mechanism they were diagnosed to be.
- Exact evidence: initial gate seed 4242, n=1600, +0.0109, t=+10.07, 136W/42L/1422T,
  concentration 0.4985, passed. Independent confirmation was declared before execution at
  seed 9999, n=3200; it returned +0.0094, t=+12.49, 233W/94L/2873T and concentration 0.5539.
- Why retracted: confirmation failed `minimum_effect` and concentration, so the initial
  marginal pass cannot support shipping.
- Materially new retry: a changed mechanism with a new preregistered hypothesis; never submit
  the unchanged candidate to another seed hoping for variance.

## Retracted claims from the 14 August session

### Frozen persuasion posterior guarantees zero payoff — retracted claim

- Contradicting evidence: across 13,506 real games, frozen bought in 67.0% of rounds versus
  60.6% informed; decisions agreed 80.1%; mean per-round EV forgone by freezing was +0.0286,
  meaning frozen was slightly better on net.
- Materially new retry: any severity claim must be evaluated against real logged decisions and
  distinguish an accessor defect from its payoff consequence.

### Static agent offer caused the live 6800 counteroffer — retracted claim

- Contradicting evidence: the agent did not attach a counter price, so the adapter fallback
  generated `8000 * 0.85 = 6800`; the proposed concession curve was unreachable from live play.
- Materially new retry: trace the production reader/adapter path end to end before attributing
  a visible live action to agent policy.

### Shrinking a lower evidence bound is conservative — rejected change

- Contradicting evidence: shrinking the lower bound restored an optimistic prior floor and
  broke `test_a_hidden_no_trade_zone_is_now_believable` in the 61% of real configurations with
  a no-trade zone.
- Materially new retry: preserve the direction of one-sided evidence bounds and validate the
  smallest no-trade example first.
