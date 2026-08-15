# Live competition integration

How to get the agent playing rated games. Competition closes **29 August 2026**.

## What you need to do (I can't)

1. Sign in at [glee-competition.com](https://glee-competition.com), create an agent in the
   Dashboard, and copy its API key. Creating accounts and handling credentials is yours —
   I never see the key.
2. Put the key in your shell. It is read from the environment, never from a file in the repo:

   ```bash
   export GLEE_API_KEY=glee_...
   ```

## What is already built

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[live]'      # pulls glee-sdk
.venv/bin/python -m glee_eval live --dry-run       # rehearse, no network, no key
.venv/bin/python -m glee_eval live --concurrency 6 # play for real
```

`--dry-run` pushes one synthetic payload per documented phase of every family through the
whole adapter and prints the action it would submit. It rehearses *our* half of the contract
only — it cannot confirm the server's real payloads match the documented shapes.

Useful flags: `--families bargaining,negotiation`, `--max-games`, `--max-time`,
`--agent my_agents.baseline:MyAgent`, `--poll-interval`.

## The design constraint that shapes everything

`GleeClient._handle_game` catches any exception from the strategy, logs it, and returns
**without submitting a move**. From the server's side that is indistinguishable from us
going silent: the turn times out, and a timeout is scored at the **5th percentile**. With the
`g/(g+30)` rating discount, early games are weighted heavily enough that one such incident
can move a family rating by roughly 400 points.

So a crash in our code is not a loud failure — it is a silent, expensive one. `LiveStrategy`
therefore guarantees:

- **It never raises.** Every failure path — translation error, agent exception, agent
  returning a non-action, unknown family — lands on a legal fallback move. It catches
  `BaseException`, not `Exception`, because a `KeyboardInterrupt` landing mid-turn would
  otherwise cost a real game.
- **The fallback itself cannot raise.** If `fallback_action` fails, a last-resort
  `{"decision": "no"}` is returned, which is legal in every decision phase.
- **Messages are capped** at the SDK's `MAX_MESSAGE_LEN` (2000). The server rejects a longer
  message as an *invalid move*, burning one of a small number of attempts, and never
  truncates for us. A test asserts our constant tracks the SDK's.
- **Bargaining gains sum exactly** to `money_to_divide`. The counterpart's share is derived
  by subtraction rather than rounded independently, so floating point cannot produce an
  invalid move.
- **A negotiation rejection always carries a counteroffer**, except on the final round of a
  capped game where the server takes none. `RejectOffer` without a price is invalid.
- **Every turn is logged** to `reports/live/observations.jsonl` with the raw payload, the
  translated state, the action, the status and the elapsed time.

## Schema differences from our offline format

Each of these is a place where a silent mistranslation costs rating. We have already been
bitten twice by exactly this class of bug offline — `raw.round_quality` vs `quality` made the
agent decline all 66,480 real buyer decisions — so the mapping is written out rather than
inferred.

| concept | offline | live |
|---|---|---|
| bargaining offer | `self_gain` / `other_gain` | `alice_gain` / `bob_gain`, must sum exactly |
| bargaining history | transcript rows | `game_state["last_offer"]` |
| bargaining exit | (none) | `decision: "walkaway"` |
| bargaining horizon | `max_rounds` always present | **absent when unbounded**, flagged by `horizon_known` |
| negotiation role | `role` | `player_N_role` |
| negotiation values | `seller_value` / `buyer_value` | `player_N_value` |
| negotiation price | normalised by `product_price_order` | **absolute, no order** |
| negotiation exit | `SellToJhon` / `BuyFromJhon` | `WalkAway` |
| negotiation rejection | bare decision | **requires a counteroffer** |
| persuasion low value | `c` | **`u`** |
| persuasion quality | `"high-quality"` | **`"high"`** |

**Scale matters as much as naming.** Live negotiation prices are absolute and can be in the
tens of thousands, while the agent's rules are tuned in units where a valuation is near 1.0 —
a constant like "concede 0.04" is meaningless against a price of 12,500. Everything is
normalised by the player's own valuation (always visible) on the way in and multiplied back
on the way out.

**An absent `max_rounds` becomes a horizon of 99, not 0.** Zero would make every round look
like the endgame and collapse the agent's accept floor.

## What is *not* verified

The fixtures in `glee_eval/live/fixtures.py` are built by hand from glee-sdk documentation.
They are a statement of what we believe the server sends, not a capture of a real game. A
2026-08-15 re-verification against the current official glee-sdk 0.0.5 documentation found
that action vocabularies and scalar mappings agree, but the input fixtures are incomplete:

- Current docs say every `game_state` contains `history`; all seven fixtures omit it and the
  adapter reconstructs only from `last_offer` or persuasion totals.
- Documented history rows differ by family: bargaining has proposer/offer/decision;
  negotiation has offer/decision/optional counteroffer/decider; persuasion has seller message,
  buyer decision, purchase, optional quality, and both payoffs.
- Persuasion fixtures omit documented `current_player`.
- The current interpreter has no installed `glee_sdk`, so SDK integration tests skip.
- Older claims that live persuasion has no per-round history, or that buyer knowledge of `p`
  is optional, are stale under the current documentation.

The mismatch was repaired immediately after the audit: all seven fixtures now carry documented
history, persuasion fixtures carry `current_player`, contracts validate both, and the adapter
consumes family-specific history while retaining `last_offer`/totals compatibility fallbacks.
The adapter is now **docs-verified** but remains unverified against the real server. Two
consequences:

- The adapter can be tested through the SDK's real `_handle_game` only when the SDK is installed,
  and still only against our fixtures. A field the live server describes differently would pass
  every dry test and still be wrong.
- `reports/live/observations.jsonl` exists precisely for this. **The first few real games are
  the cheapest chance to catch a mistranslation**, so check that log after the first run
  rather than after a hundred games.

Suggested first run — small, bounded, and inspectable:

```bash
.venv/bin/python -m glee_eval live --max-games 5 --concurrency 2
python3 -c "
import json
for line in open('reports/live/observations.jsonl'):
    r = json.loads(line)
    print(r['status'], r['game_family'], r['action_type'], '->', r['action'])
"
```

Anything other than `ok` in that `status` column on an expressly authorized real game is a
schema mismatch to fix before scaling up. This documentation does not authorize such a game.

### Reading the observation log

Summarize the adapter log directly with:

```bash
python3 -m glee_eval stats --observations reports/live/observations.jsonl
```

`shadow-score` deliberately does not accept this turn log. Official-style percentiles require
terminal candidate payoff, scenario/configuration, and reference episodes; the observation log
contains pre-action turn payloads and omits terminal outcomes. Audit what can be reconstructed
without inventing outcomes with:

```bash
python3 -m glee_eval live-episodes \
  --observations reports/live/observations.jsonl \
  --output-dir reports/live/episode_audit
```

This writes one audit row per game plus a summary. Rows whose opponent acted after our final
callback remain `indeterminate`; they are never coerced to zero or silently excluded from a
family mean. Only a complete terminal episode export can be passed to `shadow-score`:

```bash
python3 -m glee_eval shadow-score \
  --episodes RUN/datasets/episode_summary.jsonl \
  --data-dir data
```

Both `python3 -m glee_eval stats --help` and
`python3 -m glee_eval shadow-score --help` now show their command-specific options.

The historical `schema_violation` totals reported by `stats` are intentionally unchanged after
a contract fix: the observation log is an append-only record of what the adapter reported at
the time. Replaying raw payloads against the current contract is a separate validation step.

### Terminal-result coverage

The first observation file contains 1,423 turns from 109 game IDs, consistent with the roughly
30-games-per-family batch. It has no authoritative terminal-result or payoff fields. Conservative
reconstruction finds bargaining 15 reconstructed / 21 indeterminate, negotiation 13 / 23,
and persuasion 19 / 18; seven reconstructed negotiation acceptances also lack the normalization
order. Consequently no unbiased family payoff mean, HANDOVER section 4 divergence, or
official-style shadow rating can be computed from this file. Averaging only reconstructible
games would select on which player made the terminal move.

Future live runs capture every SDK `move` response in `reports/live/move_results.jsonl`, including
the complete terminal result when our submitted move ends the game. After the run, games without
such a response are read-only GET-backfilled into the same file. `run_summary.json` reports the
direct/backfilled/error counts, and `launch_manifest.json` records whether the support index and
other non-secret model paths were configured, plus file hashes. This capture is prospective and
does not recover the existing observation file. It does not authorize a live run.

### Real-server value visibility correction (50-game batch)

The first 50-game batch confirmed that persuasion `u/v` have no alternate live spelling. They
are absent only when our role is seller and `is_seller_know_cv=false`: six games, all 20 rounds,
for 120 affected turns. Buyer turns and informed-seller turns carry `u/v` normally. The contract
now models that information boundary, and all 1,423 captured payloads replay with zero
violations. No fallback occurred, so the contract report was a false-positive validation
alert. Do not overstate the policy impact: the direct recommendation and response-model paths
ignore `v/c`, but an optional `GLEE_SUPPORT_INDEX` coverage lookup includes them in its context
key and can change strategic mode. The observation log does not record whether that index was
active, so this batch proves no harm from validation/fallback behavior but does not prove full
action equivalence or a zero rating effect through coverage.

The 109-game run predates `launch_manifest.json`. Its saved summary does not record environment
settings, and shell history records no `GLEE_SUPPORT_INDEX` assignment. The variable is unset in
the current shell, but that is not evidence of its earlier value; activation for this batch is
therefore **inconclusive**, not assumed false. Independently, missing hidden persuasion `v/c`
values now remain missing in coarse coverage keys rather than aliasing genuine numeric-zero bins.

Do not run further live games merely to verify this correction. Live/rated re-verification
still requires explicit user authorization for that individual run.

## Volume, once it works

- Rating is discounted by `g/(g+30)`, so early games count for little and volume is needed
  before a rating means anything.
- **All three families must be played.** An unplayed family sits at the 1,000 starting rating
  and drags the overall average down. Persuasion has to actually ship, not just be diagnosed.
- Holding a top-100 place in a family needs ~10 games/day in it.
- Rate limit is 60 requests/minute per agent; up to 5 agents per account. `concurrency` of
  4–10 is the SDK's suggested range, and it backs off automatically.
- If matchmaking finds no opponent within 30 seconds it matches an LLM baseline, but only
  when you have no other game in flight — keeping several games running avoids it.

## Ranking note

Placement is **self-gain only**. Efficiency and fairness are recorded for post-competition
analysis but do not affect rank. Worth remembering if a future change trades measured payoff
for something that merely looks fairer.
