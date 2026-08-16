# Wave 5A pre-outcome manifest designs

Status: **infrastructure implemented; exact 3,600-row factorization deliberately unselected.**

No scenario outcomes were generated. Both independent production authorization pins remain
`None`: `factorial_report.AUTHORIZED_PRODUCTION_CONTRACT_SHA256` and
`preoutcome_manifest.AUTHORIZED_PREOUTCOME_MANIFEST_CONTRACT_SHA256`.
`glee_eval/experiments/preoutcome_manifest.py` can build and reconstruct synthetic manifests, but
labels them `infrastructure_only_non_evidence`; production validation fails closed.

## Frozen quantities shared by every valid design

Every design has exactly 3,600 paired scenarios, 1,200 per family and 600 per candidate role.
All four forced arms reuse each scenario. The manifest binds full scenario/configuration bytes,
pre-treatment eligibility, public state and horizon, receiver/report/artifact/dependency hashes,
all seven named streams, the four entrypoints, e-process version/threshold, language policy,
retry/failure and intent-to-treat missingness rules, revision-2 estimands, and the Holm family.
The contract also binds an exact root of the complete scenario/configuration payloads, contiguous
within-family indices and evaluator-derived scenario seeds, the canonical Model-C payload, and
the scenario-to-support-mask mapping; coherent replacement of a same-count scenario set or an
invented scenario-stream hash is therefore rejected even if the manifest is rehashed.

No design may use treatment reach, action, receiver output, terminal state, or payoff to select a
row. Receiver timeouts, refusals, missing results, and malformed outputs remain assigned rows and
are labelled rather than excluded.

## Candidate factorizations

These are planning designs, not frozen manifests.

### Design A — 300 base strata × two roles × two receiver replicates

For each family, select 300 configuration/opponent base strata prospectively from the frozen
non-Model-B structural-holdout inputs. Cross each with both candidate roles and two independently
named receiver/environment replicates: `300 × 2 × 2 = 1,200`.

- Strength: transparent role balance and direct receiver-replicate robustness.
- Limitation: only 300 distinct economic strata per family; inference must cluster the two
  replicates by base stratum.

### Design B — 600 base strata × two roles

For each family, select 600 unique configuration/opponent/seed strata and assign both candidate
roles: `600 × 2 = 1,200`. Each row gets one frozen receiver seed.

- Strength: maximum economic-scenario breadth and simplest paired inference.
- Limitation: receiver stochasticity is represented only across rows, not replicated within an
  identical economic state.

### Design C — 200 base strata × two roles × three receiver replicates

For each family, select 200 base strata and cross both roles with three named receiver replicates:
`200 × 2 × 3 = 1,200`.

- Strength: strongest direct estimate of receiver stochasticity and failure variance.
- Limitation: least configuration/opponent breadth and stronger clustering; likely inefficient if
  the selected receiver is nearly deterministic.

## Decision required

After the user selects an exact receiver model/version, choose the breadth-versus-replication
tradeoff above. The recommended default is **Design A**: two receiver replicates provide a direct
stability check without collapsing economic coverage to Design C's 200 strata. If a local,
byte-deterministic receiver is selected, Design B becomes preferable because duplicate receiver
replicates add little information.

The selection must precede receiver capability outcomes and any treatment payoff. It must also
freeze:

1. the exact non-Model-B config catalogue and opponent-population bytes;
2. deterministic stratum ordering/sampling;
3. receiver model/version, prompts, decoding and cache contract;
4. retry/cost caps and intent-to-treat failure treatment;
5. the complete row-root hash; and
6. the corresponding authorized report-contract hash.

Only then may both authorization pins change from `None`, each to its separately reconstructed
contract hash, followed by a fresh independent hostile audit. The report-contract pin does not
substitute for the exact pre-outcome scenario-root pin. Wave 5A does not perform either
activation.
