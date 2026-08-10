# GLEE Competitor Harness

Local evaluation, data generation, and failure mining for GLEE-style bargaining, negotiation, and persuasion agents.

This repository is designed to help you iterate before making a real leaderboard submission:

- Create a candidate agent.
- Run historical decision probes.
- Run synthetic tournaments.
- Search for hard failure scenarios.
- Save structured traces for later analysis, hypothesis generation, and training data construction.

## Quick Start

Edit the starter agent:

```text
my_agents/baseline.py
```

Run a small experiment:

```bash
python -m glee_eval experiment \
  --agent my_agents.baseline:MyAgent \
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
runs/smoke/hypotheses/hypotheses.md
runs/smoke/manifest.json
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

## GLEE Upstream

This harness expects the official GLEE repository to be cloned separately under:

```text
work/GLEE/
```

The upstream GLEE repository and generated GLEE-derived data are intentionally ignored by git.

Do not commit:

- `work/GLEE/`
- `data/processed/`
- `data/empirical/`
- `reports/`
- `runs/`
- API keys or model-provider configs

See [docs/USAGE.md](docs/USAGE.md) for the full workflow.
