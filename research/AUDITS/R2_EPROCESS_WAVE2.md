# Wave 2 hostile verification — R2 fixed-bound e-process

Verdict: **PASS for the narrow, single-stream mathematical claim; not an acting-treatment
certificate.** Version bound to repository commit
`895ffee341cd4893373e32d5f8c1a5375549e0e6` and candidate
`research/ROUTES/R2_EPROCESS.md` SHA-256
`458a72d3d6b13cf1d8b83713a2b209895e942bd0c17c2dcfde1c5c7325840c7f`.

## Independent reconstruction

For one preregistered binary event stream, let
`p_t=P(X_t=1 | F_{t-1})`. The null is not Model B, an actor-factor model, an iid
Bernoulli distribution, or an estimated population. It is the composite class of every
possibly dependent/adaptive law satisfying `p_t <= 1/2` almost surely at every indexed
opportunity. The working alternative `q=3/4` defines the bet but need not be true.

With `L_t=3/2` for success and `L_t=1/2` for failure,

`E[L_t | F_{t-1}] = (3/2)p_t + (1/2)(1-p_t) = 1/2+p_t <= 1`.

Because `M_t=M_{t-1}L_t`, `M_0=1`, and `M_{t-1}` is measurable and nonnegative,
`M_t` is a nonnegative supermartingale under every law in that class. Independence,
Model-B draws, and fitted nuisance probabilities are unnecessary. At the two affine
endpoints `p=0,1/2`, the exact means are `1/2,1`.

For the stated general predictable kernel,

`E[L_t|F_{t-1}] = 1 + (p_t-p0_t)(q_t-p0_t)/(p0_t(1-p0_t)) <= 1`

when `0<p0_t<=q_t<1` and the null really guarantees `p_t<=p0_t` after conditioning
on every predictable action/randomization variable. Normalization is therefore exact;
the fixed candidate has no zero/near-zero denominator or numerical clipping.

For a bounded stopping time the stopped expectation is at most one. For an unbounded
almost-surely finite stopping time, nonnegativity plus Fatou gives the same bound. Ville's
inequality consequently controls a crossing of this one process at `1/alpha` by `alpha`.

## Hostile boundary checks

- **Filtration and predictability:** The action, its random coin, event definition,
  `p0_t`, and `q_t` must be fixed before `X_t`. Choosing any of them after reading the
  offer/outcome breaks the proof. The repository exposes prefix histories, but no updater
  yet verifies prefix extension, uniqueness, or predictable missingness.
- **Event indexing:** “First opponent offer fixes an anchor” must be implemented as one
  frozen comparison rule (for example, successive opponent-own offers); it cannot change
  between anchor-relative and previous-offer-relative comparisons after outcomes are seen.
  A counteroffer opportunity may be indexed only after its existence is known and before
  its direction is revealed. Declined/terminated paths cannot be silently deleted after
  learning a would-be outcome.
- **Game and mode resets:** Resetting to one at a new `game_id` is valid for a new
  per-game process. Resetting after an unfavorable within-game mode switch and retaining
  favorable crossings is repeated testing and is not covered. A mode switch must preserve
  the same process state or be included in a prospectively multiplicity-controlled family.
- **Multiplicity:** Each separate event definition, role, family, or game-specific process
  is individually e-valid under its matching null. Taking their maximum, selecting a
  favorable one, or acting when any crosses does not inherit the single-process `alpha`
  bound. A prespecified convex e-mixture (weights summing to one), product justified by
  conditional factors, or alpha allocation is required. No such global construction is
  claimed in the frozen candidate.
- **Training-estimated probabilities:** None enter the fixed `p0=1/2,q=3/4` proof. A FIT
  point estimate is not a conditional upper bound. After one failure, Laplace `p0=1/3`
  with `q=3/4` has fair-null mean `21/16>1`, so naive plug-in is invalid.
- **Coverage:** The certificate covers only the declared binary concession stream. It does
  not automatically cover acceptance, purchase, recommendation, continuous offer size,
  censored terminal events, or aggregate persuasion statistics. Each needs a fixed outcome,
  filtration, and defensible conditional null bound. A myopic persuasion buyer cannot
  reconstruct a hidden event path; remaining at `M=1` is the only covered behavior.
- **Historical scores:** With one visible yes recommendation, a fair buy gives historical
  `E_receiver_obedient=5/3` and a no-buy gives `1`; its mean is `4/3>1`.
  `E_sample>1` merely because rows exist. Neither is an e-value, and maximizing such scores
  cannot repair validity.

## Exact narrower guarantee and remaining gap

The guarantee is only this: **for one fixed binary event definition within one game, under
all adaptive laws whose conditional success probability is at most one half at every
predictably indexed opportunity, the uncapped product of `3/2` on success and `1/2` on
failure is an e-process, and a single threshold crossing has Ville control.**

The smallest remaining mathematical gap is not normalization or optional stopping; it is
justification of the economic null itself. No allowed frozen evidence establishes that
opponent concession probability is conditionally at most `1/2` after every visible history
and candidate action. Without that substantive bound, the process remains a valid test of
a clearly stated hypothesis but cannot be interpreted as calibrated evidence about a
generic opponent type or as a payoff-relevant trigger. Multiplicity design and an executable
prefix-safe extractor are additional prerequisites for acting integration.

