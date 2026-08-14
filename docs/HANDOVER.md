# Handover

Written for someone picking this up cold, on a different machine, with no chat history.
State has been moving between sessions through docs in this directory, so this file is the
map. It points at detail rather than repeating it.

Current head at time of writing: `f40b630`. Test suite: **267 tests, all passing**
(7 skip without `glee-sdk` installed; 2 skip without the ingested dataset).

**Competition closes 29 August 2026.**

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

1. **Get an API key and play five real games.** Then read
   `reports/live/observations.jsonl` for non-`ok` statuses and `schema_violations` keys. Nothing
   else is worth more right now — every live claim is currently unvalidated, and rated volume
   takes calendar time we cannot recover.
2. **Persuasion is the weakest family and its policy is barely touched.** The two named leads
   are the deceptive-seller regression and the under-confident 0.5–0.8 calibration bins.
3. **Decide the H6 question** (§6.4): stratify the shadow percentile for a better skill
   measure, or leave it aligned with a presumed-pooling official formula.
4. **Commit `AGENT_CONTEXT.md` and the design memo** if you have them. Their absence from the
   repo is a real single point of failure.
