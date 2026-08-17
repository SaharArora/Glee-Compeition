# Wave 5E frozen GPT-4.1 receiver capability route

Status: **implemented offline; protected key absent; independent audit required; no API call.**

The adapter uses only the Python 3.10.13 standard library. It targets exactly
`https://api.openai.com/v1/responses` with model snapshot `gpt-4.1-2025-04-14`, strict JSON Schema
output, the Wave 5C prompt/input/parser/retry contract, `store=false`, and no model/provider
fallback. Official OpenAI documentation lists that snapshot, the Responses endpoint, Structured
Outputs support, and prices of `$2/M` input tokens and `$8/M` output tokens:
<https://developers.openai.com/api/docs/models/gpt-4.1>.

## Security and leakage boundary

- The key is accepted only from a regular file outside the repository with no group/other mode
  bits. It is held in memory and is never printed, serialized, hashed, cached, or included in a
  certificate.
- Requests bypass proxy environment variables, reject redirects, use the platform TLS trust
  store, send no hidden treatment/outcome field, and set `store=false`.
- Provider response bodies and HTTP reason text are never exposed in exceptions. Only the strict
  decision JSON and exact token/cost accounting enter the in-memory receiver harness.
- Capability output contains request/response hashes, decisions, checks, and aggregate accounting;
  it does not persist the raw provider response or API key.
- The output directory must not already exist and must be outside Git. The certificate is written
  atomically with mode `0600` inside a mode-`0700` directory.

## Route cap

The probe set contains 25 public states × two receiver seeds × two generic texts = exactly 100
nominal requests. The receiver contract permits at most two attempts per request, hence 200
attempts maximum. Each attempt pre-reserves at most 2,048 input tokens and 16 output tokens at the
frozen prices: `2048×2 + 16×8 = 4,224 microusd`. The maximum pre-reservation is therefore 844,800
microusd, below the hard route ceiling of 1,000,000 microusd (`$1.00`). The adapter rejects a
complete canonical provider payload longer than 2,048 ASCII bytes, a conservative upper bound on
its request-token count. No automatic fallback exists.

Capability PASS requires all frozen Wave 5C delivery, serialized-field, hidden-input,
parser/failure-arm-invariance, and exact-cache replay checks, plus text-only decision changes in at
least 5 of 25 states for each receiver seed. A PASS is infrastructure capability evidence only:
it does not authorize factorial outcomes or set either production pin.

## Independent audit gate

The runner refuses to load a key or call the endpoint unless a separate audit document:

- has schema `glee.research.wave5e.receiver_adapter_audit_go.v1` and verdict `GO`;
- names an independent auditor;
- binds the current exact Git commit;
- exactly matches the SHA-256 map of the adapter, harness, ITT, capability runner, frozen Wave 5C
  receiver builder, and dependency lock;
- records `automatic_fallback=false` and `api_call_performed_by_audit=false`.

The audit document should be stored outside this branch/repository. Its source hashes can be
reconstructed offline with `wave5e_capability.source_hashes(repository_root)`.

## Attended invocation after audit GO and secret setup

Create a secret file outside the repository without putting its value in shell history or chat:

```bash
install -d -m 700 /absolute/path/outside/git/wave5e-secrets
umask 077
read -s OPENAI_KEY_INPUT
printf '%s\n' "$OPENAI_KEY_INPUT" > /absolute/path/outside/git/wave5e-secrets/openai_api_key
unset OPENAI_KEY_INPUT
chmod 600 /absolute/path/outside/git/wave5e-secrets/openai_api_key
```

Then run exactly one fresh capability route while attended:

```bash
python -m glee_eval.experiments.wave5e_capability capability \
  --repository-root /absolute/path/to/audited/Glee-Wave5E-P \
  --api-key-file /absolute/path/outside/git/wave5e-secrets/openai_api_key \
  --audit-go /absolute/path/outside/git/wave5e-audit/adapter_audit_go.json \
  --output-dir /absolute/fresh/path/outside/git/wave5e-capability
```

Do not set `OPENAI_API_KEY` in repository files. Do not rerun a FAIL automatically. The only
expected durable output is `capability_certificate.json`, with `PASS` or `FAIL` and exact stop/
accounting evidence. A new run after any adapter, prompt, contract, dependency, pricing, model, or
audit change requires a new commit, new independent audit, and new authorization.

## Current blocker

The protected key file and independent audit-GO document are absent. Therefore no capability
request has been made and the receiver status remains **NOT RUN / UNKNOWN**.
