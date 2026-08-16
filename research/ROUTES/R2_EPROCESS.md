# R2 — bounded e-process kill-check

Status: **valid mathematical construction under explicit conditions; historical `E_*`
scores invalidated; implementation not yet authorized by this certificate alone.**

## Frozen claim and scope

This route asks only whether the smallest plausible anytime-evidence construction is
mathematically valid under a declared filtration and composite null. It does not claim a
payoff improvement. The construction uses only economic state and completed economic-history
events. No live run, fitting, simulation, or treatment evaluation was performed.

Base commit: `bce578597dbfacf2ebca38399edb41a5dde2f936`.

Input SHA-256 hashes:

- `research/RESEARCH_QUESTION.md`:
  `cbe48c76aaec6e00c05d0a80fe3f6d3193aeffbd2ac7c9f24f3fe3de41293ff2`
- `research/AUDIT_CHECKLIST.md`:
  `f8b03c63546d4ca863b3c8a2ec6d297c416e7b6b594e4b4c15acb08afadea5f9`
- `research/ROUTES/WAVE_1.md`:
  `cc2d96ea000c902b22c4d847ae27e9495c3a7dc3503b8825457a5649e801922d`
- `glee_eval/data/schemas.py`:
  `1868a0535529666880717459b6f9201a1c64e0e86f185593be30fa43cd481577`
- `glee_eval/tournament/runner.py`:
  `0142f3354759bad9038c1e93b331ccca762cf8ee4b09653f0b4a0903b380566b`
- `my_agents/jordan_strategic.py`:
  `27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82`

## One bounded kill-check

### Filtration and observation

Index completed binary economic opportunities by `t`, not raw transcript rows. Immediately
before outcome `X_t` is revealed, let `F_{t-1}` contain:

1. the fixed input manifest and all state fields legally visible to the agent;
2. all completed, legally visible economic events from earlier opportunities;
3. the current opportunity definition, the agent's already-selected action, and any random
   coin used to select that action; and
4. the predictable values `p0_t` and `q_t`.

Then `X_t in {0,1}` is revealed and adjoined to obtain `F_t`. An opportunity that does not
exist is not indexed. A missing observation may be skipped only when its observability was
known at `F_{t-1}`; outcome-dependent deletion is not allowed.

A concrete economic event compatible with the current prefix history is an opponent
concession. The first opponent offer fixes an anchor. At each later opponent offer,
`X_t = 1` exactly when the offer moves toward the candidate: the opponent's own share falls
in bargaining; a seller's ask falls or a buyer's bid rises in negotiation. Ties give `X_t=0`.
The same kernel can be applied to another preregistered binary economic event, but its event
definition and null bound must not be selected after seeing `X_t`.

### Composite null, alternative, and likelihood ratio

The smallest fixed candidate uses no estimated nuisance parameter:

`p0_t = 1/2` and `q_t = 3/4` for every indexed opportunity.

The composite null is the set of all laws `P`—including dependent opponents and adaptively
chosen candidate actions—such that, almost surely, for every indexed opportunity,

`P(X_t = 1 | F_{t-1}) <= 1/2`.

The working alternative has conditional success probability `3/4`. Its one-step likelihood
ratio against the boundary of the null and its cumulative product are

`L_t = (3/2)^X_t (1/2)^(1-X_t)`,

`M_0 = 1`, and `M_t = product_{s=1}^t L_s`.

Equivalently, a general predictable choice with `0 < p0_t <= q_t < 1` uses

`L_t = (q_t/p0_t)^X_t ((1-q_t)/(1-p0_t))^(1-X_t)`.

The fixed `1/2, 3/4` version is the kill-check candidate because it has no zero or near-zero
likelihoods, no plug-in estimate, and exact rational arithmetic.

### Proof under the composite null

Write `p_t = P(X_t=1 | F_{t-1})`. For the fixed candidate,

`E_P[L_t | F_{t-1}] = p_t(3/2) + (1-p_t)(1/2) = 1/2 + p_t <= 1`.

Therefore

`E_P[M_t | F_{t-1}] = M_{t-1} E_P[L_t | F_{t-1}] <= M_{t-1}`.

Thus `(M_t)` is a nonnegative supermartingale with `M_0=1` under every law in the
composite null: it is an e-process. For the general predictable kernel,

`E_P[L_t | F_{t-1}]`

`= 1 + (p_t-p0_t)(q_t-p0_t)/(p0_t(1-p0_t)) <= 1`.

The proof does not require independence. It permits the candidate action, the opponent law,
and `q_t` to adapt to the full past, provided they are fixed before `X_t` and the conditional
null bound continues to hold after conditioning on them.

For every stopping time `tau`, the stopped process `M_{tau wedge n}` has expectation at most
one. Nonnegativity and Fatou's lemma extend this to an unbounded almost-surely finite stop.
Ville's inequality gives

`sup_P P(sup_t M_t >= 1/alpha) <= alpha`,

where the supremum is over the composite null. Game termination, a horizon stop, and a
predeclared evidence crossing are therefore valid stops.

### Exact executable check

Command (deterministic; seed `N/A`; no sampled data; two affine-null endpoint evaluations and
one exact counterexample):

```sh
python -c 'from fractions import Fraction as F; p0=F(1,2); q=F(3,4); vals=[p*q/p0+(1-p)*(1-q)/(1-p0) for p in (F(0),p0)]; old=F(1,2)*F(5,3)+F(1,2)*F(1); print({"filtration":"visible completed economic events through t plus predictable candidate choices", "composite_null":"P(X_t=1 | F_{t-1}) <= 1/2 for every t", "candidate_increment":"(3/2)^X_t (1/2)^(1-X_t)", "conditional_expectation_endpoints":[str(v) for v in vals], "maximum":str(max(vals)), "historical_E_receiver_obedient_expectation_after_one_fair_trial":str(old), "candidate_valid":max(vals)<=1, "historical_score_invalid":old>1})'
```

Exact result:

```text
conditional expectation endpoints = [1/2, 1]
maximum under the null = 1
historical E_receiver_obedient null expectation = 4/3
candidate_valid = True
historical_score_invalid = True
```

Checking the two endpoints is decisive for the executable check because the conditional
expectation is affine in `p_t`; the displayed algebra is the proof for every
`p_t in [0,1/2]`.

## Historical `E_*` counterexample

The historical persuasion belief defines receiver obedience after `b` buys among `n` visible
yes recommendations as `(b+1)/(n+2)`, and its score is

`E_receiver_obedient = 1 + 4 max(0, obedience - 1/2)`.

It starts at one. After a single fair Bernoulli response under the null
`P(buy | F_0)=1/2`, it equals `5/3` after a buy and `1` after no buy. Hence

`E[E_receiver_obedient] = (1/2)(5/3) + (1/2)(1) = 4/3 > 1`.

It is not even a one-step e-value under this null. The mirrored skeptical score has the same
defect with the outcomes exchanged. Independently, historical `E_sample` is deterministically
greater than one as soon as a transcript row exists, with no compensating factor below one.
Taking the maximum of these scores in the control gate does not restore validity. These fields
are heuristic mode scores and must be absent when the e-process treatment is off; they cannot
be renamed or rescaled post hoc into the treatment.

## Nuisance and adaptivity conditions

- `p0_t=1/2` is fixed, so the proved construction has no estimated nuisance parameter.
- Replacing `p0_t` with an ordinary fitted or smoothed probability is not covered. For an exact
  counterexample, under a true fair Bernoulli null, one prior failure gives the Laplace estimate
  `p0_hat=1/3`. Plugging it into the next `q=3/4` likelihood ratio yields conditional mean
  `(1/2)(9/4) + (1/2)(3/8) = 21/16 > 1`.
- A context-dependent `p0_t` is allowed only if it is predictable and the declared composite
  null truly imposes the conditional upper bound almost surely. A point estimate from FIT data
  is not such a bound. A probabilistic upper bound would need its own error accounting or a
  joint e-process certificate.
- Choosing `q_t` from the past is valid; choosing it after seeing `X_t` is not.
- The event extractor must be fixed in advance, count each completed event exactly once, and
  never use a future transcript field.
- The mathematical state is the uncapped product (or the corresponding sum of exact log
  increments). Probability clipping or feeding a display cap back into later updates is not
  part of the certificate.
- Reset to `M_0=1` at every `game_id`; never carry evidence between scenarios or opponents.

## Interface verdict and exact obstruction

`GameState` exposes `game_id`, `round`, `horizon`, and `visible_transcript`. In the offline
bargaining and negotiation runner, each later state receives a prefix of the prior economic
transcript, so the concession event can be recomputed without mutable cross-game memory.

The interface is not uniformly prefix-monotone. A myopic persuasion buyer receives a fresh
current-round transcript plus aggregate market statistics, not earlier event rows. Reconstructing
a sequential event path there would either invent outcomes or retain memory the information
structure deliberately removes. The only valid R2 behavior in that state, absent a separately
proved aggregate-data e-process, is `M_t=1` (no update). This is a scoped feasibility obstruction,
not permission to infer missing binary outcomes.

The remaining global obstruction is economic rather than mathematical: the fixed null
`P(X_t=1 | F_{t-1}) <= 1/2` is a valid hypothesis, but no result yet shows that its rejection is
the right trigger for a payoff-improving action. Mathematical validity does not establish payoff
relevance.

## Decisive next test

Before any acting integration, implement a pure offline event extractor and exact-log updater,
then run one bounded certificate with these pass/fail conditions:

1. On hand-written bargaining and negotiation histories, extract the declared concession bits;
   replaying the same state is idempotent, and extending a prefix appends exactly one bit.
2. Exhaustively enumerate every binary path through horizon 20 at the boundary null `p=1/2`.
   At every fixed time, the probability-weighted mean of `M_t` must equal one, and the exact
   crossing probability for threshold `20` must be at most `0.05`.
3. Repeat with predictable `q_t` choices and an adversarial dependent null that selects
   `p_t` from `{0,1/2}` as a function of earlier bits and actions. Verify every conditional
   factor mean and the crossing bound.
4. Run misspecified cases with `p_t>1/2`, a plug-in `p0_t`, or post-outcome `q_t`. The verifier
   must label each case outside this certificate rather than report a null-valid crossing rate.
5. Feed duplicate rows, malformed rows, a truncated prefix, outcome-dependent missingness, and
   a non-prefix myopic state. The updater must reject the contaminated sequence or remain at one;
   it must never silently skip after observing the outcome.
6. Verify that numerical state stores log increments, rejects nonfinite parameters, and does not
   use probability clipping or a capped display value for subsequent updates.

This test is decisive for implementation correctness. A payoff experiment may begin only after
it passes and after the economic event-to-action mapping is frozen independently of outcomes.
