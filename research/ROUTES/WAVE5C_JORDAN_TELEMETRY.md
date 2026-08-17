# Wave 5C Route L — attributable Jordan canary

Status: **readiness state 2 — ready for one bounded live canary, not authorized or executed.**

Route L changed telemetry only. It did not modify Jordan, any frozen research agent, the
evaluator, or a promotion pin. It queued zero games and played zero live/rated games. One
authenticated read-only `/stats` request verified the platform identity and aggregate-stat
schema without entering matchmaking.

## Frozen deployment tuple

- policy candidate: `bce578597dbfacf2ebca38399edb41a5dde2f936`;
- entrypoint: `my_agents.jordan_strategic:MyAgent`;
- policy path/hash: `my_agents/jordan_strategic.py`,
  `27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82`;
- platform identity: `99357c15-48d5-4177-9d6a-48d02b95a164` / `gangsteryoshi`;
- telemetry implementation checkpoint: `8950b3cb633195929e273a57c64f8db5f5b782a2`;
- optional artifacts: all four `GLEE_OPPONENT_POPULATION`, `GLEE_CONFIG_CATALOGUE`,
  `GLEE_RESPONSE_MODEL`, and `GLEE_SUPPORT_INDEX` must be absent.

The launcher records two identities separately. `candidate_commit` pins Jordan's policy bytes;
the clean telemetry worktree HEAD pins the launcher and adapter bytes. The launcher verifies the
current Jordan file byte-for-byte against the Git object at the candidate commit. It therefore
does not pretend the later telemetry commit is a new Jordan policy.

## What is now captured

`glee_eval.live_telemetry` creates a canonical configuration and launch manifest before queueing.
It records exact HEAD, a deterministic tracked-plus-untracked dirty digest, frozen policy digest,
entrypoint, expected and observed UUID/name, family/game caps, runtime/SDK version, optional
artifact paths and byte hashes, non-secret environment hashes, and a keyed HMAC fingerprint for
the API credential. The HMAC key and API key are never serialized. Hostile credential echoes in
unexpected platform fields are redacted again at the final ledger boundary.

Every raw event is linked to one batch and configuration digest, monotonically sequenced,
timestamped, fsync'd, and SHA-256 hash-chained. Per-game events capture scenario ID and payload,
family, role, action and attempt, fallback status, move validity, payoff, terminal status, and
before/after aggregate platform snapshots. Terminal responses and GET backfills carry an explicit
capability record for official percentile, official game rating, rating update, and public
opponent adjustment. A missing field is recorded as `status=unavailable`; aggregate family
`scores.*.rating` is deliberately not mislabelled as a per-game rating.

The launcher stops and preserves a partial batch on identity mismatch, dirty code, artifact
drift, unresolved terminal, duplicate/conflicting game, cap violation, crash, transport timeout,
API failure, or missing official per-game rating. It independently re-reads the raw ledger to
write `reconciliation.json`. `glee_eval.telemetry_audit` is a separate hostile verifier: it does
not import or trust that reconciler and recomputes configuration hashes, the event chain, frozen
identity, terminal uniqueness/completeness, required fields, and official-score availability.

## Verification and capability result

- 18 Route-L tests passed under Python 3.14 with `glee-sdk==0.0.5`, including the real SDK
  `_handle_game` boundary with all HTTP methods replaced offline.
- 95 live-path compatibility tests passed with no skips.
- A clean three-family offline launch produced 22 linked events, three unique terminals and an
  independent hostile-audit `PASS`; secret-literal, dirty-tree, identity-mismatch,
  configuration-tamper and duplicate-terminal attacks all fail.
- The read-only live `/stats` response exposed the exact expected `agent_id` and `agent_name`,
  `active_games=0`, and aggregate family game counts/ratings. It did not expose per-game scoring,
  which is expected because no game was played.

The actual terminal `move`/`game_state` payload's official per-game fields remain unobserved.
That is not silently assumed away: if the first one-per-family wave lacks `game_rating`, the
launcher records each capability as unavailable, drains/backfills those three games, and stops
globally. The 300-game scientific result would then be unavailable, but the batch would remain
attributable and bounded.

## Readiness verdict

1. Operationally ready to deploy: **yes**.
2. Ready for one bounded live canary: **yes, technically; separate user authorization required**.
3. Showing preliminary competitive performance: **no**.
4. Plausibly top-five competitive: **no**.
5. Demonstrating a winning agent: **no**.

Remaining prerequisites are operational rather than code changes: keep a clean detached checkout
of the telemetry checkpoint, supply `GLEE_API_KEY`, supply an independent at-least-32-byte
`GLEE_TELEMETRY_HMAC_KEY`, install the declared `glee-sdk==0.0.5` runtime, and provide the exact
authorization sentence below. The platform's per-game official-score capability remains unknown
until the first authorized terminal response.

## Exact future canary

Prepare a clean detached checkout at `8950b3cb633195929e273a57c64f8db5f5b782a2`; create a fresh
runtime with `python3 -m pip install -e '.[live]'`; load the API key and a distinct HMAC key; and
verify the output directory does not yet exist. The only launch command is:

```bash
env -u GLEE_OPPONENT_POPULATION -u GLEE_CONFIG_CATALOGUE -u GLEE_RESPONSE_MODEL -u GLEE_SUPPORT_INDEX \
  /path/to/frozen-live-venv/bin/python -m glee_eval.live_telemetry launch \
  --repo /Users/sahararora/Documents/Codex/Glee-Wave5C-L \
  --output-dir /Users/sahararora/Glee-Compeition/reports/live/jordan_canary_wave5c_001 \
  --per-family-games 100 --concurrency 3 --poll-interval 2
```

Expected maximum: 100 terminal games per family, 300 total. The run queues one game per active
family per wave. Immediate global stops are attribution failure, duplicate/conflicting game,
unresolved terminal, cap violation, identity/config drift, or official per-game rating
unavailable. Three invalid/fallback actions in a family stop the run; three timeout/API failures
pause that family. After 30 official ratings in a family, its one-sided 95% UCB below 1800
pauses it; two paused families or the family-balanced pooled UCB below 1800 stops globally. One
unrecovered transport exception after the SDK's safe internal retries is treated more strictly as
an attribution-preserving global stop; the launcher never replays an ambiguous POST itself.
Expansion success requires all 300 terminals, integrity limits, and every family's one-sided 95%
LCB at least 2000. No expansion is authorized by this route.

Post-run commands, even for a stopped partial batch:

```bash
/path/to/frozen-live-venv/bin/python -m glee_eval.live_telemetry reconcile \
  --output-dir /Users/sahararora/Glee-Compeition/reports/live/jordan_canary_wave5c_001
/path/to/frozen-live-venv/bin/python -m glee_eval.telemetry_audit \
  --output-dir /Users/sahararora/Glee-Compeition/reports/live/jordan_canary_wave5c_001 \
  --expected-per-family 100
```

The single sufficient authorization sentence is:

> I authorize exactly one bounded Jordan canary of at most 300 live/rated games—100 terminal
> games per family—using the frozen Wave 5C Route-L tuple and stop rules, and no other live games.
