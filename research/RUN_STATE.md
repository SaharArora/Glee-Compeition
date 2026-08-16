# Research run state

- Campaign state: `running`
- Latest user directive: establish the separate research/2x2 campaign under the root
  orchestrator contract; close R0 after its already-frozen failure; use bounded waves and
  durable repository state.
- Branch: `research/2x2-eprocess-language`
- Worktree: `/Users/sahararora/Glee-Research-2x2`
- Current commit: `bce578597dbfacf2ebca38399edb41a5dde2f936`
- Competition worktree: `/Users/sahararora/Glee-Compeition`, branch
  `agent/parallel-offline-work`, same committed revision plus uncommitted interrupted
  actor-factor construction work.
- Frozen historical event source: `data/processed/events.jsonl`, 8,214,931,069 bytes,
  1,188,434 lines/events, 80,872 contiguous games, SHA256
  `afc50fdf2f9c08feaf86355494db2bbd257c29ff4f9fbc8ed65f15e005329ad6`.
- Frozen failed Model-B report: `reports/model_b_crossfit_validation`, report SHA256
  `1a86cac280b1cd6b0049bc9429a6662f9d33b754dcfb23b4044e5b04ebbdacec`.
- Active processes: none.
- Interrupted process: `python3 -m glee_eval.population.actor_factor_crossfit_fit
  fit-fold --data-dir data --output-dir models/actor_factor_crossfit_v2 --manifest
  models/actor_factor_crossfit_v2/crossfit_manifest.json --axis actor --fold 0`.
  It was interrupted by the user-supplied R0 completion contract. It wrote no fold artifact
  or checkpoint and is not safe/authorized to resume unless the user explicitly reopens R0.
- Current orchestration wave: Wave 1 reconciled. Wave 2 may begin only with the bounded R1
  baseline isolation and fresh hostile audits of the exact R2/R3 candidates; R4 is paused on
  those dependencies. See `research/ROUTES/WAVE_1_SYNTHESIS.md`.
- Frozen baseline revision: none yet. Commit `bce5785` is rejected as the treatment-off
  mapping because its heuristic `E_*` control changes the first adversarial bargaining offer
  from the projected core's `56.0` to `62.0`. R1 owns a new isolated candidate version.
- Frozen evaluation protocol revision: `research/RESEARCH_QUESTION.md` revision 1 and
  `research/AUDIT_CHECKLIST.md` revision 1; R4 owns the executable pairing certificate.
- Live/rated authorization: no research arm has live/rated authorization. The competition
  campaign retains the user's instruction to start one leaderboard run after competition
  completion, but its exact durable command/cap must be reconciled in R5 before launch.
- Wave-1 evidence: R1 counterexample SHA `144cb7a943de614421deea2762891287b6cd6a98b2a61bf6dc2f893597baaa67`;
  R2 exact evidence SHA `f10597b69a18a0eaadfeae756f56ab8878178ad29189641547e742c59ad454fc`;
  R3 feasibility test SHA `23e32d0319010dd42c8b8a332033120b1ecd0ab4ea6c785717a5d9a9ad9b93e3`;
  R4 evaluator test SHA `2cdbe38545769d9f0dda0a91fc67ce2d8b1fa6b874b813410552300c4b03ef70`.
- Last reconciled: 2026-08-16 America/New_York, Wave 1 complete.
