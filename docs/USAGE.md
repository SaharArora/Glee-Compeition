# GLEE Eval Harness Usage

## 1. Create Or Edit An Agent

Edit:

```text
my_agents/baseline.py
```

Your agent should subclass `CandidateAgent` and implement:

```python
def decide(self, state: GameState) -> AgentAction:
    ...
```

The harness loads custom agents with:

```text
module.path:ClassName
```

For the included baseline:

```text
my_agents.baseline:MyAgent
```

For the Jordan-inspired evidence-gated strategic-control agent:

```text
my_agents.jordan_strategic:MyAgent
```

## 2. Empirical-First Workflow

Bluntly: if you have access to a large real GLEE dataset, do not use synthetic simulation as the main behavioral dataset. The better workflow is:

```text
real GLEE games -> dataset audit -> empirical priors/response models -> targeted simulation -> agent iteration
```

First ingest the real records:

```bash
python -m glee_eval ingest \
  --glee-root work/GLEE \
  --families bargaining,negotiation,persuasion \
  --sources llm_vs_llm,human_vs_llm \
  --output-dir data
```

Then run the audit:

```bash
python -m glee_eval dataset-audit \
  --data-dir data \
  --output-dir reports/dataset_audit
```

Read:

```text
reports/dataset_audit/audit.md
reports/dataset_audit/audit.json
```

The audit checks:

- games/events by family, source, role, and configuration
- action distributions and coarse empirical support bins
- message coverage
- private/public state key coverage
- player/model identity availability
- whether the data is only useful for smoke testing or rich enough to be an empirical foundation

If the verdict is `no_processed_dataset` or `toy_or_smoke_dataset`, do not run huge continuous simulations expecting a serious training set. Get more real data first, and use synthetic games only to verify the harness and find obvious agent failures.

If the verdict is `empirical_foundation_candidate`, make real data the main foundation and use simulation only for counterfactual evaluation, rare cases, adversarial testing, and policy stress tests.

## 3. Run Historical Decision Probes

Historical probes ask your agent what it would do at states extracted from real GLEE logs.

```bash
python -m glee_eval probes \
  --agent my_agents.baseline:MyAgent \
  --data-dir data \
  --limit 1000 \
  --output-dir reports/my_agent_probes
```

This does not pretend the historical continuation is a counterfactual. It is a cheap decision-quality benchmark.

## 4. Run A Simulation Stress-Test Experiment

This runs probes when processed real data exists, plus a synthetic tournament, adversarial scenario search, dataset export, and hypothesis generation into one self-contained run folder. Treat it as stress testing unless the dataset audit shows that your real GLEE data is too small or unavailable.

Small smoke run:

```bash
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name jordan_smoke \
  --families bargaining,negotiation,persuasion \
  --games 100 \
  --probe-limit 100 \
  --search-population 50 \
  --search-generations 2 \
  --seed 42
```

Larger targeted run after the audit:

```bash
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name my_agent_v1 \
  --families bargaining,negotiation,persuasion \
  --games 10000 \
  --probe-limit 10000 \
  --search-population 2000 \
  --search-generations 5 \
  --search-elite-frac 0.05 \
  --seed 42
```

Main outputs:

```text
runs/my_agent_v1/manifest.json
runs/my_agent_v1/tournament/episodes.jsonl
runs/my_agent_v1/probes/decisions.jsonl
runs/my_agent_v1/search/<family>/elite_episodes.jsonl
runs/my_agent_v1/datasets/state_action_outcome.jsonl
runs/my_agent_v1/datasets/episode_summary.jsonl
runs/my_agent_v1/datasets/failure_cases.jsonl
runs/my_agent_v1/matches/match_ledger.md
runs/my_agent_v1/matches/match_ledger.csv
runs/my_agent_v1/matches/match_ledger.jsonl
runs/my_agent_v1/hypotheses/hypotheses.md
```

Use `state_action_outcome.jsonl` for later analysis/training-data conversion. Use `hypotheses.md` as the first-pass research memo on where the agent seems weak.

Use `matches/match_ledger.md` as the running document for compiled match results. It summarizes all matches and lists the highest-regret rows up to `--match-report-limit` so very large runs do not create an unreadable document. The full match ledger is always available in `matches/match_ledger.csv` and `matches/match_ledger.jsonl`.

## 5. Run Synthetic Tournaments Only

Synthetic tournaments play full games against deterministic opponent archetypes.

```bash
python -m glee_eval tournament \
  --agent my_agents.baseline:MyAgent \
  --families bargaining,negotiation,persuasion \
  --games 10000 \
  --seed 42 \
  --output-dir reports/my_agent_tournament
```

Outputs:

```text
reports/my_agent_tournament/episodes.jsonl
reports/my_agent_tournament/metrics.json
```

## 6. Search For Failures Only

Use this to generate hard scenarios before working on leaderboard submissions.

```bash
python -m glee_eval search-failures \
  --agent my_agents.baseline:MyAgent \
  --family negotiation \
  --population 2000 \
  --elite-frac 0.05 \
  --generations 5 \
  --objective maximum_regret \
  --output-dir reports/my_agent_search
```

Outputs:

```text
reports/my_agent_search/elite_episodes.jsonl
reports/my_agent_search/summary.json
```

## 7. Refresh Historical Data

Small all-family sample:

```bash
python -m glee_eval ingest \
  --glee-root work/GLEE \
  --limit 5 \
  --families bargaining,negotiation,persuasion \
  --sources llm_vs_llm \
  --output-dir data
```

Larger runs:

```bash
python -m glee_eval ingest \
  --glee-root work/GLEE \
  --limit 1000 \
  --families bargaining,negotiation,persuasion \
  --sources llm_vs_llm,human_vs_llm \
  --output-dir data
```

Then:

```bash
python -m glee_eval validate --data-dir data
python -m glee_eval stats --data-dir data
python -m glee_eval dataset-audit --data-dir data --output-dir reports/dataset_audit
python -m glee_eval calibrate-population --games 10000 --data-dir data --output-dir reports
```

## 8. Publishing Guidance

Do not commit:

- `work/`
- `data/processed/`
- `data/empirical/`
- `reports/`
- API keys or model-provider configs

The harness should be published as code that expects users to clone GLEE separately.
