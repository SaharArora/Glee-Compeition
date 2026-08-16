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
reports/dataset_audit/support_index.json
```

The audit checks:

- games/events by family, source, role, and configuration
- action distributions and coarse empirical support bins
- message coverage
- private/public state key coverage
- player/model identity availability
- whether the data is only useful for smoke testing or rich enough to be an empirical foundation
- state-action support coverage by family/config/role/round bucket

If the verdict is `no_processed_dataset` or `toy_or_smoke_dataset`, do not run huge continuous simulations expecting a serious training set. Get more real data first, and use synthetic games only to verify the harness and find obvious agent failures.

If the verdict is `empirical_foundation_candidate`, make real data the main foundation and use simulation only for counterfactual evaluation, rare cases, adversarial testing, and policy stress tests.

## 3. Train Empirical Response Models

This trains lightweight, interpretable response surfaces from processed GLEE events:

```bash
python -m glee_eval train-response-models \
  --data-dir data \
  --output-dir models/response_v0 \
  --min-support 50 \
  --alpha 5.0
```

Outputs:

```text
models/response_v0/model.json
models/response_v0/training_summary.json
models/response_v0/training_report.md
```

The v0 model estimates:

- bargaining: `P(accept | offered_share, role, round, config, source)`
- negotiation: `P(AcceptOffer | normalized_price, role, round, surplus, source)`
- persuasion: `P(buy | recommendation, quality, round, p-bin, message-style, source)`

It also stores support counts, uncertainty, theory-residual summaries, and lightweight population-structure features by `family|config_id|role`. Sparse or out-of-support buckets are penalized at runtime.

Enable the model-backed Jordan agent:

```bash
export GLEE_RESPONSE_MODEL=models/response_v0
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name empirical_jordan_smoke \
  --games 100 \
  --probe-limit 1000 \
  --search-population 100 \
  --search-generations 2
```

Unset the variable to run the original rule-only agent:

```bash
unset GLEE_RESPONSE_MODEL
```

## 4. Estimate A Shadow Leaderboard Score

GLEE's live leaderboard scores payoff by percentile against the same configuration and role, then maps that percentile to a game rating:

```text
game rating = 2000 + 8000 * (percentile - 0.5)
```

The local shadow scorer uses ingested GLEE games as the reference pool. It cannot reproduce the private live opponent-strength adjustment, so treat it as a directional official-style estimate rather than an exact leaderboard replica.

For any experiment run:

```bash
python -m glee_eval shadow-score \
  --run-dir runs/empirical_jordan_smoke \
  --data-dir data
```

Outputs:

```text
runs/empirical_jordan_smoke/shadow_score/shadow_score.md
runs/empirical_jordan_smoke/shadow_score/shadow_score.json
runs/empirical_jordan_smoke/shadow_score/scored_episodes.csv
```

New experiment runs create this folder automatically when `data/processed/games.jsonl` exists. Add `--skip-shadow-score` if you want to skip it.

Read the family table first. A strong agent should improve mean percentile in all three families; one weak family will cap the overall score because missing or weak family ratings are averaged into the leaderboard result.

Negotiation output also includes a separately labelled `trade_zone_stratified_percentile`.
It compares an episode only with reference games in the same role and gains/no-trade zone and
helps expose distortion when fallback buckets pool those regimes. It never changes the primary
percentile or rating: the live formula is private, so this is a diagnostic rather than a claim
about placement.

## 5. Run A/B Tests

Use the same seed and run size so differences are mostly from the agent variant, not scenario sampling.

Rule-only Jordan:

```bash
unset GLEE_RESPONSE_MODEL
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name ab_rule_jordan_300 \
  --families bargaining,negotiation,persuasion \
  --games 300 \
  --probe-limit 1000 \
  --search-population 150 \
  --search-generations 2 \
  --seed 20260812
```

Empirical-model Jordan:

```bash
export GLEE_RESPONSE_MODEL=models/response_v0
python -m glee_eval experiment \
  --agent my_agents.jordan_strategic:MyAgent \
  --name ab_empirical_jordan_300 \
  --families bargaining,negotiation,persuasion \
  --games 300 \
  --probe-limit 1000 \
  --search-population 150 \
  --search-generations 2 \
  --seed 20260812
```

Compare:

```text
runs/ab_rule_jordan_300/shadow_score/shadow_score.md
runs/ab_empirical_jordan_300/shadow_score/shadow_score.md
runs/ab_rule_jordan_300/matches/match_ledger.md
runs/ab_empirical_jordan_300/matches/match_ledger.md
```

The first decision rule is simple:

- If shadow mean percentile improves without increasing `IR_VIOLATION`, keep the change.
- If payoff improves but low-support bucket count is high, treat it as a hypothesis, not a proven improvement.
- If negotiation mean percentile or displayed rating is worse, patch negotiation before running longer tests.

## 6. Targeted Simulation And Diagnostics

The standard experiment pipeline now runs an audit first and routes experiment-time simulation through the targeted dispatcher. The dispatcher has exactly five trigger labels:

```text
rare_type
counterfactual
adversarial
long_horizon
policy_optimization
```

Every simulated episode is tagged with one trigger in `scenario.metadata.simulation`, and the run-level ledger records why simulation fired:

```text
runs/<run_name>/simulation/simulation_ledger.jsonl
```

The match ledger also includes the trigger column:

```text
runs/<run_name>/matches/match_ledger.md
```

Negotiation diagnostics run as a normal experiment stage:

```text
runs/<run_name>/diagnostics/negotiation/negotiation_diagnostic.md
runs/<run_name>/diagnostics/negotiation/negotiation_diagnostic.json
```

The diagnostic compares real accepted-deal surplus capture, midpoint residuals, support coverage near the current surplus-capture floor, and smoke-test negotiation failures. Its top candidate cause is inserted into:

```text
runs/<run_name>/hypotheses/hypotheses.md
```

You can also run it directly:

```bash
python -m glee_eval negotiation-diagnostic \
  --data-dir data \
  --run-dir runs/ab_empirical_jordan_300 \
  --output-dir reports/negotiation_diagnostic
```

## 7. Run Historical Decision Probes

Historical probes ask your agent what it would do at states extracted from real GLEE logs.

```bash
python -m glee_eval probes \
  --agent my_agents.baseline:MyAgent \
  --data-dir data \
  --limit 1000 \
  --output-dir reports/my_agent_probes
```

This does not pretend the historical continuation is a counterfactual. It is a cheap decision-quality benchmark.

## 8. Run A Simulation Stress-Test Experiment

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
runs/my_agent_v1/audit/audit.md
runs/my_agent_v1/audit/support_index.json
runs/my_agent_v1/simulation/simulation_ledger.jsonl
runs/my_agent_v1/diagnostics/negotiation/negotiation_diagnostic.md
runs/my_agent_v1/search/<family>/elite_episodes.jsonl
runs/my_agent_v1/datasets/state_action_outcome.jsonl
runs/my_agent_v1/datasets/episode_summary.jsonl
runs/my_agent_v1/datasets/failure_cases.jsonl
runs/my_agent_v1/matches/match_ledger.md
runs/my_agent_v1/matches/match_ledger.csv
runs/my_agent_v1/matches/match_ledger.jsonl
runs/my_agent_v1/hypotheses/hypotheses.md
runs/my_agent_v1/shadow_score/shadow_score.md
```

Use `state_action_outcome.jsonl` for later analysis/training-data conversion. Use `hypotheses.md` as the first-pass research memo on where the agent seems weak.

Use `matches/match_ledger.md` as the running document for compiled match results. It summarizes all matches and lists the highest-regret rows up to `--match-report-limit` so very large runs do not create an unreadable document. The full match ledger is always available in `matches/match_ledger.csv` and `matches/match_ledger.jsonl`.

## 9. Run Synthetic Tournaments Only

Synthetic tournaments play full games against deterministic opponent archetypes.

Note: the standalone tournament command is still useful for a quick isolated simulator smoke test. The full `experiment` command is the audit-first path that tags simulation through the dispatcher.

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

## 10. Search For Failures Only

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

## 11. Refresh Historical Data

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
python -m glee_eval train-response-models --data-dir data --output-dir models/response_v0
python -m glee_eval calibrate-population --games 10000 --data-dir data --output-dir reports
```

## 12. Publishing Guidance

Do not commit:

- `work/`
- `data/processed/`
- `data/empirical/`
- `reports/`
- `models/`
- API keys or model-provider configs

The harness should be published as code that expects users to clone GLEE separately.
