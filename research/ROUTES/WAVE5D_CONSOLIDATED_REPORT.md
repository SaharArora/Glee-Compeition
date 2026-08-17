# Wave 5D consolidated offline report

Status: **terminal offline campaign; no network, API, receiver, live/rated game, Model B, fit,
structural-outcome score, production pin, policy modification, or promotion occurred.** The
campaign began at `2026-08-17T04:20:34Z` and all routes reached their fail-closed terminal states
before the first 90-minute log interval and before the `11:50:34Z` safe-shutdown boundary.

Because the shared repository's Git metadata was outside the session's writable roots, the three
normal worktrees would have required an unattended approval. Root did not wait. Instead, each
route used an isolated local shared clone under `/private/tmp`, pinned to its declared base, and
committed locally. Network push was prohibited by the Wave 5D authorization.

## Route outcomes

| Route | Local branch / terminal commit | Verdict |
| --- | --- | --- |
| Paper design | `research/wave5d-paper` / `5590a5c1ff505a8395cdbe8c37ddddd5edc232d8` | A300 retained only as a prospective conditional recommendation; production remains blocked. |
| Model-A v2 | `research/wave5d-model-a-v2` / `854ea7bec45e6eb790081dd7318e9387d923e2a1` | Independent pre-fit **FAIL**; no extraction or fit and no third formulation. |
| Competition preparation | `research/wave5d-competition-prep` / `2810a124407e55371edf88efc889e01d1ff1d6a9` | Two hypothesis-only Jordan-v2 routes; no implementation or promotion. |

All three route worktrees were clean at terminal verification. They are local-only and unpushed.

## Paper design and MDE result

The paired experimental row is one scenario reused by all four forced arms. Four arm episodes are
repeated measures, the two hosted-receiver replicates are nested in one base economic stratum, and
the twenty receiver decisions per episode are serial nested measurements. For the eligible
persuasion-seller primary analysis, A300 has at most 600 paired rows in only **300 independent
clusters**. Neither 14,400 episode executions nor 48,000 confirmatory requests is a sample size.

The prospective planning calculation uses two-sided familywise alpha `.05`, three Holm hypotheses,
the most stringent first step `.05/3`, and 80% power. Under the central planning assumptions of
contrast SD `.20`, receiver-replicate ICC `.50`, and 10% information loss:

| Design | Paired rows | Episodes | Independent primary clusters | Effective N | MDE | Nominal / max requests | Primary nominal / retry-cap cost | Idealized 30s service |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A300 | 3,600 | 14,400 | 300 | 360 | 0.03411 | 48,100 / 96,200 | $203.1744 / $406.3488 | 12h32m / 25h03m30s |
| A200 | 2,400 | 9,600 | 200 | 240 | 0.04177 | 32,100 / 64,200 | $135.5904 / $271.1808 | 8h22m / 16h43m30s |
| A140 | 1,680 | 6,720 | 140 | 168 | 0.04993 | 22,500 / 45,000 | $95.0400 / $190.0800 | 5h52m / 11h43m30s |
| A100 | 1,200 | 4,800 | 100 | 120 | 0.05907 | 16,100 / 32,200 | $68.0064 / $136.0128 | 4h12m / 8h23m30s |

The full prespecified grid spans contrast SD `.10` to `1.00`, ICC `0` to `.75`, and information
loss `0` to `.20`. Under the central assumptions, an MDE of `.0100` would need about 3,490
independent strata per family: 41,880 paired rows, 167,520 episodes, 558,500 nominal requests and
about $2,359.10 primary nominal cost. A300 is therefore defensible only if effects around `.035`
or larger are scientifically meaningful. It is not justified for `.0100`.

Route 1 recommends A300 over smaller A-shaped designs because hosted receiver variability still
requires two replicates and each smaller design worsens already limited precision. The
recommendation is not production-ready. Four blockers remain:

1. the manifest/report does not bind or use the base-stratum cluster identity;
2. receiver failure is retained by admission, but no treatment-blind failure-to-environment and
   numeric-payoff ITT rule is frozen;
3. no blinded contrast variance or smallest scientifically important effect is accepted;
4. A300's nominal and retry-cap service envelopes conflict with the existing 12-hour wall cap.

Both production pins remain `None`. A 12-row/48-episode synthetic pipeline test passed and is
labelled infrastructure-only non-evidence.

Paper-ready artifacts:

- `research/ROUTES/WAVE5D_PAPER_METHODS.md`
- `research/ROUTES/WAVE5D_STATISTICAL_ANALYSIS_PLAN.md`
- `research/EVIDENCE/WAVE5D_PAPER_DESIGN_AUDIT.json`

## Model-A v2 verdict

The implementation owner froze pre-fit commit
`1a1e8f7977e758faf4256993d3b75397a55057de`; its contract SHA-256 is
`e431284df3ee243b175a02412a343e01d9db7b85f33a97d33a2f0c25d6fd315f`.
An independent Route-1 auditor verified the source and all locked hashes without inspecting a
released outcome row. Sixteen frozen tests passed, but hostile synthetic mutations produced six
fatal objections:

1. same-round opposite-role decisions can enter the supposedly strict `t-1` feature boundary;
2. an unparseable terminal callback is silently dropped and the prior offer becomes censored;
3. an ordinary player-1 offer/player-2 acceptance makes the nonterminal role's complete
   trajectory invalid;
4. failed inner validation predictions can drop a fold/game while the remaining folds yield a
   finite selection score;
5. a detached new-session descendant can outlive a supervisor success certificate;
6. fast artifact-limit violations evade the final poll, and spawn failure writes no terminal
   certificate.

The independent audit SHA-256 is
`e2e65b0e37906d72b27265a1c47aeb877d0f3b45a2c6273a3db8deaeca72dc6d`.
Per the one-formulation rule, the route stopped. There are zero extracted rows, fits, OOF rows,
structural scores, Jordan diagnostics on outcomes, integrations or payoff results. Model-A need
remains prior candidate/self-audited evidence only; prediction, structural validation, untouched
confirmation and payoff value remain untested.

## Competition preparation and Jordan-v2 hypotheses

Route 3 reused only the already-exposed 900-row Wave 5B development ledger. Factorial00 minus
Jordan by family/role was:

| Cell | N | F00 - Jordan |
| --- | ---: | ---: |
| Bargaining player 1 | 168 | +0.14543 |
| Bargaining player 2 | 132 | +0.17844 |
| Negotiation buyer | 156 | +0.00445 |
| Negotiation seller | 144 | +0.01383 |
| Persuasion buyer | 163 | -0.00006 |
| Persuasion seller | 137 | -0.05730 |

All 67 persuasion-seller non-ties favored Jordan and 70 tied. Source alignment points to removal
of Jordan's late obedience-gated low-quality seller EXPLOIT branch, but the development ledger has
terminal payoffs rather than action traces. Causal attribution is therefore **underidentified**.

Exactly two unimplemented hypotheses were frozen:

1. `jordan_v2_family_local_neutral_control`: force SAFE control only in bargaining and
   negotiation while keeping Jordan persuasion byte-identical. First cheap development kill-check:
   replay the exposed 900 identities, require persuasion action parity, no affected cell below
   `-.005`, bargaining at least `+.020`, overall at least `+.010`, and gain concentration at most
   `.50`.
2. `jordan_v2_memory_aware_seller_exploitation`: replace only the low-quality persuasion-seller
   EXPLOIT branch with prespecified Wilson-LCB and myopic/persistent timing gates. Development
   kill-check requires changes only in eligible turns, seller mean at least `+.005`, nonnegative
   myopic and persistent means, no regime below `-.010`, concentration at most `.50`, and zero
   illegal/private reads.

Neither hypothesis is implemented. Both require a new prospectively frozen, structurally
disjoint, non-Model-B confirmation before any separately authorized live evaluation.

## Morning setup

The exact attended GLEE command is in
`research/ROUTES/WAVE5D_MORNING_CHECKLISTS.md` on the competition-prep branch. It requires a clean
detached Route-L head `f2a1bb5afe6f83c3a8a03201a0e5939f748ecda9`, policy commit
`bce578597dbfacf2ebca38399edb41a5dde2f936`, `glee-sdk==0.0.5`, hidden key prompt, a new
mode-0600 HMAC secret, all optional artifacts unset, a fresh `/stats` identity and
`active_games==0` check before queueing, and unconditional reconciliation plus hostile audit.
It remains unauthorized by Wave 5D.

The OpenAI receiver capability path remains `NO-GO_ADAPTER_ABSENT`. Before any external request,
select and independently review a provider adapter and dependency lock, freeze their hashes and
transport import, provide the key through a hidden prompt, use approved encrypted storage, and
pre-reserve `5,000` microusd for each of at most 200 attempts—an exact `$1.00` software ceiling.
The frozen capability rule still requires complete probe identities and at least 5/25 text-only
decision changes in each replicate. An API key alone is insufficient.

## Evidence and claims

Gained:

- exact prospective unit, cluster, repeated-measure, MDE, workload, cost and runtime arithmetic;
- paper-ready Methods and SAP drafts;
- one conditional A300 recommendation with explicit precision and infrastructure blockers;
- a fresh independent refutation of the single Model-A-v2 formulation;
- exact development-ledger behavior differences and two falsifiable, unimplemented Jordan-v2
  hypotheses;
- attended morning setup checklists with fail-closed identity, spend and telemetry boundaries.

Still prohibited:

- receiver capability or responsiveness;
- adequate power for `.0100` or production-valid clustered/ITT reporting;
- any e-process, language, interaction, payoff or causal treatment result;
- Model-A predictive, structural, confirmation, payoff or integration claim;
- causal attribution of the persuasion-seller development gap;
- Jordan-v2 improvement, promotion or leaderboard competitiveness;
- Model B support for any route;
- any claim based on the synthetic pipeline as scientific evidence.

## First actions tomorrow

- **Research:** repair and independently re-audit the A300 manifest/report cluster identity and
  frozen receiver-failure ITT continuation/payoff rule, then prospectively accept an effect-size
  target and reconcile the wall cap. Do this before receiver capability or production pins.
- **Leaderboard:** in an attended session, use the frozen Route-L checklist to provision secrets,
  require fresh identity plus `active_games==0`, and only then launch the separately authorized
  bounded Jordan canary. Do not modify Jordan first.

