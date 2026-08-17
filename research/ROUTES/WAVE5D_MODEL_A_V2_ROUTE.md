# Wave 5D Route 2 — bargaining Model-A v2

Status: **terminal independent pre-fit FAIL. No extraction, fit, structural
scoring, integration, API call, or live game is authorized.**

## Materially new formulation

This is the single Wave 5D successor permitted after the Wave 5C pre-fit
failure. It has a new route identity, schema, code package, contract, audit
schema, and supervisor. It does not mutate the rejected Wave 5C files.

The eight prior fatal objections map to executable v2 controls:

1. The audit gate requires an exact top-level key set, exact locked code map,
   exact contract hash, exact ten-check all-pass map, a fresh non-implementer
   identity, an exact commit, test evidence, no objections, no structural
   outcome access, and a separate root GO token.
2. The extractor requires nonempty `public_parameters`, projects a fixed public
   field allowlist, forbids private-configuration fallback, validates transcript
   order and same-role current-round leakage, and freezes a t-1 visibility
   certificate before reading the target.
3. Right-censored games retain observed non-stop hazards but never receive a
   terminal-round or action-count endpoint. Complete-case trajectory support and
   censored/invalid counts are separately reported.
4. The operational-v1 comparator calls the pinned schema-v1 sampler and the
   pinned `BargainingPolicy` for every draw, retaining archetype, parameters,
   noise seed, round, horizon, and the boulware/late-conceding freeze.
5. Inner CV calculates one equal-channel joint score per game and pools all
   validation games across folds with equal game weight. Unequal fold means are
   never averaged.
6. Every row receives a SHA256 identity over canonical source/game/actor/public
   state/visible history/target content. Empty observational event IDs are
   allowed but irrelevant; duplicate row identities fail extraction and OOF
   reconciliation.
7. A separate process-group supervisor enforces a 7 GiB aggregate RSS ceiling,
   six total worker threads, monotonic and absolute campaign deadlines,
   aggregate artifact bytes, SIGTERM/grace/SIGKILL, one fsync-backed atomic
   certificate, and zero restarts. The campaign refuses direct unsupervised
   execution.
8. All three immutable Jordan-reached labels have implemented, exact, two-axis
   diagnostics with frozen coverage/MAE rules. They are diagnostic-only and
   cannot select the model or create live evidence.

## Pre-fit audit boundary

The auditor must work from the frozen clean commit without using released
structural outcomes. Synthetic hostile mutations must cover future transcript
items, same-actor current-round items, private configuration fallback, terminal
and payoff poison, duplicate empty event identifiers, real memory/deadline
violations, incomplete audit documents, unequal inner-fold game counts,
boulware policy parity, right censoring, and exact Jordan labels.

The machine gate is
`research/ROUTES/WAVE5D_MODEL_A_V2_PREFIT_AUDIT_SCHEMA.json`. A passing audit
only makes the package eligible for the root token `WAVE5D_MODEL_A_V2_GO`.

The fresh non-implementer audit of exact commit
`1a1e8f7977e758faf4256993d3b75397a55057de` returned FAIL. The verbatim record
is `research/EVIDENCE/WAVE5D_MODEL_A_V2_PREFIT_AUDIT.json`, SHA256
`e2e65b0e37906d72b27265a1c47aeb877d0f3b45a2c6273a3db8deaeca72dc6d`.
Its six fatal objections are the authoritative terminal explanation. The
execution description below is retained only as the never-authorized frozen
proposal; it must not be invoked. Wave 5D authorizes no repair or third
formulation.

## Frozen execution proposal — never released

The only permitted execution shape is one campaign process under the external
supervisor, with no parallel memory-heavy process:

```text
python3 -m glee_eval.diagnostics.wave5d_supervisor \
  --certificate <new-output>/supervisor_certificate.json \
  --deadline-seconds <remaining-monotonic-budget> \
  --not-after-wall-time-ns 1786967434000000000 \
  --max-rss-bytes 7516192768 \
  --max-worker-threads 6 \
  --artifact-root <new-output> \
  --max-artifact-bytes 3221225472 \
  -- python3 -m glee_eval.diagnostics.bargaining_model_a_campaign_v2 \
  --contract research/ROUTES/WAVE5D_MODEL_A_V2_PREFIT_CONTRACT.json \
  --audit <independent-audit.json> \
  --root-go WAVE5D_MODEL_A_V2_GO \
  --output-dir <new-output>
```

The remaining monotonic budget must end no later than the fixed 11:50:34Z safe
shutdown boundary. The result remains an offline research candidate. No Jordan,
factorial-agent, Model C, simulator, evaluator, promotion, or live-policy
integration is permitted.
