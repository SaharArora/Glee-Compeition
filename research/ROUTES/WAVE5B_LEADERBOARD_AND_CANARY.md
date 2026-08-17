# Wave 5B leaderboard proxy and live-canary decision

Status: **operationally ready to deploy (state 1); not yet ready for the bounded canary (state 2).**

No live/rated game was queued in Wave 5B. The obstruction to state 2 is narrow and operational:
the current launcher does not record the exact agent commit or an official per-game scoring/update
payload. Running another batch before fixing those fields would repeat the identifiability failure
measured below.

## Proxy back-test: what is and is not identified

The audit uses every terminal-complete strict log on disk: 61 bargaining, 60 negotiation and 60
persuasion games across confirmation, volume and volume2. Complete configurations, roles, terminal
payoffs and batch-end displayed ratings are available. However:

- launch manifests record `my_agents.jordan_strategic:MyAgent` but no git commit;
- official per-game percentile/game rating/update was never captured;
- opponent-strength and private adjustment inputs are absent or hidden; and
- confirmation contains ten terminal persuasion records while the official game counter advanced
  by nine, so that family is not exactly attributable at the batch boundary.

Consequently **zero batches meet every formal attribution requirement**. Per-game bias, MAE,
correlation, interval coverage and ranking agreement are not identifiable, and the audit does not
reverse-engineer fictitious labels.

There is still a useful class-attributed batch sensitivity check. In the two 75-game batches whose
family counts reconcile exactly, the public shadow proxy over-predicts the observed displayed
endpoint by approximately:

| Family | Batch endpoint bias/MAE | Median AE | Exact-config percentile coverage |
|---|---:|---:|---:|
| Bargaining | +55.60 rating points | 55.60 | 60–72% across the two batches |
| Negotiation | +125.77 | 125.77 | 20–24% |
| Persuasion | +69.98 | 69.98 | 0% |

This is not a calibrated correction: only two exact-count endpoints per family exist, and the
unobserved official adjustment is confounded with every other approximation. It is direct evidence
that a single shadow number is overconfident, especially for negotiation.

## Required four-part forecast

From the 181 class-attributed games, the four distinct outputs are:

| Family | Raw exact-config percentile | Public-formula mean game rating | Empirically calibrated proxy | Sensitivity at 300 / 500 games |
|---|---:|---:|---|---|
| Bargaining | .445 | 2127 | unavailable | point 1445 / 1660; empirical endpoint bands 1386–1505 / 1601–1720 |
| Negotiation | .347 | 2521 | unavailable | point 1459 / 1793; bands 1328–1590 / 1661–1924 |
| Persuasion | unavailable (0 exact support) | 2387 | unavailable | point 1539 / 1807; bands 1462–1616 / 1730–1884 |

Every band is only a captured batch-end sensitivity envelope. The private opponent-adjustment
envelope remains **unbounded from captured fields**, so none is a placement guarantee. Current
official displayed ratings are 1138.91 bargaining, 1003.47 negotiation and 1156.72 persuasion at
105/104/104 games respectively.

Exact machine-readable evidence is
`research/EVIDENCE/WAVE5B_LEADERBOARD_PROXY.json`.

## Shared-backbone benchmark and candidate selection

The prospectively frozen 900-scenario paired benchmark compared Jordan with Factorial00 on the
same non-Model-B holdout population/catalogue. Factorial00 minus Jordan was +.04757 overall
(256 wins, 109 losses, 535 ties): +.15995 bargaining, +.00895 negotiation and -.02620 persuasion.
The persuasion seller cell was -.05730. This is an offline architecture diagnostic—not a
promotion gate—and the evaluator itself has the Model-A defects documented in this wave.

Select **current production Jordan**, not Factorial11 or Factorial00, for the first canary:

- Factorial11 would be selected from unrun treatment effects, which is prohibited.
- Factorial00 is a research economic backbone requiring frozen research artifacts and currently
  shows a material persuasion-seller regression; it has no independently validated competition
  promotion or live adapter.
- Jordan has terminal-complete operational history and an already deployed entrypoint. Its source
  at competition commit `bce578597dbfacf2ebca38399edb41a5dde2f936` is byte-identical to this
  checkpoint (`my_agents/jordan_strategic.py` SHA-256
  `27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82`).

This does not claim Jordan is best. It is the least confounded candidate for measuring the platform
properly before a later independently validated competition-only candidate exists.

## Concrete unexecuted canary contract

### Identity and environment

- candidate commit: `bce578597dbfacf2ebca38399edb41a5dde2f936`;
- entrypoint: `my_agents.jordan_strategic:MyAgent`;
- one platform agent identity: UUID `99357c15-48d5-4177-9d6a-48d02b95a164`, name
  `gangsteryoshi`; abort if the authenticated identity differs;
- exact artifact state: `GLEE_OPPONENT_POPULATION`, `GLEE_CONFIG_CATALOGUE`,
  `GLEE_RESPONSE_MODEL` and `GLEE_SUPPORT_INDEX` all absent. Supplying one would change the
  deployed policy and requires a new contract;
- source tree clean and commit verified immediately before queueing; launcher/live-adapter source
  SHA `383fcf7b9e72cd00642960293d5931a54ecf0f26673658b5d9976bbcd7a13403`.

### Scope and queueing

- exactly 100 terminal games per family, 300 total, one strict cap;
- concurrency three, at most one active/queued request per family per wave; rotate family order
  between waves;
- never combine `--max-games` with `--max-time`; no second run if the cap, identity or logging
  invariant fails;
- new empty output directory; observations, submitted actions, every move result, terminal
  backfills, launch manifest and before/after platform stats retained.

Before this command becomes executable, the live adapter must add: exact git commit/dirty digest;
per-family game count and displayed rating immediately before and after each completion; official
per-game percentile/game rating/update and public opponent adjustment fields when exposed; and an
explicit absent-capability marker when not exposed. With one active game per family, rating
snapshots cannot be confounded by a second completion in that family.

### Validity and stopping

- terminal capture: 100%; any unresolved terminal after backfill stops new queues;
- invalid/fallback actions: at most 1%; three invalid/fallback actions in any family stop the run;
- timeouts/API failures: at most 2%; three in any family pause that family;
- duplicate/unattributed game, agent-identity change, cap overrun, or missing commit/scoring
  provenance: immediate global stop;
- after at least 30 completed games in a family, pause it if the one-sided 95% upper confidence
  bound for mean official per-game rating is below 1800;
- global gross-underperformance stop after at least 30 per family if two families meet that pause
  rule or the pooled family-balanced upper bound is below 1800;
- normalized payoff is a secondary drift alarm against the existing terminal-complete means
  (B .40741, N .07953, P .41733), never a substitute for official per-game rating.

### Success, expansion and rollback

Success for expansion requires all 300 terminals, every integrity bound above, and in each family a
95% lower confidence bound for mean official per-game rating at least 2000. Then—and only under a
new authorization—expand the same frozen tuple to 300–500 total games per family. Sustained
high-volume play requires those expanded intervals, role/config support, drift checks, and no
family pause; a claim of top-five or winning additionally requires actual contemporaneous
leaderboard rank/competition evidence, not the shadow proxy.

Rollback means stop queueing, drain and capture already active games, preserve the failed batch,
and restore the previously frozen whole deployment tuple. It never deletes results, silently
changes a family, or switches candidates mid-run.

## Readiness statement

1. **Operationally ready to deploy:** yes; already demonstrated.
2. **Ready for a bounded live canary:** no, pending exact commit and per-game official scoring
   capture in the adapter.
3. **Showing preliminary competitive performance:** not established by attributable per-game
   evidence.
4. **Plausibly top-five competitive:** not established.
5. **Demonstrating a winning agent:** not established.
