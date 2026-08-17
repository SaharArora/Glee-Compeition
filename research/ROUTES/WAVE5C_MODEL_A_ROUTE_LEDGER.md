# Wave 5C Route A ledger

Status: **terminal pre-fit FAIL / NO-GO. No corpus extraction, fit or
structural-holdout scoring occurred.**

The machine-readable authority is `WAVE5C_MODEL_A_PREFIT_CONTRACT.json`. Route A
implements only a bargaining sequential behavior candidate and its development
OOF evaluator. It does not change the simulator, Jordan, the four factorial
agents, Model B, Model C, any promotion gate, or any live policy.

## Pre-fit audit questions

The fresh auditor must answer all of these against the exact frozen hashes:

1. Can any feature read terminal payoff/outcome, a future transcript item, hidden
   incomplete-information delta, held-out actor/config identity coefficient, or
   the target itself?
2. Do the three actor folds contain exactly five of the 15 acting identities and
   do the four config folds implement the declared canonical hash mapping?
3. Does each row receive exactly one prediction on each outer axis, with all
   inner selection restricted to the corresponding training complement?
4. Are the action probabilities coherent, the CRPS/energy/log-loss/Brier formulas
   proper, the calibration tests literal, and the nested bootstrap faithful?
5. Is the interpretation of “20 clusters” as 20 nested game clusters consistent
   with the frozen statement that the actor axis contains exactly 15 primary
   identities? If not, the pre-fit audit must fail rather than silently relax it.
6. Does observed-prefix trajectory reconstruction satisfy the frozen trajectory
   endpoint without treating later prefixes as earlier information? If not, the
   pre-fit audit must fail.
7. Does zero/degenerate walkaway support correctly fail the mandatory next-action
   calibration instead of disappearing from the report?
8. Are all source/comparator hashes, solver tolerances, grids, tie breaks,
   resource stops, status ceilings and prohibited integrations enforceable?

Only a separate audit artifact with the exact contract and code hashes plus an
explicit root `GO` can release corpus extraction.

## Terminal pre-fit verdict

The fresh non-implementer audit of exact commit
`8d4e6e9e940563cdb8fd4341ad252fd176f67266` failed. Its verbatim payload is
`research/EVIDENCE/WAVE5C_MODEL_A_PREFIT_AUDIT.json`, SHA256
`56d32cb3d7f9f1068f9d18f5e126afb5fa8040cff6eaf8624d290e014fc49e2d`.
The audit independently verified all frozen source hashes without inspecting
structural-holdout outcomes and ran 64 tests successfully, but hostile mutations
found eight fatal design/enforcement defects:

1. the audit gate accepts an incomplete synthetic pass document;
2. transcript ordering and public/private visibility are not fail-closed;
3. censored last callbacks become false trajectory terminals;
4. the operational-v1 comparator omits the policy's boulware early freeze;
5. the inner objective weights unequal folds rather than games exactly;
6. stable nonempty unique row identity is not enforced;
7. CPU/RSS/artifact limits are detected after breach rather than preempted; and
8. immutable Jordan-reached live-branch rescoring is not implemented.

Per the Wave 5C blocked-route contract, this exact formulation is closed at
pre-fit. The owner did not repair or resubmit it, and no root `GO` was issued.
The implementation is preserved only as **candidate code rejected by independent
pre-fit audit**. It provides no evidence that a fitted Model A predicts better,
no structural validation, no untouched confirmation, and no payoff evidence.
A future reopen is a new formulation requiring new code/contract hashes and a
fresh hostile pre-fit audit.
