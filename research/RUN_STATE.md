# Research run state

- Campaign state: `paused_after_wave_2_checkpoint`
- Latest user directive: execute only Research Wave 2's four bounded deliverables, update
  durable evidence, commit/push a checkpoint, and report before any treatment payoff,
  Wave 3, rated game, generation project, or Model-B reuse.
- Branch: `research/2x2-eprocess-language`
- Worktree: `/Users/sahararora/Glee-Research-2x2`
- Wave-2 base commit: `895ffee341cd4893373e32d5f8c1a5375549e0e6`
- Current checkpoint commit: this durable Wave-2 checkpoint (see branch `HEAD`).
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
- Current orchestration wave: Wave 2 is complete and stopped at its required report boundary.
  R1 exists as a self-audited treatment-off interface; R2 has a verifier-backed narrow theorem
  but no justified economic null; R3 recommends observational/feasibility only and awaits user
  choice; R4 is verifier-backed blocked for active-treatment scoring.
- Frozen baseline revision: `research/CANDIDATES/r1_treatment_off_baseline.py` SHA256
  `95bf90cfb63bde3b78aa9bdd5140de902016bd6413b25b910d8bebf80f885fef` at base
  `895ffee`; 8 parity tests pass. No baseline payoff or treatment run occurred.
- Frozen evaluator candidate: `glee_eval/experiments/factorial.py` SHA256
  `bda3da00922ffcb9e931a95febfa885673a0f778b67d04771243398127011f14`.
  Its seven inert canaries pass, but hostile audit SHA256
  `f37dc7454ef90018e31dfb22d06ba51f838723b94108dee917628d02f56dfd35`
  blocks active scoring because cross-stream RNG consumption is accepted when inert equality is
  disabled.
- Live/rated authorization: no research arm has live/rated authorization. The competition
  campaign retains the user's instruction to start one leaderboard run after competition
  completion, but its exact durable command/cap must be reconciled in R5 before launch.
- Wave-2 execution boundary: no holdout, fit, treatment payoff comparison, Wave 3, generation
  logic, text-opponent project, Model-B gate, or live/rated game was run.
- Wave-1 evidence: R1 counterexample SHA `144cb7a943de614421deea2762891287b6cd6a98b2a61bf6dc2f893597baaa67`;
  R2 exact evidence SHA `f10597b69a18a0eaadfeae756f56ab8878178ad29189641547e742c59ad454fc`;
  R3 feasibility test SHA `23e32d0319010dd42c8b8a332033120b1ecd0ab4ea6c785717a5d9a9ad9b93e3`;
  R4 evaluator test SHA `2cdbe38545769d9f0dda0a91fc67ce2d8b1fa6b874b813410552300c4b03ef70`.
- Wave-2 evidence: `research/EVIDENCE/R1_BASELINE_PARITY.json`,
  `research/EVIDENCE/R2_EPROCESS_WAVE2_VERIFICATION.json`,
  `research/EVIDENCE/R3_LANGUAGE_DECISION.json`, and
  `research/EVIDENCE/R4_FACTORIAL_INTEGRITY.json`.
- Last reconciled: 2026-08-16 America/New_York, Wave 2 complete; awaiting user direction.
