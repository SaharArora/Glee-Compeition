# Post-Gap-Fix Report

Session scope: verify section 5 of the handoff doc, fix the two gaps in section 6, re-run the
standard pipeline against real GLEE data, and report back. Nothing on the deferred list in
section 2 was built.

Commits: `2b794a2` (gap fixes), `beb37d1` (audit projection), `699f324` (coverage provenance).

---

## 1. Verification: what did not hold up

Section 5 was accurate on almost everything I checked — the four-layer structure, the
`exact → coarse → family_role_round → family_action` fallback ladder with
`min_action_support=20`, the response model's binned table with `alpha=5.0` / `min_support=50`,
`ResponseEstimate` and `ood_penalty = 1 - support_quality`, `population_structure.segments`
keyed `family|config_id|role` with its four `latent_type_signal` fields and its explicit
"not learned embeddings" note, both theory-residual definitions, the agent's four modes and
four-part EXPLOIT gate with the stated defaults (2.1 / 0.18 / 0.30), the absence of any LLM
call, `run.py`'s stage order, `simulation_trigger` provenance threading, the
`policy_optimization` OPE-lite placeholder, and the `eval/` and `audit/legacy.py` shims.

Seven things did not hold up.

**1.1 — Gap 1 is three dead triggers, not one.** The doc singles out
`counterfactual_simulation` as unreachable and implies the other four are wired. In fact
`rare_type_simulation` and `long_horizon_simulation` are *also* never called from anywhere and
have no tests. Only `policy_optimization_simulation` and `adversarial_simulation` were
reachable, so the "five named triggers" were two-of-five live. I wired `counterfactual` as
instructed and left the other two dead rather than expanding scope — flagging, not fixing.

**1.2 — The dataset is ~4x smaller than the doc says.** The doc's "~128k bargaining, ~130k
negotiation, ~52k persuasion game directories" are *file* counts: each game directory holds
exactly four files (`config.json`, `game.csv`, `log_player_1.csv`, `log_player_2.csv`), and
`find work/GLEE/Data/llm_vs_llm/bargaining -type f | wc -l` returns 128,172 = 32,043 × 4.
Actual game directories: 32,043 bargaining, 32,403 negotiation, 13,021 persuasion under
`llm_vs_llm`, plus 3,405 under `human_vs_llm`. Total ingested: **80,872 games /
1,188,434 events**.

**1.3 — The audit could not run on the full dataset at all.** `audit_processed` materialized
every event, which is ~21 GB of Python objects for 1.19M events (measured by extrapolating a
60k-event load), against 32 GB of RAM. This is not mentioned anywhere, which means the audit
had never been run against full real data before this session. Fixed in `beb37d1` — see 2.3.

**1.4 — `identity.composition` double-counts.** The audit reports
`human_labeled_games: 3405` and `llm_labeled_games: 80872`, which sum to more than the 80,872
total. Cause: `llm_labeled_games` counts games whose `source` contains `"llm"`, and the human
source directory is named `human_vs_llm`. So all 3,405 human games are counted as LLM games
too. Population composition is not currently legible as reported.

**1.5 — One of the agent's response-model guards can never fire.**
`jordan_strategic.py` guards on `estimate.key == "__global__"` in three places, but
`runtime.EmpiricalResponseModel.estimate` returns `key="implicit_global"` when it falls through
to the family global rate. The intended global-fallback rejection therefore never matches on
that path. Behavior is still safe because the adjacent `support_quality` guard catches it
(`support_quality` is 0.0 on that path), so I did not change it — but the code reads as if it
has a check it does not have.

**1.6 — `min_support` defaults disagree.** `runtime.py` defaults to 30, `train.py` to 50. The
trained artifact carries its own value so the runtime uses 50 in practice. Cosmetic.

**1.7 — Red-team episodes bypass the coverage gate.** `adversarial_simulation` delegates to
`search_failures(agent_spec=...)`, which loads its own agent, so adversarial episodes never
receive the injected gate. I left this deliberately — red-teaming should not consume the
counterfactual dispatch budget — but it is an asymmetry to be aware of when reading the
coverage ledger.

---

## 2. What changed

### 2.1 Gap 1 — wiring the counterfactual trigger

New `glee_eval/simulate/coverage_gate.py`. `CoverageGate` reads the audit support index and is
the only path from an out-of-support decision to a targeted simulation.

Judgment calls:

- **The agent does not hold a dispatcher; the dispatcher injects a gate.** `build_agent()` on
  the dispatcher loads the agent and calls `attach_coverage_gate` if it exists (duck-typed, so
  `my_agents/baseline.py` and the built-in agents are unaffected — confirmed by the control run
  recording zero verdicts). This keeps the agent a pure decision function and avoids the
  agent-owns-dispatcher / dispatcher-owns-agent ownership tangle.
- **Hook point is `_action()`**, the single place where every family's action is finalized. One
  wiring point covers bargaining, negotiation and persuasion, and it is literally "about to
  commit to an action".
- **Re-entrancy protection was mandatory, not defensive.** The cycle is
  `counterfactual_simulation → run_episode → agent.decide → request → counterfactual_simulation`.
  The guard lives on the dispatcher (`counterfactual_available()`) so every caller is protected,
  and the gate checks it before spending budget. It fired for real in the production run — the
  first ledger line of `post_gap_fix_baseline` is
  `counterfactual / skipped / "Already inside a counterfactual simulation."`
- **Hard budget plus dedup, with every drop recorded.** 200 games × ~9 candidate decisions would
  otherwise spawn hundreds of 25-game simulations. The gate dedups by
  `(family, role, action_type, action_bin)` and caps dispatches at 3 per run. Deduplicated and
  budget-dropped requests are written to the ledger with their status, so the run never silently
  under-covers.

Runs now write `simulation/coverage_summary.json`, `coverage_requests.jsonl` and
`coverage_verdicts.jsonl`.

### 2.2 Gap 2 — the two support signals

I took the second option the handoff doc offers: **keep them separate, with the reason stated**
— but the substantive half of the fix is that the audit support index now reaches a decision it
previously did not touch at all.

The split is by question asked:

| Signal | Question | Scope | Governs |
|---|---|---|---|
| Audit support index (`CoverageGate`) | "Do we have real data about this situation?" | Context-level; shared with dispatcher and negotiation diagnostic | Whether the agent may escalate to EXPLOIT; which decisions get flagged for counterfactual simulation |
| Response model `support_quality` | "How tightly is this specific offer bucket estimated?" | Bucket-local to one binned table | Weighing candidate numeric values against each other |

The rationale is written into the agent's class docstring so it is a decision on the record
rather than an unexamined inconsistency.

Mechanically: `_counterfactual_uncertainty` now takes a coverage argument and adds
`coverage_uncertainty_weight * (1 - context_score)` to its in-game term, so the EXPLOIT gate's
`max_counterfactual_uncertainty` ceiling consumes real empirical coverage. A **missing index is
treated as neutral, not as zero coverage** — otherwise a data-less run would become uniformly
paranoid, which would be the wrong inference from "we have no data source".

This needed a new lookup: `support_lookup` requires a candidate action to derive an action bin,
but the control decision happens *before* an action exists. `context_support_lookup` scores the
context from the resolved bucket's observation count and density only. It shares
`_resolve_support_bucket` with `support_lookup`, so there is genuinely one index and one fallback
ladder, not two parallel implementations — a test asserts both resolve the same `bucket_key`.

### 2.3 Two changes beyond the two gaps

- **Audit event projection** (`beb37d1`), necessary to run step 7.3 at all. `read_audit_events`
  streams and keeps only the fields the audit reads, replacing `transcript_so_far` with a
  length-preserving placeholder — the audit uses that field only through its presence rate, never
  its contents. Peak drops from ~21 GB to **7.7 GB**, runtime 114 s, with no change to any
  reported figure. The reduction is recorded in `audit.json` under `event_projection`, and
  `--no-project-events` audits the raw records.
- **Coverage provenance** (`699f324`), fixing an auditability defect in my own work: verdicts
  from agents running *inside* a counterfactual probe were being pooled with policy-run verdicts.
  Every verdict and request now carries `nested_in_counterfactual`, and the summary reports
  `bucket_level_counts` — which is what made finding 4.3 below visible without hand computation.

### 2.4 Tests

`tests/test_coverage_gate.py`, 19 tests. Both required paths are covered at two levels — gate
(`test_action_outside_support_dispatches_counterfactual` / `test_action_inside_support_does_not_dispatch`)
and dispatcher (`test_out_of_support_action_runs_and_is_logged` /
`test_in_support_action_is_skipped_and_logged`, both asserting the ledger status). Also covered:
dedup, budget exhaustion, re-entrancy refusal, gate injection, missing-index neutrality,
agent-tags-its-actions, agent-unaffected-without-index, and the Gap 2 uncertainty behavior.
Full suite: **41 tests, all passing** (was 22).

---

## 3. Real-data pipeline results

Real GLEE cloned and ingested; nothing synthetic is substituted anywhere below.

| Stage | Result |
|---|---|
| Ingest | 80,872 games / 1,188,434 events (7m54s) |
| Dataset audit | `verdict: empirical_pilot_dataset`, `blockers: []` |
| Support index | 20,614 buckets, 13,528 (65.6%) low-coverage |
| Response model | 459,157 examples (92,823 barg / 96,214 nego / 270,120 pers); 7,332 population segments; 729,277 events skipped |
| Probes | 1,000 probes, `legal_action_rate: 1.0`, `format_failure_rate: 0.0` |

`strategy_recommendation.verdict` is `empirical_pilot_dataset` with **no blockers** — all three
families present, private state present, message text present, model identity present. The
80,872 games land just under the 100,000 threshold for `empirical_foundation_candidate`. Its
simulation budget: *"Use real data for priors and response-surface pilots. Keep simulation
targeted to counterfactual and adversarial gaps."*

### 3.1 The counterfactual trigger fired

From `runs/post_gap_fix_baseline/simulation/`:

```
decisions_evaluated       1882
out_of_support_decisions     6
requests                  dispatched: 2, duplicate_bucket: 4
dispatches_used           2 / 3
```

All six out-of-support decisions were `negotiation / seller / offer`. The ledger shows one
`counterfactual / ran` entry with 25 episodes, and one `counterfactual / skipped` from the
re-entrancy guard.

### 3.2 Negotiation diagnostic, now on 18,102 real role-rows

Three ranked causes:

1. `smoke_runs_show_under_aggressive_negotiation_outcomes` — 47 of 58 smoke rows (81%) flagged
   UNDER_AGGRESSIVE.
2. `floor_region_is_low_support_so_simulation_or_conservative_fallback_is_justified` — 53.7% of
   82 floor-support rows are low-support. Its proposed fix, *"Route this bucket through
   counterfactual simulation before changing the floor"*, is now actually possible.
3. `surplus_capture_floor_may_be_above_empirical_acceptance_region` — 14.95% of real accepted
   rows sit below our capture floor. Proposed A/B: floor scale 0.75.

Note this diagnostic *does* resolve `exact`-level buckets, because it builds configs from real
rows. That contrast is the subject of finding 4.3.

---

## 4. Findings

Three runs, all seed 42, so the 200 scenarios are **identical across runs** — which makes a
paired comparison available and far sharper than the unpaired per-family CIs the harness
reports. Paired differences in candidate payoff:

| Comparison | Family | Mean diff | 95% CI | t | W/L/T |
|---|---|---:|---|---:|---|
| jordan+RM vs jordan-noRM | bargaining | +0.0019 | ±0.0242 | +0.16 | 21/25/23 |
| | **negotiation** | **−0.0399** | **±0.0226** | **−3.47** | **10/23/23** |
| | persuasion | 0.0000 | — | — | 0/0/75 |
| jordan-noRM vs baseline | bargaining | +0.0027 | ±0.0206 | +0.25 | 26/15/28 |
| | **negotiation** | **+0.0542** | **±0.0165** | **+6.43** | **32/1/23** |
| | **persuasion** | **+0.0994** | **±0.0429** | **+4.54** | **36/21/18** |
| jordan+RM vs baseline | negotiation | +0.0143 | ±0.0247 | +1.14 | 21/17/18 |
| | persuasion | +0.0994 | ±0.0429 | +4.54 | 36/21/18 |

Shadow displayed ratings: jordan+RM **1418**, jordan-noRM **1460**, baseline **1459**.

### 4.1 The strategic machinery earns its keep; the trained response model destroys most of it

Jordan's rule-based policy beats the plain baseline decisively on negotiation (+0.054, t=+6.43,
32 wins to 1 loss) and persuasion (+0.099, t=+4.54). Bargaining is a wash in all three
comparisons.

Blending in the trained response model then *reverses* three quarters of the negotiation gain:
+0.054 over baseline becomes +0.014, and the direct paired comparison against rules-only is
−0.040 (t=−3.47, 10 wins to 23 losses). It has literally zero effect on persuasion — 0 wins,
0 losses, 75 ties, because the low-quality-EXPLOIT branch never fires — and none on bargaining.

The aggregate shadow ratings hide this completely: 1418 vs 1460 vs 1459 reads as "everything is
the same". The paired view is what makes it visible.

### 4.2 Why: the response model's price surface is confounded and slopes the wrong way

Acceptance probability from the trained model, at the pooled `price=` bucket level:

```
price 0.60-0.65   p=0.008   n=2509
price 0.70-0.75   p=0.017   n=2757
price 0.80-0.85   p=0.142   n=4066
price 0.95-1.00   p=0.190   n=4276
price 1.05-1.10   p=0.228   n=3066
price 1.20-1.25   p=0.165   n=8938
```

Acceptance is **increasing** in price across the whole working range. `robust_score =
payoff × probability − penalties` is then monotonically increasing in price, so the argmax
slams into the ceiling: with the model on, the seller asks for a median of **100% of the
available surplus** (mean 0.927) versus 0.950 / 0.866 on rules alone. `support_quality`
averages 0.842 on those offers, so the agent's own `< 0.08` guard never fires — the model is
confidently wrong.

The cause is confounding, not sparsity. Normalized price is measured in absolute value units,
so it correlates with `buyer_value`; high-`buyer_value` configs both permit higher prices and
have more room to accept. The table therefore estimates `P(accept | price observed)`, not
`P(accept | price we set)`. This is exactly the property the section-3 memo demands of Model C —
"a response surface, not a classifier — it must support counterfactual queries" — and the
current binned table does not have it for price.

### 4.3 The coverage signal is saturated, for a fixable reason

`bucket_level_counts` over the policy run: **0 at `exact`, 56 at `coarse`, 1,826 at
`family_role_round`**. Mean coverage score 0.993; 6 of 1,882 decisions out of support.

Every bargaining and negotiation lookup falls back to the config-agnostic level, because
`max_rounds` sits in both the exact and coarse bucket keys and the scenario sampler hard-codes
`max_rounds=6` while real GLEE uses 10, 12 and 30. Only persuasion ever reaches `coarse`, because
its coarse key bins `total_rounds=20`, which does match.

So Gap 2's coverage term is currently almost never binding, and the Gap 1 trigger is firing off
a nearly-saturated signal. The mechanism is correct and tested; the input is degraded. The
negotiation diagnostic reaching `exact` buckets from real configs confirms the index itself is
fine.

### 4.4 61% of real negotiation configs have no gains from trade; the sampler generates none

Over 96,214 real negotiation offer events:

| | share |
|---|---:|
| `buyer_value > seller_value` (gains from trade) | 38.8% |
| `buyer_value = seller_value` | 24.6% |
| `buyer_value < seller_value` (no trade zone) | 36.6% |

`sample_scenario` draws `buyer_value = uniform(seller_value, 1.25)`, so it produces a no-trade
zone essentially never. The agent's entire negotiation policy is built on
`surplus_room = max(0, buyer − seller)`, which collapses to 0 across the majority of the real
config space, and the synthetic tournament cannot surface that.

### 4.5 The agent cannot take the outside option, and the harness cannot score it

Real negotiation decisions: `RejectOffer` 66,536, `BuyFromJhon` 13,488, `AcceptOffer` 11,168,
`SellToJhon` 5,022. The outside option is **19.2%** of all decisions, and in no-trade-zone
configs it outnumbers `AcceptOffer` 16,003 to 2,117 — real players take the exit 7.6× more often
than they accept.

`_negotiation_decision` returns only `AcceptOffer` / `RejectOffer`, and `_run_negotiation` treats
any non-reject as a plain acceptance, so a fifth of the real action space is structurally
unreachable — concentrated in exactly the configs from 4.4.

Two supporting checks:

- The outside option is a **zero-surplus safe exit**, not a bonus. GLEE's
  `games/negotiation/negotiation.py` sets `deal_with_jhon_text` to
  `"Sell the product to Jhon for ${player_1.final_value}"` — it transacts at the player's own
  value. Our `terminal_negotiation` scoring it as 0.0 is therefore correct, which I checked
  before reporting it as a bug.
- But `terminal_negotiation` clamps with `max(0.0, ...)`, so a value-destroying acceptance in a
  no-trade zone scores **identically to correctly walking away**. Individual-rationality
  violations in negotiation are invisible in our data, and the incentive gradient is flat exactly
  where 4.4 says most of the real distribution lives. Whether the official metric clamps is
  unverified.

---

## 5. What to investigate next, cheapest test first

Ordered by information per unit of work. H1 and H2 are the same one-file change and should be
done together; both are prerequisites for trusting anything else.

**H1 — Sampling real config distributions unblocks the coverage signal.**
*Claim:* the saturation in 4.3 is entirely caused by `max_rounds=6`, and drawing configs from
the empirical distribution will make `exact`/`coarse` buckets resolve, the coverage term bind,
and the counterfactual trigger fire on real gaps instead of near-noise.
*Test:* ~10 lines in `sample_scenario` to draw negotiation and bargaining configs from the
observed discrete grid (`max_rounds ∈ {10, 12, 30}`, `seller_value`/`buyer_value ∈ {0.8, 1.0, 1.2, 1.5}`,
`product_price_order ∈ {1e4, 1e6}`), then re-run and read `bucket_level_counts`. Falsifiable in
one 200-game run; no new machinery. **Cheapest and highest leverage in this list.**

**H2 — The agent's negotiation policy degenerates in no-trade-zone configs.**
*Claim:* with `surplus_room = 0`, `required_margin = max(margin, 0)` collapses and the agent
accepts or offers near-arbitrarily in 61% of the real config space.
*Test:* same sampler change as H1, then a negotiation-only paired run split by trade zone.
Free once H1 is done. If confirmed, the fix is an explicit no-trade-zone arm — which requires H3.

**H3 — Adding the outside option is worth more than any parameter tuning.**
*Claim:* 19.2% of real decisions are an action we cannot take, concentrated where we are weakest.
*Test:* two steps, both small. First, pure real-data analysis (no simulation): compare realized
payoff of taking the exit versus accepting versus running out the clock, by trade zone — most of
this is already computed above. Then a harness change (add `SellToJhon`/`BuyFromJhon` to
`_run_negotiation` and the agent's decision set) A/B'd on the negotiation-only pipeline.
*Do the clamp fix first* — while `terminal_negotiation` clamps negatives to 0, the A/B cannot
distinguish "correctly exited" from "accepted a value-destroying deal", so it would measure
nothing. That clamp fix is a two-line change and should be treated as a prerequisite.

**H4 — The response model needs a conditioning set that blocks `buyer_value`.**
*Claim:* keying negotiation acceptance on *absolute* normalized price is what produces the
upward-sloping surface in 4.2; keying on price relative to the responder's own value
(`(price − seller_value)/surplus`, or `buyer_value − price`) removes the confound.
*Test:* change `negotiation_keys` in `runtime.py` to bin the relative quantity, retrain (51 s),
re-run the paired A/B. If the surface becomes downward-sloping and the paired negotiation
difference against rules-only turns non-negative, confirmed. One key change, one retrain, one
run. **Until this lands, `GLEE_RESPONSE_MODEL` should be off for negotiation** — we have direct
paired evidence it costs 0.040 payoff per game.

**H5 — Persuasion-as-buyer is the weakest family and it is a rule error, not a data gap.**
*Claim:* displayed rating 1122, mean percentile 0.391, worst episodes dominated by
persuasion-as-buyer including one IR violation at payoff −0.0445 — meaning
`break_even_quality + safety_margin` admitted a negative-EV purchase.
*Test:* pure real-data analysis. Compare real buyer accept rates conditioned on
`(p, v, c, recommendation)` against what the agent's break-even rule would do on the same
states. No simulation, no new machinery.

**H6 — Shadow percentiles are not comparable across families.**
*Claim:* negotiation shows the *best* percentile (0.779) and the *worst* payoff (0.129), and real
capture ranges from −11.4 to +12.4. The percentile denominator is likely distorted by
no-trade-zone games where nearly every payoff is clamped to 0, so ties dominate.
*Test:* recompute shadow percentiles stratified by trade zone over the artifacts already on
disk. No new runs at all.

### Recommended sequence

H1+H2 (one change, unblocks measurement) → clamp fix → H3 analysis → H4 retrain → H5, H6 in
parallel. The negotiation floor-scale A/B the diagnostic proposes should wait until after H1:
run today, it would tune a floor against a config distribution that does not exist in reality.

### Still open, deliberately not done

`rare_type_simulation` and `long_horizon_simulation` remain dead code (finding 1.1). The
`identity.composition` double-count (1.4) and the `"__global__"` guard (1.5) are unfixed. None of
the section-2 deferred items were started.
