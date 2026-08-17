# Wave 5C Route A ledger

Status: **pre-fit package under construction; no corpus extraction, fit or
structural-holdout scoring has occurred.**

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

