# Wave 5A controlled-receiver decision gate

Status: **offline infrastructure complete; receiver selection and production activation blocked
pending explicit user inputs**.

Version bound: base commit `3a04ec199a725957b06df75bc6eabd50e60a6574`.
This checkpoint made no external model calls, chose or tuned no receiver, ran no treatment or
payoff experiment, and did not change
`glee_eval.experiments.factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256` from `None`.
Every mock/certificate result from this route is labelled exactly
`infrastructure_only_non_evidence`.

## Decision

Do not name a provider/model yet. The repository establishes that a separately controlled,
pre-existing, independently selected text-responsive receiver is the least-confounded primary
follow-on, initially for persuasion candidate-seller episodes. It does **not** contain evidence
that supports any particular hosted model/version or local artifact. Selecting one now would
invent a scientific dependency.

The source-grounded route-level shortlist is therefore:

1. a pre-existing hosted receiver with an immutable provider/model/version identifier, exact
   cached replay, and a treatment-blind capability certificate; or
2. a pre-existing local receiver whose model, tokenizer, inference code, and runtime are bound by
   artifact/dependency hashes and which passes the same certificate.

The basis for these categories is the controlled-frozen-receiver route and hosted/local replay
tradeoff in `research/ROUTES/R3_LANGUAGE_DECISION.md`, especially its “Controlled frozen LLM
opponents” row, plus the binding Route-B contract. There is **no defensible named-model
shortlist** in current project evidence. The existing `glee.offline.rule_based_text_blind.v1`
receiver remains a useful negative control, but it is not eligible for a language-effect study.
The cross-fitted learned response evaluator remains predictive/model-relative, not a causal
receiver choice. Randomized live GLEE assignment remains a separately authorized ecological
study, not a controlled-receiver substitute.

## Implemented offline contract

`glee_eval/experiments/controlled_receiver.py` now provides a dependency-free, injected-transport
harness. The contract hash canonically freezes:

| Boundary | Frozen content |
| --- | --- |
| Receiver identity | Hosted provider/model/version or a local artifact SHA-256 |
| Prompt bytes | Exact base64-encoded system and user bytes |
| Input separation | Distinct economic-stance and candidate-text fields; exact visible and hidden field names; `treatment_arm` must be hidden |
| Generation | Decoding parameters and all allowed receiver seeds |
| Output | Strict JSON schema, parser identifier, decision field, allowed decisions, and refusal decisions |
| Failure | Per-kind action for timeout, refusal, malformed output, and missing output; maximum attempts; timeout |
| Missingness | Failed prespecified rows are retained and marked missing; post-treatment exclusion is prohibited |
| Replay | Exact canonical request and response envelopes, SHA-256 bindings, conflict rejection, canonical cache export/import |
| Resources | Calls, input/output tokens, micro-USD cost, runtime, and per-call reservations |
| Scope | Eligible family, candidate role, and receiver role |
| Selection | Prospectively frozen and treatment-blind; factorial payoff and treatment-template use must both be false |

The outbound receiver request contains candidate text, fixed economic stance, and only declared
visible inputs. Hidden values are committed into the audit request-envelope hash but are not
included in bytes delivered to the receiver. Responses bind exact bytes, token/cost/runtime
usage, attempt number, request hash, and instrumented consumed-field names. Cache lookup keys the
complete audit request envelope, so two hidden-arm records may share byte-identical outbound
requests without colliding.

The parser and retry policy are contract-global and receive no arm argument. Timeout, refusal,
malformed, and missing responses all end as a retained missing observation after the frozen retry
rule. A call reservation is checked before invoking an injected transport, and reported usage
must fit that reservation and the total caps. The harness ships no provider client and cannot
make an ambient call.

## Capability certificate

The generic certificate runs prespecified paired probes that are not the four factorial treatment
templates. The implementation rejects a probe whose text hash equals any of those templates.
For each generic pair it holds public state, economic stance, receiver seed, prompts, decoding
parameters, and hidden inputs fixed. It verifies:

1. the candidate-text bytes occur in the distinct outbound text field;
2. transport instrumentation records that the receiver consumed that field;
3. at least one prespecified generic text-only pair changes the parsed output;
4. hidden field names and canary values do not enter the outbound receiver object;
5. only the text field differs, while the parser/failure-policy hash is arm-invariant; and
6. the complete request/retry/response record replays byte-for-byte from exact cache without a
   second transport call.

A text-blind receiver or a receiver lacking consumed-field instrumentation fails the certificate,
even if text was delivered. A malformed or missing response never becomes an arm-specific
exclusion. Passing this certificate proves plumbing and generic text responsiveness only. It is
not evidence that the four treatment templates change behavior, payoff, or real GLEE opponents.

## Exact user inputs still required

All items below must be supplied or explicitly delegated before a real capability run. A partial
answer must not be converted into a production contract.

1. **Identity:** hosted provider, exact immutable model/version (not a moving alias), and endpoint
   terms; or local model/tokenizer/inference/runtime artifact hashes.
2. **Independent selection provenance:** who selected the receiver, when, the pre-existing source
   considered, the treatment-blind rule used, and affirmative confirmation that neither the four
   treatment templates nor `Factorial01Agent`/`Factorial11Agent` payoff informed selection.
3. **Exact prompt bytes:** system bytes and user-instruction bytes, including whitespace and text
   encoding. These must be owned/frozen independently of treatment outcomes.
4. **Input boundary:** exact public-state fields, exact economic-stance representation, exact
   candidate-text field, exact hidden fields, and confirmation that no quality/private state,
   treatment arm, template ID, e-process state, future event, or payoff is visible.
5. **Generation:** decoding parameters, seed values, whether the provider honors seeds, context
   and output-token limits, and hosted nondeterminism expectations.
6. **Output/parser:** strict JSON decision schema and allowed buyer decisions for persuasion,
   including the exact refusal representation and whether explanations are prohibited or bounded.
7. **Failure policy:** maximum attempts; timeout; which timeout/refusal/malformed/missing events
   retry; backoff behavior in the external adapter; and confirmation that final failures remain
   intent-to-treat missing rows in every arm.
8. **Cache/retention:** authorized location, encryption/access policy, retention period, whether
   prompt/response bytes may be stored, and the policy for a provider response that conflicts with
   an existing exact request.
9. **Caps and prices:** maximum calls, input/output tokens, wall time, currency/date-specific
   input/output/cache prices, a micro-USD ceiling, rate limits, and explicit spend authorization.
10. **Scope:** confirmation that Wave 5 begins with persuasion candidate-seller / receiver-buyer
    only, plus the frozen pre-treatment state/probe population and receiver seeds.
11. **Capability design:** independent owner of the generic probes, probe count, probe texts,
    untouched pass/fail rule, and a holdout rule that prevents replacing failed probes after
    inspection.
12. **Confirmatory design:** approval of the final paired sample size/power rule, whether the
    existing 6,000-call-per-family envelope remains appropriate, and the exact estimand/manifest
    authorization hash. This is separate from capability authorization.
13. **Adapter:** the reviewed Python transport callable implementing
    `ReceiverTransport(bytes, timeout_seconds) -> TransportResult` and its source/dependency hash.

## Calls, tokens, cost, and runtime

These are planning envelopes, not quotes, authorizations, or power calculations. Exact numbers
cannot be stated until prompt bytes, tokenizer, prices, rate limits, and retry policy are selected.
For arithmetic only, the table assumes 1,000–4,000 input tokens, 16–64 output tokens, 0.5–10
seconds per uncached call, illustrative rates of $0.10–$15 per million input tokens and
$0.40–$60 per million output tokens, and no cache discount. Replay makes zero external calls.

| Stage | Calls | Token envelope | Illustrative cost | Serial runtime; ideal concurrency 10 |
| --- | ---: | ---: | ---: | ---: |
| Generic capability certificate | 25–50 states × 2 texts × 3 seeds = **150–300 nominal**; **300–600 hard maximum** if every call uses one retry | **0.15–1.20M input**, **2.4–19.2k output** nominal; at most double under the retry cap | About **$0.02–$19.16 nominal**; at most about **$38.31** under the stated retry/rate extremes | **1.25–50 min serial**; roughly **0.13–5 min** ideally parallel, excluding queue/rate limits |
| Existing controlled-receiver planning pilot (not capability certification) | **1,800** calls from `R3_LANGUAGE_DECISION.md`; up to 3,600 with one retry | **1.8–7.2M input**, **28.8–115.2k output** nominal | About **$0.19–$114.91 nominal** | **15 min–5 h serial**; roughly **1.5–30 min** ideally parallel |
| Confirmatory persuasion study | **6,000 nominal** per covered family from the existing route; **12,000** with one retry | **6–24M input**, **96–384k output** nominal | About **$0.64–$383.04 nominal**; at most about **$766.08** under the retry/rate extremes | **50 min–16.7 h serial**; roughly **5 min–1.7 h** ideally parallel |

The 1,800 and 6,000 counts are inherited planning values, not newly selected sample sizes. A
capability pilot should freeze a strict call cap independently. Confirmation still requires a
prospective power calculation and the exact 3,600-scenario manifest; calls and scenarios are not
interchangeable units.

## Determinism and replay tradeoff

Hosted inference can change behind a model alias and may not be byte-deterministic at temperature
zero or with a nominal seed. For a hosted receiver, scientific replay therefore means replaying
the exact cached response envelope. A cache miss is a new call, not a reconstruction. The
provider/model/version, endpoint behavior, timestamps, usage, prompt bytes, response bytes, and
all hashes must remain in provenance. Cache loss would obstruct exact reproduction.

A local receiver can offer stronger execution determinism, but only if model and tokenizer bytes,
inference library/accelerator versions, decoding implementation, quantization, seeds, and relevant
deterministic-kernel settings are all frozen. An artifact hash alone does not freeze the execution
stack. Local hardware/runtime can also be costly even when marginal API cost is zero.

## Circularity controls

The central risk is manufacturing a responsive receiver around the candidate templates. Receiver
selection, prompt construction, capability probes, and pass/fail thresholds must be fixed by an
independent owner before template or factorial outcomes are inspected. Capability probes must be
generic and distinct from treatment wording. Passing receivers may not be ranked by strength of
response to the treatment, treatment payoff, or combined-arm payoff. A failed named receiver may
be reported as a failed capability route, but replacing it requires a newly authorized,
prospectively documented selection—not silent tuning. Capability data and confirmatory payoff
data must use separate purposes and ledgers.

## Future authorized command

First rerun the offline infrastructure check:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest -v tests.test_controlled_receiver
```

After all thirteen inputs above are frozen, the reviewed adapter and two canonical JSON inputs
exist, and external calls/spend are explicitly authorized, run exactly this interface with the
approved paths and reservation amounts substituted from that contract:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m glee_eval.experiments.controlled_receiver certify \
  --contract research/CONTRACTS/CONTROLLED_RECEIVER_V1.json \
  --probes research/CONTRACTS/CONTROLLED_RECEIVER_CAPABILITY_PROBES_V1.json \
  --transport approved_receiver_adapter:transport \
  --cache-out research/EVIDENCE/CONTROLLED_RECEIVER_CAPABILITY_CACHE_V1.json \
  --certificate-out research/EVIDENCE/CONTROLLED_RECEIVER_CAPABILITY_CERTIFICATE_V1.json \
  --reserved-input-tokens 4000 \
  --reserved-output-tokens 64 \
  --reserved-cost-microusd 100000
```

Those file names, adapter, and reservation values are an interface specification, not existing
or approved artifacts. The command must not be run until they are user-approved and hash-frozen.
Even a passing result remains `infrastructure_only_non_evidence`; production activation requires
a separate exact pre-outcome contract, independent audit, and explicit non-`None` authorization
pin.

## Current verification

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest -v tests.test_controlled_receiver
```

Current result: **11/11 tests passed**. Evidence class: unit/synthetic infrastructure only. The
suite covers canonical contract hashing and immutability; incomplete identity and circular
selection rejection; hidden-input separation; retry/parser/missingness rules; identical handling
under hidden arm changes; resource-cap preflight; response-hash tamper rejection; cache
export/import and exact replay; a passing text-sensitive synthetic receiver; and failing
text-blind/uninstrumented synthetic negative controls. It also exercises the future CLI end to end
through an explicitly injected synthetic adapter and verifies labelled cache/certificate outputs.
No mock result is outcome evidence.
