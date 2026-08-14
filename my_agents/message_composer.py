"""Composes persuasion seller messages from the step-3 evidence, in shadow by default.

Step 3 measured which message features move real buyer purchase rates, holding the
realized quality, the stance of the message and the seller's model identity fixed
(138,009 real text-mode decisions). Only features whose sign held on *both*
high- and low-quality rounds are built on here -- a feature that helps only on
low-quality items is the seller's private intent showing through, not language:

    feature        effect    high-q    low-q    used?
    hedged         -0.113    -0.224    -0.069   yes, avoided
    social_proof   +0.064    +0.035    +0.106   yes, added
    confident      +0.028    +0.016    +0.052   yes, added
    long_message   -0.046    -0.086    -0.009   yes, kept short
    gain_frame     -0.043    -0.079    +0.008   NO -- sign flips
    discloses_value +0.022   -0.006    +0.053   NO -- sign flips
    asks_question  +0.019    -0.011    +0.054   NO -- sign flips

The composer runs in **shadow mode** by default: it decides what it would send and
records that, while the message actually transmitted stays the existing fixed
template. This exists because the promotion gate cannot run on message text --
nothing in our simulator reads messages, so an in-simulator A/B of a language
change would measure exactly nothing (verified: swapping every template for "."
changes persuasion payoff by 0.000000). Building a message-consuming opponent
calibrated on these same numbers and then A/B-ing against it would be circular.

So the evidence for promotion has to come from real logged games. Shadow mode is
how those accumulate without risking rated games on an ungated change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Real messages have a median length of 253 characters, and longer ones do worse.
# These sit well under that.
_MAX_SHADOW_MESSAGE_CHARS = 220


@dataclass(frozen=True)
class ComposedMessage:
    text: str
    features: dict[str, int]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "features": self.features, "rationale": self.rationale}


class PersuasionMessageComposer:
    """Builds a seller message from the features that survived step 3's controls.

    Deliberately template-based rather than generative: the point is to vary the
    three measured features and nothing else, so that if a real-data A/B ever shows
    a difference, the difference is attributable.
    """

    # Wording is chosen so the message carries *exactly* the features step 3
    # supports and none of the three that flip sign with realized quality. Three
    # drafts failed that check and were rewritten: "worth buying" tripped
    # `discloses_value`, "advise against" matched no discouragement pattern at all
    # so the decline read as neutral, and a bare count carried no social proof.
    # `test_message_composer.py` asserts the feature vectors so a future reword
    # cannot silently reintroduce one.

    #: Social proof: the largest positive, and twice as strong against a buyer with
    #: no history of their own (+0.108 vs +0.052).
    _SOCIAL_PROOF = "Other buyers who took my recommendation have been satisfied."
    #: Confidence, without asserting anything about this unit's quality.
    _CONFIDENT_ENDORSE = "I am confident you should buy this one."
    _CONFIDENT_DECLINE = "I am confident you should pass on this one."
    #: The existing behaviour, kept so shadow mode has something to compare against.
    _BASELINE_ENDORSE = "I recommend buying this product."
    _BASELINE_DECLINE = "I recommend passing on this product."

    def __init__(self, *, use_social_proof: bool = True, use_confidence: bool = True):
        self.use_social_proof = use_social_proof
        self.use_confidence = use_confidence

    def baseline(self, recommend: bool) -> str:
        return self._BASELINE_ENDORSE if recommend else self._BASELINE_DECLINE

    def compose(self, recommend: bool, *, market_sold: int = 0, market_high_quality: int = 0) -> ComposedMessage:
        """Compose the candidate message for a recommend / decline decision.

        Social proof is only claimed when there is something true to claim: if the
        agent has no sales behind it, asserting that buyers were satisfied would be
        a fabrication rather than a framing choice.
        """

        parts: list[str] = []
        used_confidence = False
        used_social_proof = False

        if self.use_confidence:
            parts.append(self._CONFIDENT_ENDORSE if recommend else self._CONFIDENT_DECLINE)
            used_confidence = True
        else:
            parts.append(self.baseline(recommend))

        if self.use_social_proof and recommend and market_sold > 0:
            if market_high_quality > 0:
                parts.append(
                    f"Of the {market_sold} products other buyers took, {market_high_quality} were high quality."
                )
            else:
                parts.append(self._SOCIAL_PROOF)
            used_social_proof = True

        text = " ".join(parts)[:_MAX_SHADOW_MESSAGE_CHARS]
        rationale_bits = []
        if used_confidence:
            rationale_bits.append("confident (+0.028)")
        if used_social_proof:
            rationale_bits.append("social_proof (+0.064)")
        rationale_bits.append("no hedging (-0.113 avoided)")
        rationale_bits.append(f"short ({len(text)} chars, -0.046 avoided)")

        from glee_eval.diagnostics.language import message_features

        return ComposedMessage(text=text, features=message_features(text), rationale="; ".join(rationale_bits))


def shadow_record(
    composer: PersuasionMessageComposer,
    recommend: bool,
    *,
    market_sold: int = 0,
    market_high_quality: int = 0,
) -> dict[str, Any]:
    """What the composer would have sent, alongside what is actually sent.

    Both messages carry their feature vectors so a later analysis can compare the
    two arms on the same footing as the step-3 measurement.
    """

    from glee_eval.diagnostics.language import message_features

    candidate = composer.compose(recommend, market_sold=market_sold, market_high_quality=market_high_quality)
    baseline_text = composer.baseline(recommend)
    return {
        "mode": "shadow",
        "gate_status": "not_gate_passed_pending_real_data",
        "sent": {"text": baseline_text, "features": message_features(baseline_text)},
        "would_send": candidate.to_dict(),
        "evidence": "step 3: hedged -0.113, social_proof +0.064, confident +0.028 (real data, controlled)",
    }
