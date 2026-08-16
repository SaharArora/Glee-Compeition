# R1 baseline

## Wave 2 isolated implementation

Outcome: **concrete treatment-off core and parity tests** against source commit
`895ffee341cd4893373e32d5f8c1a5375549e0e6`.

`research/CANDIDATES/r1_treatment_off_baseline.py` defines one
`TreatmentOffEconomicCore` and four thin slot wrappers.  Every wrapper defaults
to `use_eprocess=False` and `use_language=False`; the treatment-capable wrapper
surfaces expose only their own orthogonal flag.  With no treatment installed,
toggling a flag cannot change the other treatment surface.

The core inherits the shipped family mechanics but fixes control to neutral
`SAFE` / `treatment_off_economic_core`.  The old `E_*` multipliers are absent
and are scrubbed from action metadata, so neither their magnitudes nor the old
threshold attributes can alter an action byte.  Bargaining retains the theory
SPE anchor, negotiation retains surplus/screening and now places its own neutral
next offer in every rejection before support review, and persuasion retains its
Bayesian policy without creating or storing a shadow language candidate.

Ambient `GLEE_RESPONSE_MODEL` and `GLEE_SUPPORT_INDEX` are ignored.  An external
response residual or support index is loaded only with an explicit matching
SHA256; the response artifact also passes the small runtime schema/finite-range
verifier before it can influence a decision.

Bounded tests cover:

- all ten family/role/action-kind cells: bargaining two roles by offer/decision,
  negotiation two roles by offer/decision, and persuasion seller/buyer actions;
- canonical action and metadata equality across all four treatment-off wrappers;
- a hostile `1e300` `E_*` injection and permissive legacy thresholds, with exact
  action-byte equality to the neutral core;
- language-flag numeric/decision isolation and e-process-flag message isolation;
- matching-hash residual use plus missing/wrong-hash rejection;
- the dynamic offline loader; and
- all seven documented production phases plus a forced rejection, whose live
  payloads equal translation of the core's action with zero `LiveStrategy`
  fallbacks.  The rejection proves its counter price came from `AgentAction`.

Exact focused command and result:

```bash
env -u GLEE_RESPONSE_MODEL -u GLEE_SUPPORT_INDEX \
  python -m unittest tests.test_r1_treatment_off_baseline -v
```

Result: `Ran 8 tests in 0.017s — OK`.

Implementation SHA256:
`95bf90cfb63bde3b78aa9bdd5140de902016bd6413b25b910d8bebf80f885fef`.
Test SHA256:
`0df7e2cb5bd4e10edc16f57770df448231a749a0014263e1ef1c6852daf28795`.

This is interface/parity evidence only.  It did not inspect a holdout, evaluate
payoff, fit an artifact, run live, or change any shared research ledger.

## Wave 1 bounded kill-check

Outcome: **verified counterexample** at commit
`bce578597dbfacf2ebca38399edb41a5dde2f936`.

## Exact mapping checked

The four factorial slots `00`, `10`, `01`, and `11` were mapped to four fresh
`my_agents.jordan_strategic:MyAgent` instances, all at seed `20260829`.  This is
the smallest available treatment-off mapping because the repository has no
separate factorial wrapper implementation.

The comparator is the same `MyAgent` theory and empirical-response residual
path, with only `_control` fixed to `SAFE` so the heuristic `E_*` values cannot
select `EXPLORE`, `EXPLOIT`, or `COMMIT`.  The check supplies the same finite,
supported empirical-response fixture to all five instances and verifies that
both sides serialize `empirical_response_model` in the action.

## Decisive fixture and result

One bargaining opening-offer state is sufficient.  It has a 100-unit pot,
complete information, `delta_1=0.99`, `delta_2=0.80`, six rounds, no transcript,
and role `player_1`.  Its canonical SHA256 is
`db3fd0de3d9a2411fd3765e8831c76d0cfaf0a93ccf7a3179832be159bbc4f0c`.

The four current mappings are mutually action-byte-identical and have identical
post-decision instance-state bytes.  They are not identical to the intended
treatment-off economic core:

| Check | Current four-way mapping | Treatment-off core |
| --- | ---: | ---: |
| Strategic mode | `EXPLORE` | `SAFE` |
| Numeric offer | `62.0` | `56.0` |
| Action SHA256 | `63dc43c8415613b6c78c9e1819f11a439b12867c625936f8da56c629e0258980` | `9a5f1d5ebc2deccc6669aed88dcfee08b47eff048902f099ecc2b28d02c0e2c4` |
| Empirical residual selected | yes | yes |

The input `GameState` bytes are unchanged.  Therefore pairing, seed equality,
and mutual four-wrapper equality do not cure the R1 defect: the mapped wrapper
still contains the heuristic `E_*` mode gate forbidden when the treatment is
off, and that gate changes the economic action on the first adversarial state.

## Exact command

```bash
env -u GLEE_RESPONSE_MODEL -u GLEE_SUPPORT_INDEX \
  python -m research.CANDIDATES.r1_baseline_kill_check
```

The job is bounded at one state and five agent decisions.  It performs no fit,
holdout access, live action, registry mutation, or external write.

## Decisive next test

First isolate a hash-locked baseline class that fixes `_control` independently
of all `E_*` values and keeps the shipped theory anchor plus the selected,
verifier-backed empirical-response artifact.  Then rerun this exact fixture
across four named wrappers and require equality of canonical action bytes,
post-decision instance-state bytes, and unchanged input-state bytes.  Only after
that passes should the adversarial fixture set expand to every family/role/action
kind and production/offline adapter parity.
