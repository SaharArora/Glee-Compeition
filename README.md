# GLEE Competitor Harness

Towards charisma.

Local evaluation, empirical-data auditing, and failure mining for GLEE-style bargaining, negotiation, and persuasion agents.

This repository is designed to help you iterate before making a real leaderboard submission:

- Create a candidate agent.
- Audit real GLEE data before treating simulations as training data.
- Run historical decision probes.
- Run synthetic tournaments as smoke tests and stress tests.
- Search for hard failure scenarios.
- Estimate an official-style shadow leaderboard score from local reference percentiles.
- Save structured traces for later analysis, hypothesis generation, and training data construction.

## Quick Start

Blunt strategy note: if you have access to a large real GLEE dataset, do not make synthetic simulation your primary behavioral dataset. Use real games as the empirical foundation, then use simulation for counterfactuals, adversarial testing, rare cases, and policy stress tests.

Edit the starter agent:

```text
my_agents/baseline.py
```

The Jordan-inspired strategic-control agent from the redesign PDF is implemented at:

```text
my_agents/jordan_strategic.py
```

Run a small experiment:

```bash
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name smoke \
  --games 100 \
  --search-population 50 \
  --search-generations 2
```

The run appears under:

```text
runs/smoke/
```

Important outputs:

```text
runs/smoke/datasets/state_action_outcome.jsonl
runs/smoke/datasets/episode_summary.jsonl
runs/smoke/datasets/failure_cases.jsonl
runs/smoke/matches/match_ledger.md
runs/smoke/matches/match_ledger.csv
runs/smoke/hypotheses/hypotheses.md
runs/smoke/shadow_score/shadow_score.md
runs/smoke/manifest.json
```

## Empirical-First Workflow

If you have the official GLEE data available locally, ingest and audit it before running large simulations:

```bash
python -m glee_eval ingest --glee-root work/GLEE --output-dir data
python -m glee_eval dataset-audit --data-dir data --output-dir reports/dataset_audit
```

Read:

```text
reports/dataset_audit/audit.md
reports/dataset_audit/audit.json
```

If the audit says `toy_or_smoke_dataset` or `no_processed_dataset`, keep simulations small. If it says `empirical_foundation_candidate`, shift effort toward empirical response models and use simulation only for targeted stress tests.

Train the first empirical response surfaces:

```bash
python -m glee_eval train-response-models --data-dir data --output-dir models/response_v0
export GLEE_RESPONSE_MODEL=models/response_v0
```

With `GLEE_RESPONSE_MODEL` set, `my_agents.jordan_strategic:MyAgent` uses the learned response estimates where support is available and falls back to its original conservative rules elsewhere.

Run a same-seed A/B comparison:

```bash
unset GLEE_RESPONSE_MODEL
python -m glee_eval experiment --agent my_agents.jordan_strategic:MyAgent --name ab_rule_jordan_300 --games 300 --seed 20260812

export GLEE_RESPONSE_MODEL=models/response_v0
python -m glee_eval experiment --agent my_agents.jordan_strategic:MyAgent --name ab_empirical_jordan_300 --games 300 --seed 20260812
```

Compare:

```text
runs/ab_rule_jordan_300/shadow_score/shadow_score.md
runs/ab_empirical_jordan_300/shadow_score/shadow_score.md
```

## What Gets Collected

Every experiment preserves:

- Candidate-visible state.
- Candidate action.
- Opponent/scenario metadata.
- Terminal outcome.
- Candidate and opponent payoff.
- Regret signal where available.
- Failure diagnostics.
- Hypothesis clusters.

The most reusable file is:

```text
state_action_outcome.jsonl
```

Each row is a candidate decision record that can later be analyzed, filtered, clustered, or converted into training data.

For a human-readable running match digest, use:

```text
matches/match_ledger.md
```

For the full one-row-per-match ledger, use:

```text
matches/match_ledger.csv
matches/match_ledger.jsonl
```

## GLEE Upstream

This harness expects the official GLEE repository to be cloned separately under:

```text
work/GLEE/
```

The upstream GLEE repository and generated GLEE-derived data are intentionally ignored by git.

Do not commit:

- `work/`
- `data/processed/`
- `data/empirical/`
- `reports/`
- `runs/`
- `models/`
- API keys or model-provider configs

See [docs/USAGE.md](docs/USAGE.md) for the full workflow.
