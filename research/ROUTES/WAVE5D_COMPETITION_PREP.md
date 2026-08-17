# Wave 5D Route 3 — competition preparation

Status: **offline route complete; two hypotheses nominated; neither implemented, gated, or
promoted.** This route did not alter Jordan, Factorial00, telemetry, an evaluator artifact, or a
production pin. It made no external call and queued no game.

## Evidence boundary

The only payoff rows read were the `900` outcomes already exposed and committed by the Wave 5B
shared-backbone diagnostic. Their byte identity is fixed at SHA-256
`66ffc4c3ebfdf80fec9cad677c92f5151074088c643e5fd75f9e350861959211`. Because their outcomes
were inspected before these hypotheses were written, they are now **development data for
mechanism generation only**. The underlying population, catalogue, Model C, support index and
untouched evaluation rows were not opened or rerun. Reusing the 900 rows cannot confirm either
hypothesis.

Source tracing is against these exact bytes:

- Jordan: `my_agents/jordan_strategic.py`, SHA-256
  `27526fc4801a856cbf0db4690a336f1f375a98fbe52256c3672935a3ea24fc82`;
- treatment-off core: `research/CANDIDATES/r1_treatment_off_baseline.py`, SHA-256
  `5e6e5daebef9df16c06ce2c4bdc3a3378b30241a4b23b08310f9447c051998a9`;
- forced agents: `research/CANDIDATES/wave3_factorial_agents.py`, SHA-256
  `f5b34b42c759391a0f68d188ce71e51cbc43a33e128dd73fcecbfebd8e6a8265`.

## Exact behavior trace

Factorial00 inherits Jordan's family rules but deletes heuristic `E_*` evidence and forces a
neutral `SAFE` control. It also disables ambient artifact discovery, requires hash-verified Model
C/support inputs, generates no shadow language, and attaches the economic core's own next price
to every negotiation rejection. The decision-level consequences are:

| Family / roles | Decision point | Jordan | Factorial00 |
| --- | --- | --- | --- |
| Bargaining / both | offer | Evidence may select `EXPLORE` or `EXPLOIT`, changing the theory-anchor branch and Model-C search cap. | Always `SAFE`; same beliefs/SPE surface. |
| Bargaining / both | response | `EXPLOIT` adds `.02` and `EXPLORE` adds `.01` to the continuation-value floor before clipping. | Adds neither increment. |
| Negotiation / buyer, seller | offer | May select `EXPLORE`, `COMMIT`, or `EXPLOIT` price formulas. | Always the `SAFE` price formula. |
| Negotiation / buyer, seller | response | Surplus capture floor is `.16` in `EXPLOIT`, `.18` in `COMMIT`, otherwise `.22`; default Jordan need not supply its own counter. | Uses `.22` and always supplies the core's next price on rejection. |
| Persuasion / seller | recommendation | High quality is `yes`; low quality can become `yes` only through late obedience-conditioned `EXPLOIT`; default text stays fixed while a shadow is recorded. | High quality is `yes`; low quality stays `no`; no shadow is recorded. |
| Persuasion / buyer | buy/pass | Visible-sample evidence lowers the safety margin from `.04` to `.02` once transcript length reaches 10. | Empty evidence leaves the margin at `.04`. |

This is a source-level trace, not a causal decomposition of terminal payoff. The Wave 5B ledger
contains terminal payoffs and subgroup labels but no action trajectories, so it cannot establish
which branch caused a difference. Artifact activation is also asymmetric in source: Jordan may
consult ambient variables, whereas Factorial00 rejects ambient state and requires exact hashes.

## Previously exposed payoff pattern

Factorial00 minus Jordan in the 900 paired rows was:

| Cell | n | Mean difference | F00 wins / losses / ties |
| --- | ---: | ---: | ---: |
| Bargaining player 1 | 168 | +.145426 | 149 / 19 / 0 |
| Bargaining player 2 | 132 | +.178444 | 76 / 13 / 43 |
| Negotiation buyer | 156 | +.004447 | 8 / 1 / 147 |
| Negotiation seller | 144 | +.013826 | 23 / 8 / 113 |
| Persuasion buyer | 163 | -.000061 | 0 / 1 / 162 |
| Persuasion seller | 137 | **-.057299** | 0 / 67 / 70 |

For persuasion seller, all 67 non-ties favor Jordan. Jordan's mean advantage is `.050714` over
70 myopic-labelled rows and `.064179` over 67 persistent-labelled rows. It is nonnegative for
Jordan in every recorded configuration regime and opponent-archetype slice, although many slices
are too small to interpret and this post-outcome slicing is descriptive only. The strongest
source-aligned explanation is the low-quality, late obedience-conditioned seller branch deleted
by forced `SAFE`; the ledger cannot prove that explanation.

## H1 — family-local neutral control

Status: `hypothesis_only_unimplemented`.

Exact delta: create a separate candidate subclass. For bargaining and negotiation only,
`_control` returns `SAFE`, empty evidence, unchanged beliefs and unchanged coverage. Persuasion
delegates unchanged to Jordan. Change no family rule, counteroffer path, artifact binding,
message path or default flag, and do not edit `MyAgent`.

Rationale: the legacy mode selector pays for exploration/screening without a causal
value-of-information certificate. Neutralizing it in the two development cells where the shared
core was better preserves the theory/reservation-value rules and keeps Jordan's persuasion seller
branch.

- Eligible cells: both bargaining and negotiation roles at offers and responses; persuasion must
  have exact action-byte parity.
- Failure modes: evaluator specificity/noise; useful live adaptation is lost; ambient artifacts
  differed; gains concentrate; negotiation counteroffer plumbing rather than control explains
  the observed difference.
- Allowed development data: exact exposed 900-row scenario ledger/replay and synthetic action
  fixtures only.
- Offline kill-check: persuasion byte parity; no affected family-role mean below `-.005`;
  bargaining mean at least `+.020`; overall mean at least `+.010`; no regime receives more than
  50% of absolute gains. Any failure kills this exact formulation. Passage remains development
  evidence.
- Untouched confirmation: prospectively freeze a structurally disjoint, non-Model-B set of
  1,600 paired games per affected family at seed `20260901`; apply the existing full promotion
  gate and family/role non-regression without changing thresholds.
- Future live promotion: only after the frozen Jordan canary is attributable and untouched
  confirmation passes, freeze a new v2 telemetry tuple. Require hostile-audit `PASS`, every
  family official-rating 95% LCB at least 2000, bargaining and negotiation 95% LCB for
  v2-minus-Jordan above zero, and persuasion noninferiority lower bound at least -100 rating
  points.

## H2 — memory-aware seller exploitation

Status: `hypothesis_only_unimplemented`.

Exact delta: in a separate candidate, expose `prior_yes_recommendations` and
`prior_buys_after_yes` from `_persuasion_beliefs`. Replace only the low-quality seller `EXPLOIT`
branch with a one-sided 90% Wilson lower bound on `P(buy|yes)`, requiring `n>=3`. For myopic
buyers require `LCB>=.50` and `remaining_fraction<=.50`; for persistent buyers require
`LCB>=.55`, no prior visible yes-on-low event, and `remaining_fraction<=.25`. High-quality
recommendations and both buyer policies remain byte-identical. Do not edit `MyAgent`.

Rationale: a sale has immediate value, while a revealed low-quality recommendation can destroy
personalized trust. That intertemporal cost differs between myopic and persistent receivers; a
sample-aware bound prevents the smoothed prior from masquerading as evidence.

- Eligible cells: persuasion seller, low quality, at least three prior yes recommendations,
  presplit by myopic/persistent receiver. Every other cell must be inert.
- Failure modes: counts are not legally visible in a platform schema; aggregate myopic statistics
  retain reputation cost; the persistent gate removes profitable terminal sales; eligible turns
  are too sparse; exposed evaluator-specific behavior drives the pattern.
- Allowed development data: exposed persuasion-seller payoff rows/regime labels and synthetic
  visible-history probes. Declined-product qualities may not be imputed.
- Offline kill-check: only eligible low-quality seller actions change; seller mean improvement
  over Jordan at least `+.005`; both memory groups nonnegative; no regime below `-.010`; gain
  concentration at most `.50`; zero private/illegal reads. Any failure kills the formulation.
- Untouched confirmation: prospectively freeze 1,600 structurally disjoint, non-Model-B
  persuasion games at seed `20260902`, seller primary, with myopic/persistent subgroups fixed;
  apply the full promotion gate and intent-to-treat missingness.
- Future live promotion: after untouched confirmation and a new telemetry audit, separately
  authorize 100 attributable persuasion terminals. Require official-rating 95% LCB at least
  2000, v2-minus-Jordan 95% LCB above zero, no integrity stop and no persistent subgroup
  regression.

## Verdict and next action

The two mechanisms are candidates for later implementation, not rescued/relabelled failures and
not evidence that Jordan v2 is better. The first competition research action tomorrow is to
implement **H1 only** in an isolated candidate and run its cheap action-surface/parity kill-check;
do not implement H2 unless H1 terminates and a new bounded route is authorized. The first
leaderboard action is still the separately authorized, frozen current-Jordan Wave 5C canary—not a
v2 candidate.

Machine-readable reconstruction is in
`research/EVIDENCE/WAVE5D_COMPETITION_PREP.json`.

