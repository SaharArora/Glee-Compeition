# Wave 5B data-feedback and versioning contract

Status: **prospective contract; no live collection or model update performed.**

The existing live logs are terminal-complete but cannot validate the leaderboard proxy: launch
manifests name the agent class but omit its git commit, and no record contains official per-game
percentile/rating or the private opponent adjustment. The contract below prevents that
identifiability loss from recurring.

## Immutable layers

1. **Raw capture.** Append-only observations, submitted actions, move responses, terminal
   backfills, platform stats and per-game official scoring payloads. Every line receives a schema
   version, UTC capture time, game ID, run ID and byte hash.
2. **Run manifest.** Before queueing, freeze agent commit and source-tree status, agent identity,
   exact entrypoint, environment variables, model/support/config artifact paths and SHA-256s,
   dependency lock hash, platform/API version, selected families, queue cap and named seeds.
3. **Normalized snapshot.** A content-addressed dataset manifest records source files, row/game
   counts, canonical-config version, parser version, exclusions, terminal coverage, and the exact
   transformation code commit. Raw bytes are never overwritten.
4. **Fit artifact.** Records training snapshot SHA, actor/config fold manifests, feature/target
   schema, hyperparameters, solver provenance, code/dependency hashes and training-only metrics.
5. **Evaluation certificate.** Binds fit artifact, untouched snapshot/fold, prediction rows,
   proper-score definitions, cluster bootstrap seeds and pass/fail thresholds. Evaluation results
   never mutate a prior artifact.

## Required live record per game

- exact candidate commit and dirty-tree digest; agent and platform identities;
- family, candidate role, complete public configuration, horizon/information/message regime;
- all role-visible observations and exact submitted actions, with parser/fallback provenance;
- opponent identifier/strength fields exposed by the platform and an explicit `unavailable` marker
  for private fields;
- terminal outcome, normalized and raw role payoffs, terminal source/backfill status;
- game count before/after, displayed rating before/after, official per-game percentile/rating and
  every public adjustment component if exposed;
- timeout, retry, invalid action, API error and duplicate-game counters;
- Model-A/Model-C/support versions used for diagnostics, even when none are active.

If the platform does not expose official per-game output or opponent adjustment, store that as a
schema-level absent capability. Never reverse-engineer it from an underdetermined displayed-rating
sequence.

## Feedback boundaries

- A live batch is immutable after terminal reconciliation. Corrections create a superseding
  manifest linked to the original, never edited rows.
- Training consumes only snapshots whose purpose was frozen before outcomes. Canary results may
  diagnose or nominate the next version; they may not both tune and confirm it.
- Research receiver/capability data, competition live data, factorial outcomes and simulator
  rollouts use separate namespaces and authorization ledgers.
- Model A, B, C and D carry independent semantic versions. An A update never silently rewrites C,
  the four-arm baseline, or the competition champion.
- Each deployment is a tuple `(agent commit, A, B, C, D, support/config, adapter, platform)`.
  Missing components are explicit `none`, not ambient defaults.
- Reproducible parser/semantic-key corrections increment the normalized snapshot version and
  invalidate downstream hashes; they do not rewrite history.

## Promotion and rollback

A new evaluator/model version progresses through development OOF, independent structural
validation, offline policy sensitivity, bounded unrated/sandbox integration where available, and
only then a separately authorized live canary. The previous champion and its artifacts remain
deployable until the canary success certificate is complete. Rollback restores the entire version
tuple, not just the Python class.

Minimum monitoring is terminal coverage 100%, invalid/fallback rate, latency/timeout rate,
family/role/config support, official per-game score when available, normalized payoff and drift
from the version's validation calibration. Any unknown critical field blocks evidence but does not
silently discard the game.
