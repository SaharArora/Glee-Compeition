# Research run state

- Campaign state: `wave_4_checkpoint_complete_waiting_for_language_environment_selection`
- Latest user directive: checkpoint Wave 3; freeze the exact baseline artifacts; finish and
  independently audit R4; settle R2, R3, family feasibility, and estimands; stop before any
  factorial payoff, large text-responsive simulator, Model-B reuse, or live/rated game.
- Branch: `research/2x2-eprocess-language`
- Worktree: `/Users/sahararora/Glee-Research-2x2`
- Wave-3 base commit: `fd05023de6ef87bb9d9e8f0f20044052569041b6`
- Wave-3 implementation commit: `a1438d0878dd89fff7d71accc7ddc7faebac983b`.
- Wave-3 implementation state: reviewed, tested, committed, and pushed to
  `origin/research/2x2-eprocess-language`; a follow-up provenance commit records that immutable
  implementation SHA without pretending a git commit can contain its own identity.
- Competition worktree: `/Users/sahararora/Glee-Compeition`, branch
  `agent/parallel-offline-work`, same committed revision plus uncommitted interrupted
  actor-factor construction work.
- Frozen historical event source: `data/processed/events.jsonl`, 8,214,931,069 bytes,
  1,188,434 lines/events, 80,872 contiguous games, SHA256
  `afc50fdf2f9c08feaf86355494db2bbd257c29ff4f9fbc8ed65f15e005329ad6`.
- Frozen failed Model-B report: `reports/model_b_crossfit_validation`, report SHA256
  `1a86cac280b1cd6b0049bc9429a6662f9d33b754dcfb23b4044e5b04ebbdacec`.
- Model-B state: the mixed-fold validation failed and R0 is closed. No Model-B process is
  active or authorized; the interrupted hierarchical actor-factor work is preserved but may
  not supply tournaments, gates, the research baseline, or e-process validity.
- Active processes: none. No Model B, factorial payoff, external-model, or live/rated process ran.
- Interrupted process: `python3 -m glee_eval.population.actor_factor_crossfit_fit
  fit-fold --data-dir data --output-dir models/actor_factor_crossfit_v2 --manifest
  models/actor_factor_crossfit_v2/crossfit_manifest.json --axis actor --fold 0`.
  It was interrupted by the user-supplied R0 completion contract. It wrote no fold artifact
  or checkpoint and is not safe/authorized to resume unless the user explicitly reopens R0.
- Current orchestration wave: Wave 3 implementation is complete and stopped at its report
  boundary. Four forced entrypoints exist. R2 acts only on persuasion-seller prior-round buyer
  obedience relative to hash-locked Model C. R3 acts only on text-enabled persuasion-seller
  rendering, so the two interventions overlap primarily in eligible persuasion-seller cells.
  The offline receiver is text-blind and no treatment payoff result exists. R4's report verifier
  has a fresh independent version-bound audit: the production authorization pin is intentionally
  absent, so no payoff contract can pass before language-environment selection and exact
  pre-outcome manifest freezing.
- Frozen baseline revision: `research/CANDIDATES/r1_treatment_off_baseline.py` SHA256
  `95bf90cfb63bde3b78aa9bdd5140de902016bd6413b25b910d8bebf80f885fef` at base
  `895ffee`; 8 parity tests pass. No baseline payoff or treatment run occurred.
- Frozen Wave-3 agent candidate: `research/CANDIDATES/wave3_factorial_agents.py` SHA256
  `b0c3f286e6e9ef5a28c209cd11b11d0dd0092105fd52d49ed96554a45b84c319`.
  Entrypoints force `00`, `10`, `01`, and `11`; override attempts fail.
- Frozen Wave-3 evaluator candidate: `glee_eval/experiments/factorial.py` SHA256
  `1ca9d360073cb59fa7df972ae140796f1585cae6d27ec7d5229ba9670be4bbb3`.
  It separates scenario, environment, opponent, economic, e-process, and language streams and
  rejects the Wave-2 active contamination counterexample.
- Live/rated authorization: no research arm has live/rated authorization. The competition
  campaign retains the user's instruction to start one leaderboard run after competition
  completion, but its exact durable command/cap must be reconciled in R5 before launch.
- Wave-3 execution boundary: no holdout, fit, treatment payoff comparison, large text-opponent
  project, Model-B gate, or live/rated game was run. Synthetic unit episodes are canaries, not
  a treatment-effect estimate.
- Wave-1 evidence: R1 counterexample SHA `144cb7a943de614421deea2762891287b6cd6a98b2a61bf6dc2f893597baaa67`;
  R2 exact evidence SHA `f10597b69a18a0eaadfeae756f56ab8878178ad29189641547e742c59ad454fc`;
  R3 feasibility test SHA `23e32d0319010dd42c8b8a332033120b1ecd0ab4ea6c785717a5d9a9ad9b93e3`;
  R4 evaluator test SHA `2cdbe38545769d9f0dda0a91fc67ce2d8b1fa6b874b813410552300c4b03ef70`.
- Wave-2 evidence: `research/EVIDENCE/R1_BASELINE_PARITY.json`,
  `research/EVIDENCE/R2_EPROCESS_WAVE2_VERIFICATION.json`,
  `research/EVIDENCE/R3_LANGUAGE_DECISION.json`, and
  `research/EVIDENCE/R4_FACTORIAL_INTEGRITY.json`.
- Wave-3 evidence: `research/EVIDENCE/WAVE3_IMPLEMENTATION_CHECKPOINT.json`; R2 and R3 exact
  scopes are in `research/ROUTES/R2_EPROCESS_WAVE3.md` and
  `research/ROUTES/R3_LANGUAGE_WAVE3.md`.
- Wave-4 baseline: Model-C SHA `9daec869...b82c`, support SHA `b9587765...9145`, non-Model-B
  structural holdout population SHA `33711317...51d`, config catalogue SHA `2a32c01d...e2ae`;
  full contract is `research/EVIDENCE/WAVE4_BASELINE_CONTRACT.json`.
- R2 verdict: nontrivial distribution-free population extension killed; exact surviving label is
  `model-relative e-process against a fixed hash-locked Model-C reference`.
- R3 decision: primary recommendation is a separately owned controlled frozen text-responsive
  receiver, initially persuasion-seller; secondary is prospectively randomized live assignment.
  Neither is authorized. The current offline language/interaction populations are empty.
- Family expansion: bargaining/negotiation e-process and all current-offline language expansions
  are unsupported; no treatment expansion selected.
- R4 verdict: verifier-backed exact obstruction at report SHA `23cdbe69...f270`; production
  contract pin remains `None`. Any activated pin requires a new independent audit.
- Last reconciled: 2026-08-16 America/New_York, bounded Wave 4 completion condition reached;
  waiting for the user's explicit language-environment selection before any next build.
