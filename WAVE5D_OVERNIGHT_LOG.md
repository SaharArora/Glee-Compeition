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

## 2026-08-17 05:35Z — independent pre-fit FAIL; route terminated

- Froze clean pre-fit commit
  `1a1e8f7977e758faf4256993d3b75397a55057de`, contract SHA256
  `e431284df3ee243b175a02412a343e01d9db7b85f33a97d33a2f0c25d6fd315f`,
  and pass-only audit schema SHA256
  `ced5786dfdca5569b87662e1ea71091877faff54bee828e8318bf8b27eb0e7a5`.
- The fresh Route-1 owner audited the exact commit without inspecting structural
  outcomes. The audit ran `16` frozen tests successfully but returned FAIL after
  seven hostile mutations established six fatal objections: one ordering leak,
  two censor/trajectory defects, one partial-support inner-CV defect, and two
  supervisor defects.
- Preserved the verbatim audit as
  `research/EVIDENCE/WAVE5D_MODEL_A_V2_PREFIT_AUDIT.json`, SHA256
  `e2e65b0e37906d72b27265a1c47aeb877d0f3b45a2c6273a3db8deaeca72dc6d`.
- Root supplied no GO. No released corpus was extracted, no fit or OOF/structural
  score began, and no Model B, integration, payoff, API/network, or live action
  occurred. Per the Wave 5D one-formulation rule, no repair or third formulation
  is permitted; Route 2 is terminal.
- Terminal reconciliation reran the exact focused suite: `16` passed, `0`
  failed in `0.592s`. The verbatim audit byte-compares with the auditor source;
  JSON validation and `git diff --check` pass. Terminal evidence SHA256 is
  `e02fecdba4c67154c299c40edd2f2483544b7fb4a1474a5c8151cb152729a974`.
