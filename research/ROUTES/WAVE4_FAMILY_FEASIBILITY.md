# Wave 4 family expansion feasibility — training-only kill checks

Status: **complete; no treatment expansion selected.**

This is a schema/mechanism census, not an outcome study. It streamed only the frozen historical
event source (SHA256 `afc50fdf2f9c08feaf86355494db2bbd257c29ff4f9fbc8ed65f15e005329ad6`),
read no held-out factorial payoff, made no external call, and ran no live/rated game.

The source contains 33,739 bargaining, 33,627 negotiation, and 13,506 persuasion games. Relevant
action support is large: bargaining has 92,823 offers and 92,823 decision callbacks; negotiation
has 96,214 offers and 96,214 decision callbacks; persuasion has 270,120 buyer decisions. Message
presence is also nonempty, but presence is not responsiveness: bargaining offer messages total
45,753, negotiation offer messages 48,249, and persuasion seller message/recommendation text
139,818.

| Family / treatment | Observable sequential evidence or text | Legally visible information | Hypothesized action mechanism | Formal/environment requirement | Training support | Decisive result |
| --- | --- | --- | --- | --- | ---: | --- |
| Bargaining / e-process | Prior opponent offers and rejection callbacks; terminal acceptance is absent before another candidate callback. | Candidate-visible prior transcript, own/visible deltas, round/horizon, public configuration. | Detect excess resistance/concession and alter acceptance or next share. | A predictable e-factor for a bounded binary/continuous variable under a justified conditional null, plus a censor-safe terminal observer. The current Bernoulli obedience factor cannot be reused for continuous shares. | 92,823 offers; 92,823 decision callbacks; 33,614 historical accepts, but accepts terminate the path. | **Unsupported.** Callback-only online evidence is rejection-selected; no accepted continuous conditional density/null exists. |
| Negotiation / e-process | Prior prices, rejections, and outside-option actions; accepted offer terminates before another candidate callback. | Candidate-visible prices, own value, disclosed counterpart value only when complete information, outside options, round/horizon. | Detect excess opponent concession or acceptance and change counter/acceptance. | A role-oriented bounded/continuous e-process in normalized own-surplus units and censor-safe terminal response. Hidden counterpart values may not be imputed. | 96,214 offers; 96,214 decisions; at least 11,168 accepts, plus outside-option categories. | **Unsupported.** Same terminal censoring and no valid continuous e-factor; do not coerce prices into the persuasion Bernoulli process. |
| Persuasion / e-process | Completed prior-round buyer follow/nonfollow after the candidate seller's recommendation. | Public p/v/c/config, seller-visible quality only when informed, prior completed recommendations and buyer decisions. | After a threshold crossing, change a baseline `no` recommendation to `yes`. | Fixed predictable reference and within-game filtration. Population validity additionally requires a real conditional upper bound; Model C supplies only a fitted reference. | 270,120 buyer decisions; 596 controller-eligible Model-C buckets. | **Supported only as the implemented model-relative persuasion-seller treatment.** Persuasion-buyer is a self-outcome and remains unsupported. |
| Bargaining / language | Candidate offer/decision messages can be delivered in structured payloads. | Public/visible bargaining state and already-fixed numeric offer/decision only. | Wording changes opponent acceptance or counteroffer. | A receiver whose decision function demonstrably consumes the words under text-only perturbation. | 45,753 offer messages plus 3,859 decision messages. | **Unsupported in the frozen offline environment.** `BargainingPolicy` ignores message text; observational message/outcome correlation is insufficient. |
| Negotiation / language | Candidate offer/decision messages are present on many historical turns. | Public/visible negotiation state and already-fixed price/decision only. | Wording changes opponent accept/counter/outside-option action. | Separately validated text-responsive receiver; numeric price/stance and RNG fixed. | 48,249 offer messages plus 1,573 decision messages. | **Unsupported in the frozen offline environment.** `NegotiationPolicy` ignores message text. |
| Persuasion / language | Candidate-seller text is delivered with a fixed yes/no stance; candidate buyer may consume opponent-seller text, which is the wrong intervention direction. | Candidate seller may use only visible quality/config and completed economic stance; no hidden/future fields. | Wording changes buyer purchase conditional on unchanged stance. | A buyer receiver that consumes candidate words. Current buyer consumes structured stance only. | 139,818 seller message/recommendation rows with text. | **Implemented template treatment, but payoff-unsupported in the current environment.** Primary recommendation is a separately selected controlled frozen text-responsive receiver. |

## Conclusion

No bargaining or negotiation expansion survives the bounded kill checks. The evidence process is
honestly persuasion-seller-specific under the current callback/likelihood contract. Language has
historical text in all three families but no candidate-to-responsive-receiver path in the frozen
offline environment. Any later expansion requires a new preregistration version before code and
cannot use held-out or payoff outcomes to select its mechanism.

