# R4 Wave 3 — fresh hostile verification

Verdict: **PASS for the repaired named-stream/capability and active-canary contract;
BLOCKED for the final payoff study and therefore not yet promoted to independently
verifier-backed R4 infrastructure.**

Version bound:

- base commit: `fd05023de6ef87bb9d9e8f0f20044052569041b6`;
- `glee_eval/experiments/factorial.py` SHA256
  `1ca9d360073cb59fa7df972ae140796f1585cae6d27ec7d5229ba9670be4bbb3`;
- `tests/test_factorial_evaluator.py` SHA256
  `85055f533b0ad9079cc0bb10162e0d5b233d0ed5191555ab39d3662a3b7067b5`;
- four-agent implementation SHA256
  `b0c3f286e6e9ef5a28c209cd11b11d0dd0092105fd52d49ed96554a45b84c319`;
- four-agent tests SHA256
  `141cf032488ef8ee43a9b4c3eee153decddd36e86e6d08395edefc3e6622a72a`;
- frozen research question SHA256
  `cbe48c76aaec6e00c05d0a80fe3f6d3193aeffbd2ac7c9f24f3fe3de41293ff2`;
- runner SHA256
  `0142f3354759bad9038c1e93b331ccca762cf8ee4b09653f0b4a0903b380566b`.

This was a code/fixture audit only. No holdout, payoff study, fit, text-responsive
environment, or live/rated game was run.

## What the repaired version establishes

The scenario/config draw uses its own seed. After the scenario identity and configuration
are fixed, separate named derivations replace the scenario's nature seed and opponent-policy
seed. Candidate factories do not receive either seed. Economic, e-process, and language
candidate RNGs are separate `RandomStreamCapability` objects with owner, draw count, and
trace hash.

An agent must claim exactly the capabilities implied by its forced arm and must return the
identical issued objects from `factorial_capability_bindings()`. Missing bindings, a shared
agent instance, disabled-treatment claims, a wrong stream binding, duplicate scenarios, or
arm-dependent paired manifests fail before a result is returned.

The Wave 2 counterexample is repaired in the active canary: a language implementation that
spoofs the economic owner and consumes an economic draw is rejected through the paired
economic trace/non-language projection even with inert equality disabled. An independently
wrong language-to-economic binding is rejected in ordinary active mode before the episode.

The exact repaired suites establish:

- four no-op wrappers have byte-identical unlabeled actions/outcomes;
- 101 extra language draws do not change economic, nature, opponent, termination, or payoff;
- 73 extra e-process draws do not change environment/opponent or an inert economic path;
- inert active language has exactly zero paired effect;
- scenario/config/role/support/eligibility and all nontreatment stream hashes match;
- factory mapping order cannot change output;
- treatment labels are removed from the inert parity record;
- the active contaminated-economic-draw fixture is rejected;
- a forged capability binding is rejected without parity mode;
- a shared instance and duplicate scenario ID are rejected; and
- the four real entrypoints bind only their forced capabilities and pass the active isolation
  canary on the bounded text-persuasion fixture.

Commands and observed results:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests \
  -p 'test_factorial_evaluator.py' -v
# 11 tests, PASS

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests \
  -p 'test_wave3_factorial_agents.py' -v
# 12 tests, PASS
```

## Hostile limits that remain

1. Python cannot sandbox an arbitrary factory from module-global randomness or force a
   malicious object to report its behavior honestly. The certificate is therefore bound to
   the exact four audited entrypoints. Those entrypoints centrally bind the issued economic
   capability and pass only the e-process capability to `EProcessController` and only the
   language capability to `FrozenPersuasionLanguagePolicy`; their source imports no ambient
   `random` API.
2. `require_active_isolation_canary` is deliberately an inert active-treatment check. It
   strips the declared treatment log/rendering but requires the remaining path to match. It
   must not be used to erase or reject a genuine treatment-mediated opponent response or the
   preregistered e-process economic override in a future outcome study.
3. The evaluator still does not implement the frozen 3,600-row equal-family-weighted report,
   language-eligible nonreportability rule, uncertainty, or Holm reconstruction. Duplicate
   rows are now blocked, but the final report validator remains an exact prerequisite.
4. This hostile pass was executed by the implementation owner in the current task, not a
   separately delegated verifier. Evidence maturity is therefore self-audited, not the
   requested independent verifier-backed level.

## Exact remaining obstruction

The named-stream repair itself passes its hostile canaries. R4 as a whole remains blocked
until a fresh independent verifier checks this exact version and a report validator
reconstructs the frozen estimands/Holm decision from paired rows. No treatment payoff is
eligible before both conditions are met.
