# R3 Wave 3 — frozen persuasion language treatment

Status: **implemented treatment candidate; causal payoff evaluation remains blocked.**

## Evaluable treatment population

The language policy is eligible only when all of the following are fixed before the
action:

- family is persuasion;
- the candidate role is seller;
- `seller_message_type == "text"`; and
- the shared economic core has already selected a `yes` or `no` recommendation.

Bargaining, negotiation, persuasion-buyer, and binary persuasion-seller cells return the
exact baseline action and message. The eligible population is therefore text-enabled
persuasion seller turns—not the current offline language-effect population. The shipped
offline buyer ignores candidate text, so causal payoff evaluation remains unidentified.

## Frozen mechanisms

The policy uses four transparent templates:

| Economic stance | Mechanism | Template ID |
| --- | --- | --- |
| `yes` | confident | `yes_confident_v1` |
| `yes` | social proof | `yes_social_proof_v1` |
| `no` | counter-interest credibility | `no_counter_interest_v1` |
| `no` | neutral control | `no_neutral_v1` |

The vocabulary was frozen from the training-only diagnostic feature surface in
`glee_eval/diagnostics/language.py` plus the preregistered counter-interest control; its
historical associations are explicitly **not causal claims**. No LLM, retrieval, hidden
quality inference, outcome, or future action is used.

The selected stance comes only from the already-completed economic action. A capability-
separated language RNG chooses between the two fixed templates for that stance. The policy
cannot access environment, opponent, e-process, or economic RNG capabilities. It replaces
only `raw_text`, `message`, and `structured.message`, and logs schema, eligibility,
mechanism, and template ID. Numeric action, acceptance, buy/recommendation stance, and all
economic metadata are unchanged.

## Remaining causal gap

This creates a genuine language-on agent, not a language effect estimate. The frozen
offline persuasion buyer consumes the structured stance rather than these words. A
numeric causal main effect still requires the user's later choice of a separately
validated text-responsive environment or authorized randomized live evaluation. No large
simulator project or rated game is authorized by this implementation.
