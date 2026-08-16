# R4 factorial evaluator — hostile verification

Verdict: **BLOCKED for an active-treatment factorial run; PASS only as an inert-parity
canary and paired scenario constructor.**

Version bound:

- repository commit: `895ffee341cd4893373e32d5f8c1a5375549e0e6`
- `glee_eval/experiments/factorial.py` SHA-256:
  `bda3da00922ffcb9e931a95febfa885673a0f778b67d04771243398127011f14`
- `tests/test_factorial_evaluator.py` SHA-256:
  `536d2ce44e06e1063b5499a8ee0f8de3798559cd3876b71474fb66bc5130ff45`
- research question SHA-256:
  `cbe48c76aaec6e00c05d0a80fe3f6d3193aeffbd2ac7c9f24f3fe3de41293ff2`
- audit checklist SHA-256:
  `57212a4be5f034f72278d45852abbb19922c9dd988aa97e60a73e29a9d293a54`

No payoff study, fit, or live game was run.

## What survives

Within each row, one deep-copied `Scenario` fixes family, configuration, public/private
inputs as represented by the scenario, candidate/opponent roles, opponent specification,
environment seed, source, metadata, horizon-bearing configuration, and runner/scoring
labels. Support and eligibility functions are evaluated once on pre-arm copies, then their
values/hashes are reused. The four episodes receive separate deep copies, and post-run
scenario mutation is rejected.

Named seeds are deterministic functions of master seed, scenario ID, and stream name.
The evaluator iterates the fixed `FACTORIAL_ARMS` tuple rather than mapping insertion order,
so reversing the factory mapping does not change results. The runner receives the identical
scenario seed and opponent seed in every arm; fresh fixture agents initialized from the
economic seed make inert arms transcript- and payoff-identical. With
`require_inert_parity=True`, the unlabeled record includes scenario, candidate ID, opponent,
transcript, decisions, terminal result, both payoffs, metrics, and failures, so an inert
change to these surfaces is rejected. The stock label-stripping, arm-order, inert-language,
and paired-manifest fixtures pass.

## Decisive blocker: contaminated candidate RNG is accepted in study mode

The stream hashes at `factorial.py:157-158` hash only the declared stream name and seed.
They do not observe which RNG object a treatment actually consumes. The only behavioral
check is `require_inert_parity` at lines 309-313. A real active-treatment experiment must
disable that equality check because treatment is intended to change actions. Therefore the
evaluator cannot distinguish an intended treatment effect from language/evidence code that
accidentally consumes the economic-policy RNG.

The repository's contamination test does not establish the claimed general rejection. Its
helper defaults to `require_inert_parity=True`; the exception at test lines 238-240 is caused
solely by changed episode output. Running the exact same contaminated fixture with
`require_inert_parity=False` is accepted and yields four rows with nonzero effects. The first
affected row reports a spurious language main effect of approximately `-0.05`.

Independent command:

```sh
python3 -c "from tests.test_factorial_evaluator import _run,_factories; rows=_run(_factories(extra_language_draws=1,contaminated=True),require_inert_parity=False); bad=[(r.key,r.contrasts()) for r in rows if r.contrasts()['language_main_effect']!=0 or r.contrasts()['interaction']!=0]; print({'contaminated_run_accepted':True,'rows':len(rows),'nonzero_rows':len(bad),'first':bad[:1]})"
```

Observed:

```text
{'contaminated_run_accepted': True, 'rows': 12, 'nonzero_rows': 4,
 'first': [('bargaining:factorial-bargaining-6436233316273085009-player_1:player_1',
 {'eprocess_main_effect': 0.0, 'language_main_effect': -0.04999999999999993,
 'interaction': 0.0})]}
```

This violates the Wave-1 named-substream requirement and blocks scoring.

## Other limits and overclaims

- A fresh factory call does not prove a fresh independent agent: a factory may return a
  shared object, use module-global RNG/state, ignore the context seeds, or branch directly
  on `context.arm`. None is rejected in active mode. Thus “freshly instantiated” and “four
  arms differ only on treatment surfaces” are caller obligations, not evaluator guarantees.
- Environment/opponent/economic stream equality proves equal seed declarations, not equal
  draw order or realized RNG traces. Nature/opponent isolation follows the current runner's
  local seeded implementation, but the certificate does not hash that code or record draws.
- Treatment labels are removed from the `ArmResult` wrapper, but `candidate_agent_id`, action
  payloads, and decision records remain. That is appropriate for detecting inert differences,
  but it is not a general proof that treatment labels cannot leak into policy behavior.
- The integrity certificate rechecks hashes already copied into each `ArmResult`; it does not
  independently reconstruct scenarios, support, eligibility, RNG traces, termination, or
  scoring from the episodes.
- The module calculates row-level contrasts only. It does not implement or verify the frozen
  equal-family-weighted estimand, language-eligible estimand, mandatory family cells,
  uncertainty, Holm correction, nonreportable-cell handling, or the exact 3,600-row manifest.
  No claim that full R4 reporting requirements are met is supportable from these files.
- Duplicate scenario IDs are not rejected. Because named candidate seeds depend on scenario
  ID, a malformed factory could reuse non-treatment RNG streams across nominal rows.

## Commands

Stock suite:

```sh
python3 -m unittest tests.test_factorial_evaluator -v
```

Result: `Ran 7 tests ... OK`.

The independent active-mode contamination command above is the counterexample and makes the
overall R4 verdict blocking despite the green suite.

## Required decisive repair

Before any active-arm score, the evaluator needs enforceable stream provenance: treatment
wrappers must receive capability-separated RNG objects (or audited deterministic draws), the
economic stream state/trace must be identical across arms except where the economic core is
legitimately responding to treatment-mediated observations, and direct access to another
treatment's stream/global randomness must fail closed. Add an active-mode adversarial test in
which treatment output may differ but consuming one economic draw from language/evidence is
still rejected. Separately, a report validator must reproduce the frozen estimands and Holm
decision from paired rows and reject duplicate scenarios, missing cells, and contamination.

