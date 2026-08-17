# Wave 5D overnight log — Route 2

Scope: offline-only bargaining Model-A v2 in
`research/wave5d-model-a-v2`. No network, API, live game, Model B, or dirty-main
worktree access is authorized.

## 2026-08-17 04:20:34Z — campaign clock received

- Root supplied the campaign start, 11:50:34Z safe-shutdown boundary, and
  12:20:34Z hard stop.
- Isolated worktree was clean at
  `c9c2c030606e1eca4676e6f9f7b0ed4561f52592`.
- Wave 5C terminal audit and all eight fatal objections were reviewed before
  implementation. No released corpus, structural outcomes, API, or live state
  was inspected.
- Began with a separate fail-closed external supervisor. It applies a
  per-process address-space backstop, independently monitors aggregate process
  tree RSS and worker threads, owns monotonic deadline termination, uses
  SIGTERM/grace/SIGKILL, writes one fsync-backed atomic certificate, and has no
  restart path.

## 2026-08-17 05:08Z — first implementation checkpoint

- The supervisor passed real disposable wall-time and aggregate-RSS violation
  tests. A 128 MiB child was independently observed above a 64 MiB test ceiling,
  received process-group termination, and left an atomic failure certificate.
- Implemented the separate v2 extractor, exact executable schema-v1 comparator,
  censor-aware trajectory evaluator, equal-game nested-CV objective, stable
  content row IDs, strict audit gate, and all three Jordan-reached diagnostics.
- Fifteen focused synthetic/hostile tests passed. The suite includes future and
  private-state poison, duplicate observational IDs, explicit right censoring,
  unequal-fold weighting, boulware parity against the real policy class, audit
  fail-closed mutations, and exact diagnostic labels.
- Began freezing the new contract and audit schema. Released corpus extraction,
  fitting, structural scoring, and integration remain at zero.
