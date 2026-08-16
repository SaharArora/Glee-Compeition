# Wave 4 estimand freeze — revision 2

Status: **frozen before any treatment-payoff study; language environment pending user selection.**

This user-authorized revision changes the headline ordering from the broad revision-1 aggregate
because the implemented treatments are structurally sparse. It does not change the four payoff
arms or their row-level contrast formulas.

For every paired scenario, let `Y(e,l)` be normalized candidate payoff and define:

- `E = .5[(Y(1,0)-Y(0,0)) + (Y(1,1)-Y(0,1))]`;
- `L = .5[(Y(0,1)-Y(0,0)) + (Y(1,1)-Y(1,0))]`; and
- `I = Y(1,1)-Y(1,0)-Y(0,1)+Y(0,0)`.

Eligibility is an immutable scenario/artifact label computed before any arm action or outcome.
The report schema requires exact booleans for e-process, language, their conjunction, and the two
treatment-specific negative controls. Outcome reach, crossing, purchase, agreement, or observed
receiver response may be diagnostics but may not define membership.

## Headline estimands

1. **Primary e-process estimand:** equal-family-weighted mean `E` over structurally eligible
   scenarios. Under the current implementation this is persuasion candidate-seller, horizon at
   least two, and a frozen public configuration for which the hash-locked Model-C artifact has at
   least one non-global supported prior-round follow reference that could be observed before a
   later seller action. Crossing is not an eligibility condition. Bargaining, negotiation, and
   persuasion-buyer are excluded from this primary and are negative controls.
2. **Primary language estimand:** equal-family-weighted mean `L` over pre-treatment cells in the
   user-selected environment whose contract delivers candidate text to a receiver proven to
   consume text while numeric stance/action is held fixed. In the current text-blind offline
   environment this population is empty and the estimand is **nonreportable**, not zero.
3. **Primary interaction:** equal-family-weighted mean `I` on the conjunction of the two immutable
   eligibility labels. Until a text-responsive environment is selected, this is nonreportable.
4. **Secondary aggregate:** `E`, `L`, and `I` across all 3,600 paired scenarios, weighting the
   bargaining, negotiation, and persuasion family means equally. This is always secondary and
   may not headline a treatment whose eligible population is sparse.

## Negative controls and mandatory cells

- E-process negative control: `E` on every scenario not structurally e-process eligible; action
  and message bytes must match the corresponding e-process-off path absent a genuine mediated
  eligible update.
- Language negative control: `L` on every scenario lacking a certified candidate-text-responsive
  receiver; current frozen offline B/N/P cells belong here and must be byte-identical after
  treatment rendering fields are removed.
- Interaction negative control: `I` where either treatment is ineligible.
- Every family and candidate role is reported. Configuration summaries are mandatory even when
  a cell is explicitly underpowered/nonreportable; missing cells are never pooled away.

## Inference and multiplicity

The paired scenario is the inference unit. A report computes each family mean, averages the
nonempty structurally eligible family means equally, and estimates variance from the paired row
contrasts within family. The frozen report uses two-sided normal intervals from those paired
scenario contrasts at 95%. The three headline hypotheses above use Holm step-down control at
family-wise alpha `.05`; effect sizes and unadjusted intervals remain visible. Improvement
requires the Holm-adjusted interval strictly above zero. Harm requires it strictly below zero;
everything else is nonconfirming.

No sequential evaluation-level e-process replaces this fixed-sample analysis. The implemented
acting e-process is a treatment, not the study's hypothesis-testing method.

