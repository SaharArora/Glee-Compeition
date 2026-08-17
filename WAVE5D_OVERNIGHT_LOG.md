# Wave 5D overnight log — Route 1 paper design

Scope: offline-only pre-outcome statistical design and synthetic infrastructure checks.
This route does not access treatment outcomes, receiver capability outputs, external APIs,
Model B, or live/rated games. Production authorization pins remain unset.

Campaign clock supplied by the root orchestrator: start `2026-08-17T04:20:34Z`; begin safe
shutdown by `2026-08-17T11:50:34Z`; terminate by `2026-08-17T12:20:34Z`.

## 2026-08-17T04:23:08Z — intake and frozen-contract audit

- Verified branch `research/wave5d-paper` starts at Wave 5C paper checkpoint
  `80a2b828ef92dbbd504b4384a64a39ac872d3c5a` and was initially clean.
- Read the complete Wave 5D directive and the frozen Wave 4/Wave 5A/Wave 5C estimand,
  factorization, controlled-receiver, manifest, evaluator, and report contracts.
- Confirmed the proposed Design A accounting: 3,600 paired scenario rows, 14,400 four-arm
  episodes, 600 receiver-eligible persuasion-seller rows, 48,000 nominal confirmatory receiver
  requests, and 96,000 maximum confirmatory attempts.
- Negative finding: 14,400 episodes and 48,000 receiver requests are workload counts, not
  statistical sample sizes. The paired scenario row is the arm-comparison unit, and repeated
  receiver calls within an episode are serial measurements nested below that unit.
- Negative finding: Design A repeats each base economic stratum across two receiver replicates,
  but the current report estimates variance from row contrasts as if rows were independent. It
  does not encode or cluster on the base-stratum identity required by the Wave 5A design note.
- Negative finding: pre-outcome outcome admission retains receiver failures, but
  `FactorialRow`/the report requires numeric payoffs and does not define a fail-closed ITT
  terminal-payoff rule when a receiver result is absent. A successful synthetic happy-path
  report therefore cannot establish production ITT readiness.
- Negative finding: the existing 12-hour receiver wall cap cannot exhaust the 96,200-attempt
  whole-route ceiling when all attempts consume their 30-second timeout at concurrency 32; the
  idealized service time alone is just over 25 hours before local episode/report overhead.

## 2026-08-17T04:26:40Z — prospective arithmetic and synthetic pipeline

- Implemented an outcome-blind standard-library planning module for effective N, worst-step Holm
  MDE, required cluster count, exact request/cost accounting, and idealized receiver service time.
- Reconstructed A300 exactly: 3,600 paired rows, 14,400 episodes, 600 maximum eligible paired
  rows in 300 base-stratum clusters, 48,100 whole-route nominal requests and 96,200 maximum
  attempts. At the Wave 5C price snapshot, primary nominal/retry-cap reservation is
  `$203.174400/$406.348800`; fallback is `$40.6348800/$81.2697600`.
- Central planning cell (`SD=.20`, `ICC=.50`, 10% information loss, 80% power, first Holm step)
  yields A300 effective N `360` and MDE `.0341062`. A200/A140/A100 yield `.0417714`,
  `.0499264`, and `.0590737`. The `.0100` reference would require 3,490 clusters per family under
  the same assumptions.
- Recommendation frozen at the design-audit level: retain A300, without production pins and
  without claiming it is powered for `.0100`. Smaller designs are cheaper but worsen already
  limited precision; A140 is the largest tested shape whose retry cap fits an idealized 12-hour
  service window when every attempt takes 30 seconds.
- Added a 12-row/48-episode synthetic-only stage-crossing test for manifest construction and
  reconstruction, four-arm paired evaluation, one retained missing receiver envelope, report
  construction and reconstruction, and verification that both production pins remain `None`.
  Route-specific result: `6/6` tests passed. Integrated manifest/receiver/evaluator/report/agent
  regression result: `79/79` tests passed in `5.016s`. This is infrastructure-only and supplies no
  treatment, receiver, payoff, or power evidence.
- Drafted paper-ready Methods and a Statistical Analysis Plan. Both make cluster-aware inference
  and the missing-receiver-to-terminal-payoff rule explicit activation prerequisites.

## 2026-08-17T04:33:08Z — terminal self-audit checkpoint

- Reconstructed the complete 96-cell MDE payload through the module CLI and validated its JSON.
- Validated the durable evidence JSON, all embedded implementation/methods/SAP hashes, and
  whitespace with `git diff --check`.
- Confirmed no production pin was changed; no external receiver, network, live game, Model B, or
  treatment outcome was touched.
- Route conclusion: candidate/self-audited design package complete. A300 remains the single
  recommendation, but production is blocked pending manifest-bound cluster inference and an exact
  ITT receiver-failure-to-payoff rule plus a fresh independent audit.
