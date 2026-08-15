# Handover

Written for someone picking this up cold, on a different machine, with no chat history.
State has been moving between sessions through docs in this directory, so this file is the
map. It points at detail rather than repeating it.

Current head at time of writing: `94ec99b`. Test suite: **309 tests, all passing**
(7 skip without `glee-sdk` installed).

**Competition closes 29 August 2026.**

> **Read §0 first if you are resuming after 14 August 2026.** That session shipped three
> fixes, built four changes the gate rejected, and — most importantly — caught one of its own
> passing results as a false positive. The method matters more than the numbers.
>
> **Read §0.9 regardless of when you are resuming.** It is the standing protocol for how any
> future session — autonomous or not — is expected to work: parallel approach families, a
> real status vocabulary, durable state files, and one hard boundary around live play. It
> supersedes nothing in §1–§7; it wraps process discipline around them.

---

## 0. Session of 14 August 2026 — what changed, and the one thing to actually learn from it

This section is self-contained. If you read nothing else, read this.

The session had one job: fix, autonomously, the defects found after the first five real live
games. No live play was permitted and none was run. Every change went through the promotion
gate (§2.6) at full strength.

### 0.1 Shipped — on by default, in main

| # | Change | Commit | Why it needed no gate |
|---|---|---|---|
| 1a | Recover the live persuasion buyer's own purchase history from the running payoff totals | `da36cbb`, `0644232` | Adds information the buyer previously did not have at all. Nothing to A/B against. |
| 3a | `u` / `v` required in the live persuasion contract, judged on the shipped reader | `3931eaf` | Validation, not policy. |
| 3b | Roll the unbounded-game horizon instead of pinning it at a fixed 99 sentinel | `efc8087` | Corrects a number this repo invented, not a strategy choice. |
| — | Adapter's last-resort counteroffer fallback decays over rounds instead of repeating one price | `beff600` | A constant is strictly worse than a decaying one, and no agent flag gates it. |

**On 3b, because it answers a question the last session left open.** The adapter used a fixed
horizon of 99 to mean "no deadline". That is fine on round 1 and wrong by round 98: the round
counter climbs while the sentinel stays put, so the agent's endgame branch — accept almost
anything, or walk away — fired on an invented number. Live negotiation `9cf35978` ended exactly
that way, a mutual walk-away at round 99 for 0.0/0.0. A deadline-free game now gets
`round + 99`:

```
capped at 99   round 1 -> remaining 99 ... round 99 -> remaining   1  -> WalkAway
unbounded      round 1 -> remaining 100 ... round 99 -> remaining 100  -> RejectOffer
```

A real cap still bites. And the two cases are now behaviourally distinguishable, so the
round-99 walk-away can be **attributed** next time instead of guessed at — previously probes A
and B produced byte-identical state, which is why the log was mute.

### 0.2 Built, measured, and rejected by the gate — all off by default

Every one of these is complete, tested, and behind a flag. None is a stub. They are off because
the gate said no, and each carries the number that says why.

| Flag | Change | Effect | t | W/L/T | Failed on |
|---|---|---:|---:|---|---|
| `persuasion_explore` | Buy at negative EV to break the persuasion cold start | +0.0051 | +3.36 | — | `minimum_effect`, concentration |
| `use_time_concession` | Boulware time-dependent negotiation concession | +0.0003 | +2.11 | 6/76/1518 | `minimum_effect` |
| `guarantee_own_margin` | Clip negotiation offers on our own profitability, and price our own live counteroffers | +0.0076 | +9.46 | 117/0/1483 | `minimum_effect` |
| `debias_counterpart_value` | Correct the counterpart-value inference for the measured anchor gap | +0.0072 | +7.52 | 64/1/1535 | `minimum_effect`, concentration |
| all three negotiation flags together | The counteroffer path as one change | **+0.0109** | +10.07 | 136/42/1422 | **nothing — passed** |
| all three, confirmation run | Same candidate, independent sample | **+0.0094** | +12.49 | 233/94/2873 | `minimum_effect`, concentration |

`minimum_effect` (≥ 0.0100 paired mean) is explicitly **not waivable** by the defect carve-out,
which is why strong-looking changes with zero regressing subgroups still did not ship.

`guarantee_own_margin` also governs whether the agent attaches `counter_price` to a live
rejection. **The two cannot be separated**: with the margin guarantee off, the agent's own
counter price can land exactly on its reservation value, which is *worse* than the adapter's
`own_value * 0.85` fallback. Shipping the plumbing alone would have been a live regression
dressed as a fix. A test enforces the coupling.

### 0.3 The confirmation run — finished, acted on, not left pending

**Status: complete.** It ran to completion, it failed, the change was rejected, and the
rejection is recorded in `docs/PROMOTION_CRITERIA.md`. Nothing about it is outstanding, and
there is no half-finished experiment to resume.

The sequence matters more than the outcome:

1. Three changes each measured +0.0072 to +0.0076 and each failed `minimum_effect` alone.
2. That suggested the *grouping* was wrong. All three had been diagnosed together, as one chain
   producing one live symptom, **before any of them was measured** — so the whole counteroffer
   path is the honest unit of change.
3. Gated as one change, it returned **+0.0109, t=+10.07, and passed every single check.**
4. It was also the **fifth** gate run in this area, and it passed two checks by a hair:
   `minimum_effect` at 0.0109 against 0.0100, and `subgroup_concentration[config_regime]` at
   0.4985 against 0.5000. A skeptic would say the candidate was recombined until something
   passed. That criticism would have been fair.
5. So a confirmation run on an independent sample was **declared in advance** — different seed,
   twice the games, shipping conditional on it holding.
6. It did not hold: **+0.0094**, concentration back to 0.5539. Both marginal passes evaporated,
   which is what a marginal pass on a multiply-tested candidate is expected to do.

**Two things to carry forward.** Declaring the confirmation run *before* seeing its result is
the only reason this rejection happened — taking the 0.0109 would have made a sub-threshold
change a default and the gate decorative in exactly the way it was built to prevent. And a
higher `t` does not rescue a smaller effect: the confirmation run was *more* significant and
still failed, because `minimum_effect` asks whether an effect is worth the policy surface, not
whether it is real. Both runs agree the effect is real. Neither shows it is big enough.

### 0.4 Two claims I had to retract, and why that is the point

Neither of these was a statistics mistake. Both were confident conclusions that real data
contradicted, and finding them is worth more than any change that shipped.

**The "guaranteed-zero-payoff" persuasion bug was an overclaim.** I described the frozen
persuasion posterior as guaranteeing zero payoff. Measured across 13,506 real games: the frozen
version buys in 67.0% of rounds against the informed version's 60.6%, the two agree on 80.1% of
decisions, and the mean per-round EV forgone by being frozen is **+0.0286** — frozen is, on net,
slightly *better*. If the live game had `v ≈ 1.25` and `p = 0.5`, informed EV is −0.0001 and
declining all 20 rounds was approximately correct play. The bug was real; the severity was
invented.

**My first negotiation diagnosis was wrong about which defect mattered.** I attributed the
unchanging 6800.0 counteroffer to a static offer rule and wrote a concession curve for it. The
concession curve was **unreachable from live play**: the agent never attached a counter price at
all, so the adapter's own fallback of `own_value * 0.85` produced every live counteroffer —
and `8000 * 0.85 = 6800` exactly. A fix aimed at the wrong layer would have measured nothing
and been reported as done.

Also mid-change, in the same spirit: I tried shrinking the counterpart-value evidence bound
toward the prior on the argument that a bound may only tighten an estimate. It broke
`test_a_hidden_no_trade_zone_is_now_believable`, and **the test was right** — a lower bound can
never make us more pessimistic, so shrinking restores an optimistic floor that was deliberately
removed earlier and makes a no-trade zone unbelievable in the 61% of real configs that have
one. Reverted rather than argued with.

And the concession curve's own first gate run came back **−0.0054, t=−7.57**, driven by
`rounds=1|gains_from_trade` at −0.0447. That was a bug in my change, not in the hypothesis: the
factor returned `0.0` at horizon 1, reading "no rounds left" as "concede everything" when round
1 of a one-round game is all opening and no endgame.

### 0.5 One thing that is now measured rather than assumed

The counterpart-value inference read an opening offer as a valuation. Over **96,214 real
negotiation offers**, earliest offer per game per role:

| Role | Information | n | median | mean | p10 | p90 |
|---|---|---:|---:|---:|---:|---:|
| seller | incomplete | 16,542 | **1.500** | 2.604 | 1.250 | 2.000 |
| buyer | incomplete | 7,647 | **0.750** | 0.715 | 0.500 | 0.833 |
| seller | complete | 17,085 | 1.200 | 1.244 | 1.000 | 1.500 |
| buyer | complete | 8,714 | 0.800 | 0.796 | 0.667 | 0.900 |

So reading the price as the value overestimates a seller's cost by ~50% and underestimates a
buyer's value by ~25% — **both shrinking the believed trade zone**, which is how the agent talks
itself out of deals that exist. The constants live in `glee_eval/theory/benchmarks.py` as
`EMPIRICAL_SELLER_FIRST_ASK_MARKUP` and `EMPIRICAL_BUYER_FIRST_OFFER_SHADING`. Medians, not
means: the seller mean of 2.604 is dragged by a long right tail of opening anchors. The
measurement stands on its own and is reusable even though the change built on it was rejected.

Separately, and settled: **the live seller's recommendation is highly informative.** Over
88,910 real decisions, `P(high | rec=yes) = 0.7999` against `0.5434` unconditional, and
`P(high | rec=no) = 0.0125`.

### 0.6 Every new flag and its default

All in `JordanStrategicAgent.__init__`, each with the rejection numbers in a comment beside it.

| Flag | Default | Status |
|---|---|---|
| `use_theory_anchor` | `True` | **Passed the real gate** (+0.046, t=+6.60 vs fitted population) |
| `message_mode` | `"shadow"` | Gate structurally cannot test message text; records what it would send |
| `persuasion_explore` | `False` | Gate-rejected |
| `use_time_concession` | `False` | Gate-rejected |
| `guarantee_own_margin` | `False` | Gate-rejected; also gates the `counter_price` plumbing |
| `debias_counterpart_value` | `False` | Gate-rejected |
| `concession_convexity` | `2.5` | Tuning constant, inert while `use_time_concession` is off |
| `min_negotiation_margin` | `0.02` | Tuning constant, inert while `guarantee_own_margin` is off |

A test — `RejectedByTheGateTests.test_every_negotiation_flag_defaults_off` — asserts all three
rejected negotiation flags are off, so none can be flipped on later without deleting an
assertion that states why it is off.

### 0.7 What to do first next session

> **Run these in parallel, not in sequence — see §0.9.** The numbering below is priority order
> if you had to pick one, not a queue. With multiple approach families independently
> actionable right now (the `minimum_effect` decision, `guarantee_own_margin`, persuasion's two
> named leads, and H6), there is no reason to work them one at a time. §0.9 gives the rules for
> running them concurrently without them contaminating each other's evidence.

1. **Decide the `minimum_effect` question, before measuring anything else.** Four complete,
   tested changes are sitting off because they land at +0.007 to +0.010 while 1,422 of 1,600
   paired episodes are *ties* — the offline population barely exercises the code paths they
   fix. Either (a) the threshold is right and these genuinely are not worth the surface, or
   (b) `minimum_effect` needs a defined variant for defect fixes on rarely-exercised paths,
   e.g. conditioning on pairs that reach the branch. **(b) is defensible but must be written
   into `docs/PROMOTION_CRITERIA.md` first**, because choosing it after seeing these numbers is
   the exact failure the gate exists to prevent. This is a human decision, not an autonomous
   one. It does not block the other items below — they can proceed while this is pending, and
   simply cannot flip a default until it resolves.
2. **`guarantee_own_margin` is the strongest candidate and deserves the decision first.** It is
   provably defective by arithmetic rather than by A/B: the old clip collapses to a single point
   once the believed counterpart value crosses our own, so the only legal offer is *exactly our
   reservation value* — worth zero even when accepted. 117 wins, **0 losses**, 0.0000 subgroup
   breadth. It fails only on effect size.
3. **Then play live games.** Every live claim in this repo is still unvalidated by anyone but
   the user's five games. Read `reports/live/observations.jsonl` for non-`ok` statuses and
   `schema_violations` keys. Rated volume takes calendar time that cannot be recovered, and the
   deadline is 29 August 2026. **Live games are never scheduled or run autonomously — see
   §0.9 — this step always requires the user's explicit go-ahead**, independent of how the
   parallel work above is proceeding.
4. **Persuasion remains the weakest family** (§4.3). The two named leads are unchanged: the
   deceptive-seller regression and the under-confident 0.5–0.8 calibration bins. These are
   independent of the negotiation work above and can run as their own concurrent family.
5. **Decide the H6 percentile question** (§6.4). Reported, not corrected. Also independent and
   parallelizable; it touches scoring/reporting, not agent policy, so it cannot collide with
   the negotiation or persuasion work.

### 0.8 Still open or uncertain after this session

- **No real games were run or validated by me.** The `9cf35978` and `ea66da38` diagnoses come
  from the user's logs, not from my own play.
- **Live fixtures remain unverified against the real server.** Every live test asserts
  self-consistency with `glee_eval/live/fixtures.py`, which I wrote from documentation.
- **~18 games on the account predate this work** and may have been played by a different agent,
  so account-level ratings are not attributable to this code.
- **The round-99 walk-away is now explainable but not confirmed** — 3b makes the two cases
  distinguishable going forward; it does not retroactively prove which happened.
- Unchanged from before: whether the official metric clamps negative negotiation payoffs, and
  the H6 shadow-percentile distortion (§6.4).

### 0.9 Standing protocol for future sessions — parallel by default

This section governs how every future session works, autonomous or not, starting now and for
the remainder of the project. It does not replace the promotion gate in
`docs/PROMOTION_CRITERIA.md` — it wraps process discipline around it, because the gate tests
effect size and significance, not reasoning, and this project has already shipped one overclaim
(§0.4) that a numeric gate alone would not have caught.

**Work in parallel. Do not self-restrict to one approach family at a time.** There is
essentially always more than one independently actionable thread available — right now that's
the `minimum_effect` policy decision, `guarantee_own_margin`, the two named persuasion leads,
and H6 — and there is no reason implemented, tested, gated work on one family should wait on
another finishing. Run as many approach families concurrently as there is real, independent
work to do; a practical ceiling is about **6 concurrent threads**, mirroring the concurrency
limit most agent harnesses default to, but treat that as a starting point to raise, not a rule
to justify sitting idle below it. The only two constraints on parallelism are:

- **No two concurrent threads may ship a default-flipping change to the same code path without
  the coordination in "Shared surfaces" below.** §0.2 already shows why: three negotiation
  flags measured independently would each have stayed rejected forever, and the real result
  only appeared once they were understood as one path. Parallel work on a shared surface must
  stay *aware* of that surface, not necessarily merged into one thread.
- **Live/rated games are never a parallel thread.** They are the one activity in this project
  that consumes an irreplaceable, un-rerunnable resource (calendar time against the 29 August
  deadline) and cannot be run speculatively alongside other work — see the hard boundary below.

**Durable state — the memory of the project, not this doc and not any one session's context.**
Before starting new work, ensure these exist:

- `docs/REGISTRY.md` — one row per approach family (`theory_anchor`, `time_concession`,
  `guarantee_own_margin`, `debias_counterpart_value`, `persuasion_explore`, `message_mode`,
  `minimum_effect_policy`, `h6_percentile`, ...): exact change, exact remaining gap, last gate
  result with numbers, status (active / paused / blocked / shipped), which concurrent thread
  owns it, dependencies, evidence links. Seed it once from §0.2/§0.6, then keep it current
  instead of relying on this doc's prose tables, which will drift.
- `docs/FAILED.md` — append-only. Every gate-rejected or retracted change: what was tried, the
  exact numeric failure, and what would make a retry materially new. §0.2 and §0.4 are the seed
  content. Read the relevant entries here before starting *any* new approach family — state
  explicitly which entry is closest and why the new attempt differs, or write "no close prior
  entry."
- `docs/PROCESS_LESSONS.md` — transferable lessons only (e.g. "grouping honestly matters more
  than individual effect size," "declare confirmation runs before seeing results," "check
  round-1/horizon edge cases before trusting a curve," "don't let three related flags stay
  siloed"). Never mathematical or empirical *claims* about the game — those belong in
  REGISTRY.md and FAILED.md.

**Status vocabulary — every flag or change carries exactly one label, and a label never
outruns its weakest supporting run:**

- `candidate` — implemented, not yet gated.
- `gate-passed` — cleared `minimum_effect`, significance, downside, subgroup, and holdout on
  one sample. Counts the same as `candidate` for shipping purposes — see the next line. §0.3 is
  the proof of why: two checks passed by a hair (0.0109 vs 0.0100; 0.4985 vs 0.5000) and both
  evaporated on confirmation.
- `confirmed` — gate-passed **and** cleared an independent-sample confirmation run that was
  declared, in writing, before that run executed. Only `confirmed` changes may flip a default
  in `JordanStrategicAgent.__init__`.
- `shipped` — confirmed and merged with its default flipped.
- `retracted` — previously shipped or confirmed, later found defective by new evidence. Stays
  in FAILED.md, is never cited as working, and every downstream change that depended on it gets
  re-flagged in REGISTRY.md.

**Before any thread ships a change that flips a default:**
1. Check FAILED.md and state the closest prior entry and the material difference, or "no close
   prior entry."
2. Declare the confirmation-run sample size and seed *in REGISTRY.md, before running it.*
3. Run it. If it holds, promote to `shipped`, update REGISTRY.md, and note it in this doc's §0
   history for the next session. If not, log it to FAILED.md as `retracted` with the numbers,
   unchanged — do not resubmit the same candidate to a fresh gate run hoping for variance.

**Adversarial check before believing your own diagnosis.** Before writing a claim like "the bug
guarantees X" or "the root cause is Y" into REGISTRY.md, try to break it against real logged
data the same session — the way §0.4 did, but before shipping rather than after. A diagnosis
that hasn't been checked against `reports/live/observations.jsonl` or a gate run is a
hypothesis, not a finding, and should be labelled as such until checked.

**Kill-check before starting a new approach family.** One pass, cheap: does the smallest real
example in `observations.jsonl` already contradict the premise? Log the result in REGISTRY.md
even if inconclusive. This is what would have caught the concession-curve horizon-1 bug (§0.4)
before it consumed a full gate run.

**Shared surfaces.** If two concurrent threads touch the same function, flag, or scoring path,
they do not need to merge into one thread, but each must record the other in REGISTRY.md's
dependency field, and neither ships a default flip on that surface without checking the other's
latest REGISTRY.md status first. Diagnosing coupled defects together, even when investigated in
parallel, is what turned three individually-rejected negotiation flags into one gate-passing
change — don't let parallelism re-fragment something that's actually one mechanism.

**Reporting gate.** Only interrupt the user unsolicited for: a change reaching `shipped`, a
retraction of a previously shipped change, or a live game result outside expectations. Routine
gate rejections, in-progress parallel threads, and process notes go in the files, not as
interruptions — regardless of how many threads are running at once.

**Persistence, with one hard, non-negotiable boundary.** Do not stop working a
rejected-but-promising family (e.g. `guarantee_own_margin`) just because one gate run failed —
keep iterating per the cadence above, and keep other threads moving in parallel rather than
waiting on it. But **no session, autonomous or otherwise, may run or schedule a live/rated game
without the user's explicit authorization in that specific instance.** This is not a
conservatism default to be relaxed under deadline pressure — it is the opposite of every other
rule in this section. Everywhere else in this document, "don't restrict yourself, run more
threads, keep going" is the instruction. Live play is the one exception, because a live game
consumes real, un-rerunnable calendar time against the 29 August deadline and a bad one can move
a rating ~400 points early on (§2, live integration). Parallelize the offline work as
aggressively as there is real work to do; never parallelize into live play.

**Web policy.** Background research on negotiation, bargaining, or persuasion game theory,
standard mechanism design, or general ML/statistics literature is fine and encouraged where it
helps a thread. Do not search for the competition's other entrants, its leaderboard, or public
writeups of solutions to this specific competition.

**On stop or pause.** Reconcile every in-flight thread into REGISTRY.md/FAILED.md before
stopping. Any thread mid-confirmation-run that hasn't finished gets marked `candidate`, not a
stronger label, even if the gate run so far looks good. Append anything transferable to
PROCESS_LESSONS.md.

---

## 1. What this project is, and the standing priority

A local evaluation harness for building a competitor agent for the **GLEE benchmark** — three
families of economic games played in natural language (bargaining, negotiation, persuasion),
scored against a large population of historical LLM, human and bot opponents. The harness
exists so the agent can be developed offline: ingest and audit the real released dataset,
train an empirical response model, run synthetic tournaments, hunt failure cases, and produce
structured traces — before anything touches a rated game.

The agent is `my_agents/jordan_strategic.py`. No LLM calls anywhere in it; it reasons over
structured state plus a trained response model. It is named for Michael I. Jordan's work on
e-values and anytime-valid testing, and its four `StrategicMode` states (`SAFE`, `EXPLORE`,
`EXPLOIT`, `COMMIT`) are gated by quantities *named* to evoke e-values
(`E_concessionary`, `E_fairness`, `E_impatient`, `E_sample`, `E_commitment_sensitive`).
**Those are informal heuristic multipliers, not e-processes** — no martingale property, no
Type-I error control. That simplification is deliberate and documented; if anyone says "the
e-values", they mean the heuristics.

### The standing priority

**Reliability and correctness first. This is not a leaderboard rush.** Leaderboard placement
is a downstream consequence of getting the architecture right, not the thing driving
decisions. Where a fast change would move a metric and a slower one would make the system
more fundamentally reliable, take the slower one and say so rather than resolving it quietly
in favour of the score.

The working design principle is **"measurement lab before race car"**: a new component should
make an existing weakness *legible* (audit, diagnostic, ledger entry) before it is allowed to
*act* (simulate, change policy).

A session is not done because the bug it was pointed at is fixed. It is done when the root
cause is fixed rather than patched around, every known issue is either addressed or
explicitly deferred with a reason, problems have been hunted beyond the ones flagged, tests
exist for what changed, regressions were checked, and submitting would be defensible.

> **Gap in the repo:** the fuller version of this brief lived in a chat-supplied
> `AGENT_CONTEXT.md` that **is not in the repo**, and neither is the strategic design memo it
> refers to (the source of the Model A/B/C/D framing below). Sections 1 and 3 here are the
> most complete written record that survives. If you have the originals, committing them
> would remove a real single-point-of-failure.

### The design vision, in one paragraph

The memo argues against end-to-end behavioural cloning — historical players are often
suboptimal, so imitating them teaches suboptimality. Instead, learn the environment and
opponent population as four separable models: **A** opponent behaviour, **B** opponent latent
type, **C** outcome/response surface supporting *counterfactual* queries, **D** learning
dynamics. Simulation shrinks to five targeted roles. Game theory acts as a structural prior
(SPE for bargaining, Bayesian screening for negotiation, Bayesian persuasion for persuasion)
with empirical data explaining deviations from it — a "theory residual". Offline data is only
trustworthy near the empirical action support, and that support/coverage quantity is meant to
be a single shared currency every module reasons about. **Only C exists as a real model
today** (a binned empirical table). A, B and D do not.

---

## 2. What has actually been done

### Data foundation

Real GLEE cloned to `work/GLEE` and ingested: **80,872 games / 1,188,434 events**. Audit
verdict `empirical_pilot_dataset` with **zero blockers**. Support index: 20,614 buckets, of
which 13,528 (65.6%) are low-coverage.

Audit could not originally run on the full dataset at all — ~21 GB of Python objects. A
field projection that keeps only what the audit reads brought peak to 7.7 GB / 114 s with no
reported figure changed (`beb37d1`).

### Architecture as built

| Layer | Where | State |
|---|---|---|
| Ingest + audit + support index | `glee_eval/data/`, `glee_eval/audit/` | Working; `support_lookup` and `context_support_lookup` share one bucket ladder |
| Response model (memo's Model C) | `glee_eval/response_models/` | Binned empirical table, not a learned function. Keyed on the responder's own gain |
| Game-theoretic benchmarks | `glee_eval/theory/benchmarks.py` | Finite-horizon bargaining SPE by backward induction, verified against Rubinstein; negotiation max surplus; persuasion truthful-sender bound |
| Opponent population | `glee_eval/population/opponent_fit.py` | Fitted from 1.19M real events; archetypes are quantile bands of observed behaviour |
| Config catalogue | `glee_eval/population/config_catalogue.py` | Samples whole observed configurations, weighted by frequency |
| Coverage gate | `glee_eval/simulate/coverage_gate.py` | Shared "how much real data is here" currency; the only path from an out-of-support decision to simulation |
| Schema contracts | `glee_eval/contracts.py` | Validated at every boundary; judged on the *shipped reader* |
| Live adapter | `glee_eval/live/` | Never-raise wrapper around the SDK |
| Promotion gate | `glee_eval/experiments/promotion.py` | Pre-registered criteria + structural holdout |
| Agent | `my_agents/jordan_strategic.py` | Four modes, heuristic evidence gates |

All **five** simulation triggers are now reachable (`rare_type`, `counterfactual`,
`adversarial`, `long_horizon`, `policy_optimization`). Three of the five were dead code when
this work started.

### Gaps found and fixed, by pass

**Measurement integrity** — these gated everything else, because every prior measurement had
been taken against invented opponents playing invented configurations.

- `76e57ae` **Information leak.** `runner._state` handed every policy the whole config, so
  private values were visible regardless of `complete_information` (~49% of real bargaining
  and negotiation games). The agent *depended* on the leak via a `public_parameters` fallback.
  Correct filters already existed in `ingest.py` and simply weren't called.
- `83fea94` **Regret measured against a hard-coded 0.5.** Not an achievable payoff: in a
  no-trade-zone negotiation the ceiling is 0, so walking away correctly was charged 0.5 regret
  and then labelled UNDER_AGGRESSIVE. Also removed a `max(0.0, …)` clamp in
  `terminal_negotiation` that made value destruction score identically to walking away.
  Effect on 200 episodes: persuasion regret 0.080 → 0.368, bargaining 0.096 → 0.198,
  negotiation 0.326 → 0.090. **This inverted the family priority ranking.**
- `357b595` **Opponents were invented and archetypes were cosmetic.** Every parameter came
  from a hand-picked `rng.uniform`, and because they were always supplied, `policies.py`'s
  archetype defaults were dead code — archetype had *no* effect on negotiation or persuasion.
  Every hand-picked range was wrong about the real population (e.g. bargaining
  `accept_threshold` real 0.41–0.50 vs `U(0.30, 0.55)`; negotiators concede ~4× faster;
  senders far more honest).
- `f17f5af` **Configs were invented**, wrong in four ways: `max_rounds` 6 vs real 12/99 and
  10/30/1; `complete_information` always True vs ~49% False; `buyer_value` forced above
  `seller_value` so a no-trade zone never occurred vs 61% of real configs; continuous values
  against a discrete real grid. 10,823 real negotiation games are single-round ultimatums we
  never simulated.

**Agent correctness**

- `386d070` / `8ee828b` **Bargaining was blind to `delta_1`/`delta_2`** — hiding them changed
  payoff by exactly 0.0000, in a family where the equilibrium split is determined entirely by
  them and 75% of real games have asymmetric discounting. Offer share was also hard-clipped
  to `[0.50, 0.72]`, so the agent structurally could not concede below half.
- `718edd2` **Negotiation outside option** (`SellToJhon`/`BuyFromJhon`) added — 19.2% of real
  decisions. Also fixed a belief bug: the counterpart value was inferred as
  `max(prior, prices, own+0.12)`, using the prior as a *floor*, so a no-trade zone was
  literally unbelievable.
- `c390bd3` **Confounded price surface.** Absolute price correlates with `buyer_value`, so the
  table estimated `P(accept | price observed)` not `P(accept | price we set)` and acceptance
  *rose* with price. Re-keyed on the responder's own gain.
- `a5c2eaf` **Three crashes and a logic bug** reachable only from malformed state, plus the
  persuasion buyer reading the recommendation as `visible_transcript[-1]`.
- `4676611` **`is_myopic` never modelled** (49.4% of real persuasion games wipe the buyer's
  memory every round), and **the buy rule declined every real purchase** — 0 of 66,480 — because
  it read quality from a key only synthetic transcripts set.

**Systemic fix** — `2b91e01`, `af12d6d`. The same shape-mismatch failure mode had produced
confidently-wrong behaviour twice with nothing raising. `glee_eval/contracts.py` now validates
every boundary, and crucially judges **the reader production code actually uses**, not the
layout: a first version compared layouts and reported 852,700 violations on real data, because
real rows legitimately carry facts under `raw.*`. The violation that matters is *the fact is
present and the shipped reader returns None*. Modes differ by boundary — STRICT offline where
raising is free, OBSERVE live where an exception would be swallowed by the SDK and cost the
game. Runs automatically in the suite and as a named CI step.

### The promotion / evidence gate

Full detail and reasoning: **`docs/PROMOTION_CRITERIA.md`**. Implemented in
`glee_eval/experiments/promotion.py`, run via `python -m glee_eval promotion-check`.

Every check must pass:

| Check | Threshold |
|---|---|
| `sample_size` | ≥ 200 paired episodes |
| `minimum_effect` | ≥ 0.01 paired mean payoff |
| `significance` | paired t ≥ 1.96 |
| `downside_p5` | candidate's 5th-pct **outcome** ≥ baseline's − 0.02 |
| `subgroup_concentration` | ≤ 0.50 of the gain from one subgroup |
| `subgroup_breadth` | ≤ 0.40 of subgroups regressing |
| `structural_holdout` | required |

Subgroups are checked on opponent archetype and config regime. **"Significance" is the
ordinary paired t and nothing stronger** — fixed-sample, not anytime-valid, not an e-process.

**Structural holdout** (`glee_eval/population/splits.py`): deterministic SHA1-bucket
partitions. The `model` axis withholds five entire LLM families the fit slice never sees
(`gpt-4o-mini`, `otree`, `otree_LLM`, `llama-3.3-70b`, `mistral-large`), 43.1% of games. The
`config` axis withholds configuration regimes.

Three verdicts recorded so far, in `reports/promotion/`:

| Change | Verdict | Numbers |
|---|---|---|
| Bargaining theory anchor | **PROMOTE**, all checks pass | +0.0737, t=+12.43, n=800; 389W/91L; larger on holdout than the +0.046 that shipped it |
| Persuasion accessor fix | **FAIL** `subgroup_breadth` (0.4375 vs 0.40) — shipped under the documented defect carve-out | +0.0160, t=+7.25, n=1600 |
| Negotiation remaining-rounds | **FAIL** — **not shipped** | +0.0002, t=+0.81, n=1600 |

The carve-out permits shipping despite a failing gate only when the prior behaviour is
provably defective *against real data*, only for breadth/coverage failures, and only with the
regression mechanism filed. It explicitly may not waive effect, significance, downside,
sample size or holdout.

### Live GLEE API integration

Full runbook: **`docs/LIVE_INTEGRATION.md`**. Code in `glee_eval/live/`.
`eb40c4c`, plus packaging fix `f40b630`.

The design is driven by one fact: `GleeClient._handle_game` **catches strategy exceptions and
returns without submitting a move**. From the server's side that is a turn timeout, scored at
the **5th percentile** — and with the `g/(g+30)` discount, one incident can move a family
rating ~400 points early on. So a crash is not a loud failure but a silent, expensive one.
`LiveStrategy` therefore catches `BaseException`, wraps the fallback so even *it* cannot
raise, caps messages at the SDK's 2000, derives bargaining's second gain by subtraction so the
exact-sum rule can't be broken by floating point, and always attaches a counteroffer to a
`RejectOffer` except on a capped final round.

Eleven schema differences from our offline format are written out in the runbook. The ones
most likely to bite: `alice_gain`/`bob_gain` not `self_gain`/`other_gain`; persuasion low
value is **`u`** not `c`; quality is **`"high"`** not `"high-quality"`; the outside option is a
single `WalkAway`; prices are **absolute** (normalised by our own valuation in, multiplied back
out); an absent `max_rounds` means unbounded and maps to horizon 99, not 0.

### Shadow-mode persuasion language change

Code `my_agents/message_composer.py`, commit `2e89062`. Adds confidence and social proof,
avoids hedging, stays short — built only on features whose sign held on **both** high- and
low-quality rounds. Deliberately excludes `gain_frame`, `discloses_value` and `asks_question`,
which flip sign and therefore proxy the seller's private intent rather than moving the buyer.

**It runs in shadow and is explicitly not gate-passed.** Nothing in the simulator reads
message text — replacing every template with `"."` moves persuasion payoff by **0.000000** — so
an in-simulator A/B measures nothing, and calibrating a message-reading opponent on the same
effects being tested would be circular. Shadow mode records what it *would* send alongside
what was sent, both with feature vectors. Every record carries
`gate_status: "not_gate_passed_pending_real_data"` so it cannot be confused with the
bargaining anchor, which passed the real gate. Real logged games are the only non-circular
evidence available.

### H1–H6 resolutions

Originally proposed in `docs/POST_GAP_FIX_REPORT.md`; re-verified in `00b64c1`.

| | Verdict |
|---|---|
| H1 coverage saturation | **Resolved.** `exact` buckets 0 → 160, `coarse` 56 → 352; mean coverage 0.993 → 0.885 |
| H2 no-trade degeneration | **Resolved.** No-trade games end at exactly 0.0000, zero negative payoffs |
| H3 outside option | **Shipped, premise wrong.** Worth exactly 0 upstream — a fidelity fix, not the payoff win predicted |
| H4 confounded surface | **Shipped, claim invalidated.** The −0.040/game was an artifact of invented opponents; against fitted ones the model *helps* (+0.0066) |
| H5 persuasion buyer | **Resolved, diagnosis backwards.** Not irrational purchases but *zero* purchases, from a shape bug |
| H6 percentile comparability | **Confirmed.** 93.9% of real no-trade payoffs are exactly 0 vs 34.9% in gains configs; pooling understates no-trade standing (0.385 vs 0.508 stratified) and overstates the rest (0.769 vs 0.599). **Reported, not corrected** — see §6 |

---

## 3. Not done, and why it was deferred rather than forgotten

Each of these was on an explicit out-of-scope list, and each needs a deliberate design pass
first rather than being bolted on.

| Deferred | Why |
|---|---|
| **LLM observer/writer components** beyond fixed templates | Would make every result unattributable to a specific mechanism; also the simulator cannot A/B message text at all |
| **Formal anytime-valid e-process / test-martingale framework** | The agent is named for it but must not be assumed to implement it. Building fake rigor is worse than none; the promotion gate is deliberately labelled fixed-sample |
| **Online / live weight updates during a run** | No way to validate; would make every game's behaviour depend on unreproducible state |
| **Neural foundation model or contextual-bandit policy portfolio** | Nothing yet justifies the complexity; the binned table is not even fully exploited |
| **Causal machinery beyond the theory residual** — propensity models, doubly-robust estimators, causal forests | The step-3 language findings are explicitly *stratified associations, not causal effects*, and the modules say so |
| **Exact replica of the official leaderboard scoring** | The formula is private. `glee_eval/scoring/shadow.py` is a proxy, and this is why H6 is reported rather than corrected |
| **Models A, B and D** | Only C exists. Archetypes are stipulated quantile bands, not fitted latent types |
| `rare_type` / `long_horizon` **richer wiring** | Both are now called, but `long_horizon` will normally record a skip because real games already reach 198 turns. Correctly inert rather than dead |
| **`policy_optimization` as true OPE** | Still runs local synthetic episodes rather than rollouts against the learned response surface. Known, lower-priority debt |
| **`identity.composition` double-count → fixed**; **`"__global__"` guard → fixed** | Both closed in `6612d45`, listed here only because earlier reports call them open |

---

## 4. Per-family status, with the numbers

All from `runs/step5_final` (200 games, real configs, calibrated opponents) unless stated.
Overall shadow rating **1401.9**; agreement/sale rate **0.79**; probes **1000/1000** legal and
parseable, format-failure rate 0.0.

**Live confirmation, 15 August 2026.** An authorized terminal-capture run produced 31 complete
game records (15 direct terminal move results plus 16 GET backfills; 100% terminal payoff
coverage). The comparable normalized means were bargaining **0.383075** (n=11, −0.101925 vs
offline), negotiation **0.116996** (n=10, +0.024296), and persuasion **0.235000** (n=10,
−0.164300). These small live cells reflect live matchmaking rather than the fitted-population
sampling target, so the differences are measurements, not causal policy regressions. The
account counter advanced by 30 rated games while capture recorded 31 terminal games. Ending
ratings were bargaining 1063.52, negotiation 1028.02, and persuasion 1072.86.

**Strict rated-volume run, 15 August 2026.** The repaired wrapper completed exactly 75/75
unique games, balanced 25 per family, with 36 direct terminal results and 39 GET backfills,
zero capture errors, zero fallbacks, and a clean schema. Means were bargaining **0.441103**
(−0.043897 vs offline), negotiation **0.072562** (−0.020138), and persuasion **0.382000**
(−0.017300). Ending ratings were 1115.66, 1022.51, and 1108.86 respectively. The earlier
large bargaining/persuasion shortfalls did not replicate at volume; both offline targets remain
inside normal-approximation live intervals. Do not promote a policy change from the original
31-game discrepancy.

**Second strict rated-volume run, 15 August 2026.** A separately authorized batch again
completed exactly 75/75 games, 25 per family, with 35 direct terminal results and 40 GET
backfills. All 860 callbacks were `ok`; there were zero capture errors, fallbacks, or schema
violations, and the launch manifest again records `GLEE_SUPPORT_INDEX` as not configured.
Means were bargaining **0.384421** (−0.100579 vs offline), negotiation **0.071503**
(−0.021197), and persuasion **0.525600** (+0.126300). Ending account ratings were 1138.91,
1003.47, and 1156.72 respectively. Bargaining player-1/player-2 means were .382355/.386329,
and persuasion seller/buyer means were .567857/.471818, so the earlier large role splits did
not replicate. The bargaining and negotiation offline targets remain inside descriptive
normal-approximation intervals; these matchmaker samples are not causal policy comparisons.

**Live text-persuasion diagnosis and rejected candidate, 15 August 2026.** Across the complete
confirmation and strict-volume logs, every one of 180 text-mode buyer turns defaulted to no.
The server supplied 101 unequivocally positive and 79 negative messages, but unlike the
simulator it supplied no hidden structured stance beside the text. A conservative default-off
parser passed the frozen 420-turn replay with zero polarity errors and zero binary changes.
Its prospectively declared structural-holdout payoff gate measured **+0.1390**, t=13.04,
n=1600, but failed config-regime concentration at **0.5437 > 0.50**. It remains a candidate;
the default is off and no post-fix live batch is authorized for it. See REGISTRY/FAILED for the
exact gate and no-retry constraint.

**Live negotiation attribution audit, 15 August 2026.** Across 60 authoritative complete
games, 37 identifiable gains-from-trade cells averaged .127264, two known no-trade/equality
cells averaged .031414, and 21 zero-payoff incomplete-information cells have hidden counterpart
values, so their true zone cannot be recovered. The live no-trade explicit-outside rate has a
sharp sample bound of 0%--84.62%; treating every hidden cell as no-trade gives 11/23=47.83%,
but that is a sensitivity assumption, not an estimate comparable with offline 86%/real 88%.
The offline zero-responder-gain boundary reproduces at .3298; live remains 0/4, underpowered,
with 210/446 response gains hidden. Own-margin harm was absent in 37 openings and 38 agreements,
and counterpart de-biasing was truth-checkable only twice. One materially new mechanism was
proved: in hidden-horizon game `f29a…`, the adapter replaced the seller's 16950 opening with a
worse static 17250 counter for 49 turns, ending at zero. A prospectively declared, isolated
live-contract fallback candidate nevertheless measured only **+0.000307**, t=1.964, 4W/0L/
1596T at n=1600 and failed minimum effect plus config concentration (.5980). It remains off;
none of the older negotiation flags was revived.

### Bargaining — strongest

- Tournament payoff **+0.4850**, 95% CI [+0.4794, +0.4906], n=69, median +0.5000
- Shadow percentile **0.6043**, rating **1540.3**, all 71 scored games resolving at `exact`
  bucket level
- Time preference is modelled and **gate-passed**: +0.0737 (t=+12.43) on holdout, 389W/91L,
  no p5 downside, max subgroup gain share 0.16 by archetype
- Corrected-benchmark regret against SPE was 0.198 at the point of measurement — i.e. below
  equilibrium, so headroom remains

### Negotiation — mid, and correctly cautious

- Tournament payoff **+0.0927**, CI [+0.0576, +0.1278], n=56, **median +0.0000**
- The zero median is *correct*, not a failure: 61% of real configs have no gains from trade,
  where 0 is the ceiling. Split out: no-trade games mean +0.0000 with **zero** negative
  payoffs; gains-from-trade games mean **+0.1883**
- 86% of no-trade games end on the outside option, against a real-population rate of 88%
- Shadow percentile 0.5735, rating 1383.9, 58 games at `exact` level — but see H6/§6, this
  percentile is known to be distorted
- Response model helps modestly (+0.0066, t=+3.00) against fitted opponents. It is consulted
  in only **160 of 600** episodes, because the agent exits no-trade configs before pricing
- Remaining-rounds conditioning was **rejected** by the gate and is not shipped
- As of 14 August 2026, **four further negotiation changes are built and rejected** — see §0.2.
  Three of them address one real chain of defects that cost a live game 99 rounds and 0.0/0.0,
  and the combined change passed the gate on one sample and failed on an independent
  confirmation run. Read §0.3 before touching this family; the flags are deliberately off, and
  §0.7 item 1 is the decision that unblocks them
- The live counteroffer path itself **is** fixed regardless of those flags: the adapter's
  last-resort fallback now decays over rounds instead of resending one price forever, and an
  unbounded game no longer presents as a game about to end (§0.1)

### Persuasion — weakest, and the active frontier

- Tournament payoff **+0.3993**, CI [+0.2983, +0.5003], n=75 — highest raw payoff of the three,
  but the **lowest shadow percentile at 0.4611** and lowest rating **1281.4**
- Its scored games resolve at `coarse` (30) and `family_role` (47), never `exact` — the only
  family that never reaches the most specific bucket
- Buyer arm, on 66,480 real decisions: purchase rate **0.4994** vs real buyers' **0.5211**,
  surplus per purchase **+1.1747** vs **+1.0158**, high-quality hit rate **0.8709** vs
  **0.8734**, ECE **0.0826**. So it buys slightly less often than real buyers and earns more
  per purchase
- Before the fix it bought **0 of 66,480**. Paired on 800 holdout scenarios the fix moved
  regret 0.4493 → 0.4100 (t=−9.18) and payoff +0.5400 → +0.5590 (t=+6.50)
- Language signal is real: on 138,009 real text-mode decisions, controlling for realized
  quality, message stance and seller model — `hedged` **−0.1131** (z=−35.9), `social_proof`
  **+0.0639** (z=+21.5), `confident` **+0.0276** (z=+10.1). The composer that exploits this is
  in **shadow only**
- Known open: residual under-confidence in the 0.5–0.8 calibration bins, and the
  deceptive-seller regression (7 of 16 archetypes regress, concentrated at the dishonest end)

---

## 5. Live integration status

**The adapter is built, tested, and installable. Zero real games have been played.**

What has been verified:

- `python -m glee_eval live --dry-run` exercises one payload per documented phase of every
  family. Latest run: 7/7 `ok`, **0 fallbacks**, `schema.clean: true`, slowest turn 0.0001 s
  against a 120 s server budget
- `reports/live/dry_run_observations.jsonl` currently holds **21 rows across 3 dry runs** (the
  log appends; `dry_run.json` is overwritten). All 21 are `ok`; **0** rows have a
  `schema_violations` key
- Our strategy driven through the SDK's real `_handle_game` with a stubbed transport, asserting
  both halves: a bare raising strategy submits **nothing**, ours always submits
- `pip install -e '.[live]'` and a non-editable wheel install both verified in a **fresh clone
  and fresh venv**, with a negative control confirming the pre-fix commit fails there

### What a clean dry run does *not* prove

This is the most important caveat in this document. **The dry run feeds the adapter my own
fixtures**, written from the glee-sdk 0.0.5 README — not captured from a real game. So
`schema.clean: true` means "my fixtures match my contracts", which is close to a tautology. A
field the live server names differently from the docs would pass all 267 tests and still be
wrong.

`reports/live/observations.jsonl` exists precisely for this. **Check it after the first five
real games, not the first hundred.** Two things to look at per row:

- `status` — anything other than `ok` is a fallback, meaning our code could not handle a real
  payload
- a `schema_violations` key — that is the contract layer firing against a *real* payload, and
  is the single most valuable signal the first games can give

Suggested first run, small and inspectable:

```bash
export GLEE_API_KEY=glee_...            # you must create the agent + key yourself
python3 -m venv .venv && .venv/bin/python -m pip install -e '.[live]'
.venv/bin/python -m glee_eval live --max-games 5 --concurrency 2
```

### Volume, once it works

Rating is discounted by `g/(g+30)`, so early games count for little and volume matters. **All
three families must be played** — an unplayed family sits at the 1,000 starting rating and
drags the average down, which is why persuasion has to actually ship, not just be diagnosed.
Holding a top-100 place needs ~10 games/day in that family. Rate limit 60 req/min per agent,
5 agents per account, `concurrency` 4–10. Placement is **self-gain only** — efficiency and
fairness are recorded but do not affect rank.

---

## 6. Still unverified or uncertain — specifics, not reassurance

1. **No real game has ever been played.** Everything about live behaviour is inference from
   documentation and fixtures. This is the largest open risk.
2. **The live fixtures are unvalidated against the server.** Eleven schema differences were
   transcribed by hand from a README. Any one being wrong is silent.
3. **Whether the official metric clamps negative negotiation payoffs.** Our clamp was removed
   on internal-consistency grounds (bargaining cannot go negative; persuasion never clamped),
   but the private formula is unknown.
4. **The H6 percentile distortion is reported, not fixed.** Stratifying would make the shadow
   score a better measure of *skill* but possibly a worse predictor of *placement*, since the
   official formula is private. `shadow.py` emits a
   `percentile_stratification_warning` on the negotiation family. **This is an open decision,
   deliberately left to a human.**
5. **`reference_payoff = max(candidate, opponent, theory)`** includes the opponent's payoff, so
   regret is partly relative rather than purely distance-from-achievable. Defensible, but it is
   why a change can raise payoff and regret together.
6. **`p ≈ 0.34` acceptance at zero responder gain** remains the most load-bearing unverified
   number in the negotiation policy. The remaining-rounds hypothesis about it was right about
   the *statistic* (0.240 early vs 0.468 final) and wrong about the *model*, and was rejected.
   Something else may still be wrong there.
7. **Archetype bands are a stipulation, not a fitting.** Mapping `aggressive_extractor` to the
   0.80–0.98 quantile window is asserted. Which real players actually cluster together is
   unmeasured, because Model B is deferred.
8. **`EMPIRICAL_DELTA_MEAN = 0.9133`** was computed on the full dataset including the holdout.
   Immaterial here (fit slice 0.9125, holdout 0.9142) but it is a genuine leak, and any future
   constant derived from full-data statistics has the same problem.
9. **The persuasion buyer ceiling** uses `p·(v−1)`, the truthful-sender benchmark, deliberately
   rejecting a perfect-foresight bound. Whether that is right against a *strategic* sender is
   unresolved.
10. **Two prior reports contain conclusions now known to be wrong.** They are kept for the
    record but must not be read as current — see the note at the top of §7.

---

## 7. Where the detail lives

| Document | What it is |
|---|---|
| **`docs/PROMOTION_CRITERIA.md`** | The evidence gate: every threshold with its reasoning, the structural holdout, the defect-fix carve-out, shadow mode, and every verdict including the rejection. **Read this before shipping any policy change.** |
| **`docs/LIVE_INTEGRATION.md`** | Live runbook: setup, the never-raise design and why, all eleven schema differences, volume requirements, and what the dry run does not prove |
| **`docs/DEBUG_PASS_REPORT.md`** | The second debugging pass. Found the information leak, delta blindness, cosmetic archetypes, and the persuasion mechanics bugs |
| **`docs/POST_GAP_FIX_REPORT.md`** | The first pass. Wired the counterfactual trigger and the coverage gate |
| **`docs/USAGE.md`** | How to run the harness day to day |
| **`docs/GLEE_AUDIT.md`** | Audit of the upstream GLEE repository itself |
| **`docs/REGISTRY.md`** | *(New, §0.9.)* Live status of every approach family, across however many parallel threads are running |
| **`docs/FAILED.md`** | *(New, §0.9.)* Append-only record of every rejected or retracted change and what would make a retry materially new |
| **`docs/PROCESS_LESSONS.md`** | *(New, §0.9.)* Transferable process lessons only, never mathematical/empirical claims |

> **Read the two pass reports with care.** Each was superseded in part by the next.
> `POST_GAP_FIX_REPORT.md` calls a negotiation finding "a confirmed, live bug… not a testbed
> artifact" — it *was* a testbed artifact. `DEBUG_PASS_REPORT.md` predicts the outside option
> would be a payoff win — it is worth exactly zero. Both errors came from measuring against
> invented opponents. **§2 and §4 of this file are the current state; those reports are
> history.**

### Commands

```bash
python3 -m glee_eval schema-check                 # contract validation, exits non-zero on violation
python3 -m glee_eval experiment --agent my_agents.jordan_strategic:MyAgent --name run1 --games 200
python3 -m glee_eval persuasion-calibration       # buy-rule calibration vs real buyers
python3 -m glee_eval language-analysis            # message-feature effects on real purchases
python3 -m glee_eval promotion-check --observations <path> --change "..." --holdout
python3 -m glee_eval live --dry-run
python3 -m unittest discover -s tests             # 267 tests
```

Full command list: `audit`, `calibrate-population`, `config-catalogue`, `dataset-audit`,
`experiment`, `fit-opponents`, `ingest`, `language-analysis`, `live`,
`negotiation-diagnostic`, `persuasion-calibration`, `probes`, `promotion-check`,
`schema-check`, `search-failures`, `shadow-score`, `stats`, `train-response-models`,
`validate`.

### Rebuilding artifacts from scratch

`data/`, `models/`, `reports/`, `runs/` and `work/` are gitignored, so a fresh clone has none
of them. To rebuild (~15 minutes, mostly the ingest):

```bash
git clone https://github.com/eilamshapira/GLEE.git work/GLEE
python3 -m glee_eval ingest --glee-root work/GLEE --output-dir data
python3 -m glee_eval dataset-audit --data-dir data --output-dir reports/dataset_audit
python3 -m glee_eval train-response-models --data-dir data --output-dir models/response_v1
python3 -m glee_eval fit-opponents --data-dir data --output-dir models/opponent_population
python3 -m glee_eval config-catalogue --data-dir data --output-dir models/config_catalogue
# holdout variants, needed for the promotion gate:
python3 -m glee_eval fit-opponents  --output-dir models/opponent_population_holdout --split-mode model  --split holdout
python3 -m glee_eval config-catalogue --output-dir models/config_catalogue_holdout  --split-mode config --split holdout
```

The agent reads `GLEE_RESPONSE_MODEL`, `GLEE_OPPONENT_POPULATION`, `GLEE_CONFIG_CATALOGUE`,
`GLEE_SUPPORT_INDEX` and `GLEE_API_KEY` from the environment. **`models/response_v1` is the
production response model** — `v0` is the confounded original and `v2` is the rejected
remaining-rounds variant.

---

## Immediate next steps, in order

> **Superseded by §0.7 and §0.9 for anyone resuming after 14 August 2026.** The list below is
> the pre-session ordering and is kept for continuity. The one change: an API key now exists and
> five real games have been played, so item 1 is partly done — but no games have been played or
> validated by the agent author, and none were run in the 14 August session by instruction.

1. **Get an API key and play five real games.** Then read
   `reports/live/observations.jsonl` for non-`ok` statuses and `schema_violations` keys. Nothing
   else is worth more right now — every live claim is currently unvalidated, and rated volume
   takes calendar time we cannot recover. **Still always requires explicit user authorization
   per §0.9 — never run autonomously regardless of what else is in progress.**
2. **Persuasion is the weakest family and its policy is barely touched.** The two named leads
   are the deceptive-seller regression and the under-confident 0.5–0.8 calibration bins.
3. **Decide the H6 question** (§6.4): stratify the shadow percentile for a better skill
   measure, or leave it aligned with a presumed-pooling official formula.
4. **Commit `AGENT_CONTEXT.md` and the design memo** if you have them. Their absence from the
   repo is a real single point of failure.

Items 2–4 above, and the items in §0.7, are independently actionable and should run as
concurrent threads per §0.9 rather than in this numbered order — the numbering here is
priority, not a queue.
