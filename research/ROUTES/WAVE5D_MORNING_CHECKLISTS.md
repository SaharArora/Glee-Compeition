# Wave 5D morning operational checklists

These commands are **not authorized by Wave 5D** and were not run. They are for a future attended
session after the user supplies the corresponding explicit authorization. Neither command prints,
hashes, fingerprints or commits a credential. Replace only the named non-secret paths; never paste
a secret into the command line, chat, Git, or an evidence file.

## GLEE — one attended command after exact canary authorization

Prerequisites: a clean detached checkout of the final audited Route-L head
`f2a1bb5afe6f83c3a8a03201a0e5939f748ecda9`; Python with `glee-sdk==0.0.5`; a fresh output path;
the launcher's frozen Jordan policy commit
`bce578597dbfacf2ebca38399edb41a5dde2f936`; and the exact separate authorization sentence
preserved outside the execution log. The launcher's
first network operation is a fresh `/stats` read. It validates UUID
`99357c15-48d5-4177-9d6a-48d02b95a164`, name `gangsteryoshi`, numeric `active_games`, and requires
`active_games==0` before the first queue request. Any mismatch produces zero new queues.

Set the four path variables below to non-secret absolute paths, then run this single attended
shell command. The example evidence directory is outside every Git worktree. The command securely
prompts for `GLEE_API_KEY`, creates an independent 32-byte HMAC secret under mode `0600`, unsets
all four optional artifact variables, runs the exact 100-per-family frozen canary, and always
attempts reconciliation and hostile audit after launch returns.

```bash
GLEE_TELEMETRY_REPO=/absolute/path/to/clean-detached-wave5c-route-l GLEE_FROZEN_PYTHON=/absolute/path/to/frozen-venv/bin/python GLEE_CANARY_OUTPUT=/absolute/path/outside-git/jordan_canary_wave5c_001 GLEE_SECRET_DIR=/absolute/path/outside-git/wave5d-secrets /usr/bin/env zsh -f -c 'set -euo pipefail; umask 077; test "$(git -C "$GLEE_TELEMETRY_REPO" rev-parse HEAD)" = f2a1bb5afe6f83c3a8a03201a0e5939f748ecda9; test -z "$(git -C "$GLEE_TELEMETRY_REPO" status --porcelain)"; test ! -e "$GLEE_CANARY_OUTPUT"; "$GLEE_FROZEN_PYTHON" -c '\''import importlib.metadata as m; assert m.version("glee-sdk") == "0.0.5"'\''; install -d -m 700 "$GLEE_SECRET_DIR"; test ! -e "$GLEE_SECRET_DIR/glee_telemetry_hmac"; IFS= read -r -s "GLEE_API_KEY?GLEE API key (hidden): "; print; export GLEE_API_KEY; (umask 077; openssl rand -hex 32 > "$GLEE_SECRET_DIR/glee_telemetry_hmac"); chmod 600 "$GLEE_SECRET_DIR/glee_telemetry_hmac"; export GLEE_TELEMETRY_HMAC_KEY="$(<"$GLEE_SECRET_DIR/glee_telemetry_hmac")"; unset GLEE_OPPONENT_POPULATION GLEE_CONFIG_CATALOGUE GLEE_RESPONSE_MODEL GLEE_SUPPORT_INDEX; set +e; "$GLEE_FROZEN_PYTHON" -m glee_eval.live_telemetry launch --repo "$GLEE_TELEMETRY_REPO" --output-dir "$GLEE_CANARY_OUTPUT" --per-family-games 100 --concurrency 3 --poll-interval 2; launch_status=$?; "$GLEE_FROZEN_PYTHON" -m glee_eval.live_telemetry reconcile --output-dir "$GLEE_CANARY_OUTPUT"; reconcile_status=$?; "$GLEE_FROZEN_PYTHON" -m glee_eval.telemetry_audit --output-dir "$GLEE_CANARY_OUTPUT" --expected-per-family 100; audit_status=$?; unset GLEE_API_KEY GLEE_TELEMETRY_HMAC_KEY; exit $((launch_status != 0 || reconcile_status != 0 || audit_status != 0))'
```

Do not install anything inside this command. If the SDK/version, commit, cleanliness, output,
identity or active-game preflight fails, stop and reconcile the evidence; do not repair and rerun
under the same authorization. If terminal official per-game rating is unavailable, the launcher
drains the first one-per-family wave and stops by contract.

## OpenAI controlled receiver — currently blocked before one-command execution

The final paper head is `80a2b828ef92dbbd504b4384a64a39ac872d3c5a`. It contains the
provider-neutral harness and frozen proposal, but **no approved OpenAI provider adapter**. There is
therefore no honest executable capability command yet. Do not substitute an SDK call or a generic
Responses example.

The smallest morning checklist is:

1. Work in a clean detached checkout at the exact paper head above.
2. Prospectively record primary receiver selection, selector identity/time and treatment-blind
   affirmation. The fallback is not automatic.
3. Review an adapter that implements the two-argument `ReceiverTransport` protocol. Freeze the
   adapter source SHA-256, dependency-lock SHA-256 and import spec. It must call only
   `gpt-4.1-2025-04-14` through Responses, serialize the strict schema and frozen prompts, enforce
   30-second timeout/two attempts/16 output tokens, report real usage/cost, declare
   `candidate_text` in `consumed_fields`, redact the credential, and fail closed on unsupported
   seed/schema/usage semantics.
4. Use an encrypted, access-restricted cache/output directory outside Git with the approved
   180-day retention rule.
5. Securely prompt `OPENAI_API_KEY` into the process environment; never pass it as an argument.
6. Materialize the exact contract and 50 probes from `build_receiver_contract()` and
   `build_capability_probes()`. Verify proposal SHA
   `fd5724eeac0da19f27bd19d9b0023eb2543bd427cbbcc84f543c86742202a7d0` and primary contract
   SHA `a752680abc2ed248bc5d6c31e78dbf124160d3e66760a0cd73dae473b7a81fcd`.
7. Invoke `glee_eval.experiments.controlled_receiver certify` with 2,048 input tokens, 16 output
   tokens and **5,000 microusd per-attempt reservation**. There are exactly 100 nominal requests
   and at most 200 attempts, so the software reservation ceiling is exactly `$1.00`; the frozen
   price estimate remains `$0.8448`. The approved adapter must also pre-reserve predicted cost
   before sending because a post-response usage rejection cannot undo provider spend.
8. Require every generic plumbing check, exact replay, complete expected probe IDs and at least
   5/25 text-only decision changes in **each** receiver replicate. Preserve failures; do not swap
   to the fallback.
9. Obtain a fresh independent hostile audit of adapter bytes, request envelopes, encrypted cache,
   certificate and spend ledger. Capability passage still does not authorize payoff execution or
   set either production pin.

Once items 1–4 have concrete approved values, the adapter owner must provide a reviewed
one-command wrapper binding those hashes and the generic certification CLI. The following is the
exact wrapper shape to use after replacing every `APPROVED_*` non-secret placeholder. It fails
before prompting for a key if commit, cleanliness, adapter or dependency bytes differ. The target
directory must already be an approved encrypted-at-rest location outside Git.

```bash
OPENAI_PAPER_REPO=/absolute/path/to/clean-detached-wave5c-paper OPENAI_FROZEN_PYTHON=/absolute/path/to/reviewed-venv/bin/python OPENAI_ADAPTER_FILE=/absolute/path/to/reviewed_adapter.py OPENAI_ADAPTER_SHA256=APPROVED_64_HEX OPENAI_DEPENDENCY_LOCK=/absolute/path/to/reviewed-lockfile OPENAI_DEPENDENCY_SHA256=APPROVED_64_HEX OPENAI_TRANSPORT_SPEC=approved.module:transport OPENAI_CAPABILITY_DIR=/absolute/path/in/approved-encrypted-storage /usr/bin/env zsh -f -c 'set -euo pipefail; umask 077; test "$(git -C "$OPENAI_PAPER_REPO" rev-parse HEAD)" = 80a2b828ef92dbbd504b4384a64a39ac872d3c5a; test -z "$(git -C "$OPENAI_PAPER_REPO" status --porcelain)"; test "$(shasum -a 256 "$OPENAI_ADAPTER_FILE" | awk '\''{print $1}'\'')" = "$OPENAI_ADAPTER_SHA256"; test "$(shasum -a 256 "$OPENAI_DEPENDENCY_LOCK" | awk '\''{print $1}'\'')" = "$OPENAI_DEPENDENCY_SHA256"; test -d "$OPENAI_CAPABILITY_DIR"; test ! -e "$OPENAI_CAPABILITY_DIR/contract.json"; IFS= read -r -s "OPENAI_API_KEY?OpenAI API key (hidden): "; print; export OPENAI_API_KEY; cd "$OPENAI_PAPER_REPO"; "$OPENAI_FROZEN_PYTHON" -c '\''import json, pathlib; from glee_eval.experiments.controlled_receiver import canonical_json_bytes; from glee_eval.experiments.wave5c_receiver import build_capability_probes, build_receiver_contract, proposal_sha256; out=pathlib.Path(__import__("os").environ["OPENAI_CAPABILITY_DIR"]); contract=build_receiver_contract(); probes=build_capability_probes(); assert proposal_sha256()=="fd5724eeac0da19f27bd19d9b0023eb2543bd427cbbcc84f543c86742202a7d0"; assert contract.sha256=="a752680abc2ed248bc5d6c31e78dbf124160d3e66760a0cd73dae473b7a81fcd"; (out/"contract.json").write_bytes(canonical_json_bytes(contract.to_dict())); (out/"probes.json").write_bytes(canonical_json_bytes({"schema":"glee.research.receiver_capability_probes.v1","probes":[{"probe_id":p.probe_id,"candidate_text_a":p.candidate_text_a,"candidate_text_b":p.candidate_text_b,"economic_stance":dict(p.economic_stance),"visible_inputs":dict(p.visible_inputs),"hidden_inputs":dict(p.hidden_inputs),"seed":p.seed} for p in probes]}))'\''; "$OPENAI_FROZEN_PYTHON" -m glee_eval.experiments.controlled_receiver certify --contract "$OPENAI_CAPABILITY_DIR/contract.json" --probes "$OPENAI_CAPABILITY_DIR/probes.json" --transport "$OPENAI_TRANSPORT_SPEC" --cache-out "$OPENAI_CAPABILITY_DIR/cache.json" --certificate-out "$OPENAI_CAPABILITY_DIR/certificate.json" --reserved-input-tokens 2048 --reserved-output-tokens 16 --reserved-cost-microusd 5000; "$OPENAI_FROZEN_PYTHON" -c '\''import json, os, pathlib; d=json.loads((pathlib.Path(os.environ["OPENAI_CAPABILITY_DIR"])/"certificate.json").read_text()); ids={str(x["probe_id"]) for x in d["probe_results"]}; expected={f"wave5c-generic-{i:02d}-seed-{s}" for i in range(25) for s in (530011,530017)}; changed={s:sum(x.get("output_changed") is True and str(x["probe_id"]).endswith(f"-seed-{s}") for x in d["probe_results"]) for s in (530011,530017)}; assert d["passed"] and ids==expected and all(v>=5 for v in changed.values())'\''; unset OPENAI_API_KEY'
```

This is a template, not present authorization. `APPROVED_64_HEX` must never be guessed and the
transport spec must never point to the ineligible dry-run transport. Until an adapter review
supplies those non-secret pins, the exact morning result is `NO-GO_ADAPTER_ABSENT`;
`OPENAI_API_KEY` alone is insufficient.
