# Wave 5C controlled-receiver decision packet

Status: **concrete proposal, offline dry-run verified, not user-authorized, not
capability-verified, and not eligible for production.** No external receiver call, payoff row, or
live/rated game was run. Both production authorization pins remain `None`.

## Recommendation

Use hosted **OpenAI `gpt-4.1-2025-04-14`** as the proposed primary receiver and hosted
**OpenAI `gpt-4.1-mini-2025-04-14`** as the one prespecified fallback. The fallback is not
automatic: if the primary is unavailable or fails the frozen capability gate, that route closes
and the fallback requires a new explicit authorization before its capability results are seen.

This is an engineering recommendation made before receiver or factorial outcomes, not project
evidence that either model is responsive or scientifically valid. OpenAI's current model pages
list both immutable snapshots as supporting the Responses API and Structured Outputs. The pages
list standard uncached token prices of $2/$8 per million input/output tokens for the primary and
$0.40/$1.60 for the fallback. Snapshot names reduce alias drift; they do not establish account
availability, seed support, byte determinism, internal field consumption, or stable endpoint
behavior. Those remain capability-stage checks. Sources checked 2026-08-16:
[GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1) and
[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

Select **Design A**: 300 base economic strata × two candidate roles × two receiver replicates per
family. A hosted receiver is not expected to be byte-deterministic even with temperature zero,
so two replicates measure receiver/environment variance. Design B would waste less sample on
replication only for a byte-deterministic local receiver; Design C's three replicates are not
justified without evidence of unusually high variance.

The complete 13-field proposal has SHA-256
`fd5724eeac0da19f27bd19d9b0023eb2543bd427cbbcc84f543c86742202a7d0`; the embedded primary
canonical receiver contract has SHA-256
`a752680abc2ed248bc5d6c31e78dbf124160d3e66760a0cd73dae473b7a81fcd` before the final
proposal-only metadata wrapper. The complete 13-field proposal and offline evidence are in
`research/EVIDENCE/WAVE5C_RECEIVER_DECISION.json`; their validator is
`glee_eval/experiments/wave5c_receiver.py`. Any change below creates a new hash and requires a new
prospective decision.

## Exact 13-field proposal

1. **Identity.** Primary: provider `openai`, model `gpt-4.1`, immutable version
   `gpt-4.1-2025-04-14`, Responses API. Fallback: `openai`, `gpt-4.1-mini`, immutable version
   `gpt-4.1-mini-2025-04-14`, Responses API. Neither is authorized or capability-verified.
2. **Independent-selection provenance.** Proposed owner is the user/principal investigator. The
   owner must record name and UTC authorization time and affirm that selection used no generic
   capability strength, treatment templates, Factorial01/11 action, or factorial payoff.
3. **Prompt bytes.** UTF-8 system prompt SHA-256
   `b8ba8c6deb5e5c1fdf5688ba6b2c850b259ccfe925f9f4b568e362416a77b724` and user prompt SHA-256
   `234fcc2724aa12062753c880e1a35c2a212ed3a856878ae20b949269eb082857`. Exact base64 bytes are
   frozen in the JSON evidence; whitespace changes invalidate the contract.
4. **Input boundary.** Separate `candidate_text` and `economic_stance` objects. Visible fields are
   exactly round, total rounds, product price, public high-quality prior, public buyer values,
   seller message type, myopia flag, prior public recommendations, and prior public buyer
   decisions. Hidden fields are exactly treatment arm, scenario ID, private quality, template
   ID, e-process state, future events, terminal outcome, and both payoffs. Hidden values enter only
   a request-envelope commitment hash and never outbound bytes.
5. **Generation.** Temperature `0`, top-p `1`, maximum 16 output tokens, strict JSON-schema
   response, receiver replicate tags/seeds `530011` and `530017`. Provider seed/schema support
   must be demonstrated; it is not assumed. Expected byte determinism is `false`.
6. **Output and parser.** Parser `strict_json_decision_v1`. The entire response must be one JSON
   object, no extra keys, with exactly one `decision` in `buy`, `pass`, or `refuse`. `buy` and
   `pass` are observations; `refuse` is a retained missing observation.
7. **Timeout/retry/refusal/malformed rules.** Thirty-second timeout; maximum two attempts. Timeout
   and malformed JSON receive one immediate, no-jitter retry. Refusal and empty/missing output do
   not retry. An exhausted attempt remains an assigned, labelled missing row; no arm-specific
   fallback or parser is allowed.
8. **Cache, replay, retention, and invalidation.** Exact request/response envelopes are keyed by
   contract hash and request hash. A cache hit makes zero external calls; a conflicting record
   aborts rather than overwriting. Proposed storage is encrypted
   `research/private_cache/wave5c_receiver`, restricted to the principal investigator and named
   runner, retained 180 days. Any identity, prompt, input, decoding, parser, failure, adapter,
   dependency, or execution-stack change creates a new contract/cache namespace.
9. **Resource caps.** Per attempt: 2,048 input tokens, 16 output tokens, $0.01, 30 seconds. Whole
   capability plus confirmatory envelope: 96,200 attempts, 197,017,600 input tokens, 1,539,200
   output tokens, $1,000 hard spend ceiling, 12 wall-hours, and concurrency 32. Under prices
   checked above, fully reserved primary cost is $203.1744 nominal and $406.3488 at the retry cap;
   fallback retry-cap cost is $81.26976. Reverify price and account limits at authorization.
10. **Scope.** Controlled receiver is eligible only when the candidate is persuasion seller and
    the receiver is persuasion buyer in a text configuration. Bargaining, negotiation, and
    persuasion-candidate-buyer remain frozen language negative controls with no external
    receiver. Numeric recommendation is fixed before text reaches the receiver.
11. **Treatment-blind capability probes.** Twenty-five generic public states × two generic
    text-only alternatives × two receiver replicates = 100 nominal requests and 200 maximum
    attempts. All delivery, adapter-serialization, hidden-input, parser-invariance, and replay
    checks must pass, and at least 5/25 states must change parsed decision in each replicate.
    Failed probes are not replaced. A fresh owner must audit that the generic probe set was not
    selected from treatment outcomes. Adapter `consumed_fields` proves serialization into the
    provider request, not internal attention; behavioral text-only divergence is separately
    required.
12. **Confirmatory design.** Design A; 3,600 paired scenario rows, exact four frozen agents,
    current theory+Model-C core, Wave-4 estimands, intent-to-treat missingness. No production pin
    is set. Capability passage does not authorize the payoff study.
13. **Adapter and credentials.** Provider-neutral interface is
    `ReceiverTransport(bytes, timeout_seconds) -> TransportResult`. The repository contains only
    an ineligible deterministic dry-run transport. The user must provide `OPENAI_API_KEY` through
    the runner environment and a reviewed provider-adapter source/dependency hash. No credential
    value may enter a manifest, hash, cache, log, or evidence file.

## What “3,600 rows” means

`3,600` means **paired experimental scenario units**, not calls and not arm executions:

- Design A creates 1,200 rows per family: 300 base strata × two roles × two receiver replicates.
- All four frozen arms reuse each row, so the payoff study has **14,400 agent episode
  executions**.
- Only persuasion candidate-seller is receiver-eligible: 300 strata × two receiver replicates =
  600 rows.
- Every eligible persuasion episode has 20 buyer decisions and all four arms require the same
  controlled environment: `600 × 4 × 20 = 48,000` nominal receiver requests.
- No retry is planned. One conditional retry is reserved for each request, giving 48,000
  additional attempts and a **96,000-attempt confirmatory ceiling**.
- Capability certification adds 100 nominal requests and 100 possible retry attempts. The whole
  route is therefore **48,100 nominal requests and 96,200 maximum attempts**. Exact cache hits may
  reduce external calls but are not assumed in the cap.

The earlier 6,000-call-per-family planning number did not account for the exact 3,600-row
four-arm execution. It is superseded by this derivation, not silently reused.

## Offline verification and evidence maturity

The provider-neutral dry run crossed the complete 50-probe set (two texts each) through an
injected deterministic local test double. It verified deterministic proposal/contract hashing,
strict input separation, different hidden-arm commitment hashes with byte-identical outbound
requests, absence of every hidden key and canary value, hash-consistent forgery rejection, exact
cache replay without another transport call, parser/failure invariance, and the stricter
replicate-specific capability rule. This is labelled `infrastructure_only_non_evidence`. It says
nothing about the two proposed hosted receivers or treatment payoff.

## Decisions and credentials still required

The user must decide or supply all of the following; none is inferred:

1. accept the primary or explicitly reject it and select the fallback;
2. independent selector name, UTC time, and treatment-blind affirmation;
3. credential availability through `OPENAI_API_KEY` without exposing its value;
4. endpoint access plus verified snapshot, Structured Outputs, seed/replicate, usage, and error
   semantics;
5. reviewed external adapter and dependency hashes;
6. encrypted cache location, access list, and 180-day retention;
7. current-price recheck and a separate capability-only spend authorization (planning hard cap
   $0.8448 at the reserved primary token envelope; a smaller operational ceiling may be chosen);
8. later, and only after a passing untouched capability certificate and fresh hostile audit,
   whether to authorize and pin the 3,600-row payoff study.

If the hosted endpoint cannot support the strict schema/replicate contract, or if the adapter
cannot honestly record candidate-text serialization, reject the proposal. Do not weaken the
certificate or silently switch to the fallback.

Decision response template:

> I prospectively select `openai/gpt-4.1-2025-04-14` as the primary receiver (fallback
> `openai/gpt-4.1-mini-2025-04-14`, not automatic), affirm selection was treatment- and
> payoff-blind, name `[selector]` as owner at `[UTC time]`, approve Design A and the proposed
> encrypted 180-day cache policy, and will provide credentials plus a reviewed adapter separately;
> this decision authorizes no external call or payoff study.

To reject in one response:

> I reject the Wave 5C primary and fallback receiver proposal; keep both production pins unset
> and make no external call.
