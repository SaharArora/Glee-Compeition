# R3 language route decision memo

Status: **decision required; no route has been started.**

Version bound: commit `895ffee341cd4893373e32d5f8c1a5375549e0e6`.
This memo compares only four authorized choices: randomized live evaluation, a separately
validated text-responsive opponent environment, restriction to available text-responsive
persuasion cells, and observational/feasibility reporting.

## Evidence that constrains the decision

The current bounded test runs three text-only opponent perturbation pairs, one per family, with
numeric state, structured stance, opponent seed `104729`, and round-indexed RNG fixed. It finds
zero receiver-action divergences in three pairs.

There is one schema qualification to the existing R3 route: bargaining and negotiation candidate
messages are not necessarily absent from the receiver state. The offline runner retains the full
candidate `structured` dictionary, and the shipped candidate places its message at
`structured["message"]`. The string can therefore be present as a nested field even though the
runner does not copy `AgentAction.message` to top-level `free_text_message`. This changes the
delivery label from "not delivered" to "delivered in the structured payload" for that producer,
but it does not change causal feasibility:

- `BargainingPolicy` reads offer amounts and its fixed threshold, not either message field.
- `NegotiationPolicy` reads price and private values, not either message field.
- The candidate-seller persuasion event carries both its structured decision and message;
  `PersuasionPolicy` buyer reads `buy_no_buy` or `structured.decision` and ignores the words.
- At the candidate-buyer persuasion boundary, the runner removes the opponent seller's latent
  stance and exposes `free_text_message`. The candidate can optionally parse that text, but this
  is the opposite intervention direction: the opponent generated the text and the candidate
  consumed it. It is not a cell in which candidate-generated language changes a receiver.
- All three terminal payoff functions use numeric offers, decisions, qualities, and values only.
  None consumes message text.

Consequently, the current frozen offline evaluator has no verified path from candidate-generated
text to a text-responsive opponent or payoff evaluator. A delivered but ignored string is not a
language-responsive cell.

## Comparison

| Route | Causal validity | Circularity risk | Required data | Competition-game cost | Engineering cost | Family coverage | Supports a paper language main effect? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Randomized live evaluation** | Potentially high for a prospectively randomized live estimand, but only after verifying delivery and receiver consumption. Changing words while holding numeric action, stance, context, and RNG fixed is necessary. Existing observational live logs are not causal evidence. | Medium-high. Remote opponents and availability can change; selecting identities, cells, or messages after response inspection would be post-treatment selection. Pairing may be impossible if the same receiver state cannot be replayed. | Authorized randomized intervention records; exact outgoing and received text; numeric action/stance hashes; opponent identity and role; pre-treatment eligibility; terminal outcome; failure/missingness; named RNG substreams; a prospective power calculation. | **High and presently unbounded.** A defensible number depends on effect size, clustering, opponent turnover, and pairing. Existing games cannot substitute for randomized games. | High: authorization, randomizer, delivery receipts, immutable eligibility, failure capture, and causal analysis for a changing remote population. | Potentially bargaining, negotiation, and persuasion because adapters can carry messages, but responsiveness is unverified in every family. | **No for the frozen offline main effect.** It could support a separately preregistered live-population effect, not silently replace the frozen evaluator estimand. |
| **Separately validated text-responsive opponent environment** | High internal validity if the receiver's documented decision function consumes text, validation is independent of treatment development, and the environment is frozen before treatment outcomes. | **High unless strongly separated.** Building or selecting the receiver around the candidate's messages can manufacture responsiveness. Independent ownership, blinded validation, immutable holdouts, and no treatment-driven tuning are required. | Versioned environment and decision function; independent text-only perturbation certificate; frozen opponent/config holdouts; delivery/consumption traces; numeric/stance/RNG equality; payoff outputs. | **Zero rated competition games.** | Very high if built across families; medium only if a qualifying pre-existing environment can be identified and independently certified. This memo does not authorize that project. | One to three families depending on the pre-existing environment; all three would require separate receiver contracts and validation. | **Only for a newly declared environment estimand.** It does not by itself identify the effect in the current frozen evaluator and cannot be introduced after outcome inspection. |
| **Restrict to available text-responsive persuasion cells** | **Invalid/undefined for the stated treatment.** The only available responsive direction is opponent-seller text consumed by the candidate buyer. Candidate-seller text is received by a buyer policy that uses the fixed structured stance, not the words. | High. Reversing treatment ownership or selecting cells because they react would redefine the intervention and eligibility after seeing mechanics. | Current runner, candidate parser, and opponent-policy boundary are already sufficient: the candidate-generated/text-responsive intersection is empty. | Zero. | Low mechanically, but no eligible causal estimand results. | Persuasion only, with **zero currently eligible candidate-to-receiver cells**. | **No.** It would estimate a different intervention if opponent text were manipulated, and reporting zero over an empty/ineligible population is prohibited. |
| **Observational/feasibility only** | No causal effect estimate; high validity for the narrower claim that the frozen evaluator cannot identify the language effect. Message/outcome associations remain descriptive only. | Low if all exclusions and the empty eligible population are reported without outcome-selected exceptions. | Current source-bound delivery/consumption audit, the three fixed perturbation pairs, exact hashes, and any descriptive schema counts clearly labelled noncausal. | Zero. | Low. Preserve the verifier and document the limitation; do not build treatment generation or a new receiver. | All three families can receive a feasibility verdict; none supplies a current candidate-language causal cell. | **No numeric language main effect.** It supports the frozen study's permitted verifier-backed impossibility/limitation conclusion and prevents a text-blind zero from being presented as an effect. |

## Recommendation

Recommend **observational/feasibility only for the frozen study**.

This is the only option that preserves the frozen target and intervention without spending rated
games, reversing treatment direction, or creating a receiver whose responsiveness could be
circularly tailored to the treatment. The paper can state that the language main effect is not
identified in the frozen offline evaluator and report the version-bound delivery/consumption
obstruction. It must not report the three inert perturbations as a zero causal effect.

If a numeric causal language effect is mandatory, the least-confounded follow-on is a separately
validated **pre-existing** text-responsive environment, frozen and certified independently before
any treatment outcomes. That would be a new prospective estimand, not a repair applied to the
current result.

## Decision gate

No generation logic, opponent environment, live randomization, or observational effect model is
authorized by this memo. **Wait for an explicit user choice among the four routes before doing any
further R3 work.**

## Reproduction

Command:

```sh
python -m unittest -v tests.test_r3_language_feasibility
```

Result: `1` test passed, comprising `3` fixed text-only family perturbation pairs and `0/3`
receiver-action divergences. Test seed: fixed opponent seed `104729`; no competition games and no
sampled payoff evaluation.
