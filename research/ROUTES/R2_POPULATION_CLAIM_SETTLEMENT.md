# R2 population-claim settlement

Status: **settled as model-relative; the population-valid extension is killed.**

The implemented within-game persuasion-seller process has a valid likelihood-ratio/e-process
argument only under its stated predictable conditional null. Model C supplies the fixed numerical
reference used by that null. Neither the proof nor the training corpus establishes that the real
opponent's conditional follow probability is bounded by that fitted reference.

The bounded kill check verified the exact Model-C bytes (SHA256
`9daec869b3e4950945a1a370486e8841874fe9f5e611a7e8638dcdaa2b08b82c`) and inspected no
holdout or payoff outcome. It found 596 controller-eligible reference buckets among 1,197
persuasion buckets. Nevertheless, under arbitrary dependence any finite observed prefix remains
compatible with next-step conditional success probability one. The sharp distribution-free
upper bound is therefore one, which is fixed and predictable but useless for the implemented
likelihood ratio.

Optional stopping remains valid if the declared conditional null is true. It does not make that
premise true. The current treatment also controls neither selection across 596 possible signals
nor repeated testing across games. A nontrivial population claim would require a separately
justified conditional bound and a prospective multiplicity design.

The exact permitted label is:

> model-relative e-process against a fixed hash-locked Model-C reference

Evidence: `research/EVIDENCE/R2_POPULATION_BOUND_KILL_CHECK.json`. Tests:
`python3 -m unittest tests.test_r2_population_bound_kill_check -v` (`2/2` pass). No Model B,
payoff study, external call, or live/rated game was used.
