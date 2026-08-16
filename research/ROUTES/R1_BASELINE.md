# R1 baseline — wave-1 bounded kill-check

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
