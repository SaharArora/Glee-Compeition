# R3 — language observability and causal feasibility

Status: **killed for the frozen offline evaluator** (bounded feasibility check; no live
or payoff experiment run).

## Kill-check

The check perturbs only `free_text_message` while holding the complete numeric action,
structured stance, visible state, round/horizon, opponent specification, opponent seed,
and therefore its round-indexed RNG draw fixed. Fresh identical policies receive the two
states. `tests/test_r3_language_feasibility.py` exercises one receiver decision in each
family.

| Family | Text observable on the frozen payoff path? | Receiving-policy response | Verdict |
|---|---|---|---|
| Bargaining | No. `_run_bargaining` copies numeric/structured offer fields into the transcript but omits `AgentAction.message`. | Even when text is injected into a policy-visible state, `BargainingPolicy` reads only numeric offer fields and returns the identical action. | Causal-feasibility obstruction. |
| Negotiation | No. `_run_negotiation` likewise omits `AgentAction.message`. | Even under hypothetical delivery, `NegotiationPolicy` reads only numeric price/private values and returns the identical action. | Causal-feasibility obstruction. |
| Persuasion | Only at the candidate-buyer boundary does the runner expose seller text without its latent stance. At the candidate-seller/opponent-buyer boundary the event retains the structured stance. | `PersuasionPolicy` buyer reads `buy_no_buy` or `structured.decision`, never `free_text_message`; changing words with the stance fixed returns the identical action and RNG outcome. | Causal-feasibility obstruction for candidate language. |

The live adapters are capable of carrying bargaining/negotiation messages and persuasion
seller text, but delivery capability is not evidence that the remote receiver is
text-responsive. No frozen causal intervention on a text-responsive live opponent is
available in this worktree, and observational message/outcome associations would not
satisfy R3.

## Decisive next test

Before any language payoff gate, introduce or identify a frozen evaluator opponent whose
documented decision function consumes the delivered message. Run the same paired
text-only intervention through the *end-to-end transcript adapter* with numeric action,
structured stance, scenario, opponent draw, and named RNG streams byte-identical. The
minimum eligibility result is nonzero receiver-action divergence in each claimed family;
otherwise that family remains ineligible rather than receiving a zero-effect score.

