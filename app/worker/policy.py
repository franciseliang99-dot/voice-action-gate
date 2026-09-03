"""Deployment policy for the demo application.

`gate/` has zero defaults, on purpose: a threshold written inside the library
would be quoted back as a measurement. So every knob below is typed here, by
the caller, with the reason it holds that value. Read this file as "what this
particular deployment decided", never as "what the gate recommends".

Nothing threshold-shaped is imported from `gate/`. Closed vocabularies
(`CheckId`, `STANDARD_CHECKERS`) are enumerated from the tables themselves, so
adding a check to the library cannot silently leave this registry uncovered.
"""

from __future__ import annotations

from types import MappingProxyType

from gate.checks import STANDARD_CHECKERS
from gate.decision import Gate
from gate.registry import (
    ActionRegistry,
    ActionSpec,
    CheckId,
    CheckRequirement,
    CheckStatus,
    ParamSpec,
    Reversibility,
    lint_deployment,
)
from gate.roles import SemanticRole
from gate.normalize import ValueKind
from gate.transcript import TranscriptProvenance, raw_text_of

# ---------------------------------------------------------------------------
# Knobs. Each one is a decision, and each decision states its own basis.
# ---------------------------------------------------------------------------

CONFIDENCE_FLOOR = 0.90
"""A PRODUCT CHOICE, not a measurement.

ARCHITECTURE V-2 measured a per-word confidence distribution on studio
broadcast audio; this demo runs on laptop microphones in noisy rooms, which is
a different domain, so that distribution does not license a number here. 0.90
is chosen because the failure it buys is the safe one: a word the recognizer is
unsure of stops being a witness, and an argument with no witness is BLOCKed.
Raising it blocks more; lowering it never fails closed on our behalf."""

MAX_SPAN_WORDS = 3
"""Longest word run that may be decoded into one value: "five hundred dollars"
is three. Wider windows manufacture witnesses out of adjacent unrelated words."""

ROLE_WINDOW = 2
"""How far from a role cue a span may sit and still inherit that role."""

MAX_TRANSCRIPT_WORDS = 400
"""A demo turn is seconds long. This is a denial-of-service bound, not a
linguistic one; over the bound the verdict is BLOCK, not a truncation."""

REQUIRE_KNOWN_PROVENANCE = True
"""🔴 Fail closed. The browser must declare the `format_turns` value it opened
the AssemblyAI connection with. If it does not, `formatting_enabled` is None
and every verdict is BLOCK. We refuse to infer it from `turn_is_formatted`:
gate/transcript.py records why that field's meaning is in dispute."""

EXTRACTOR_ID = "raw_text_of"
TEXT_FIELD = "text"

ACTION = "transfer"

PARAM_SHAPE: tuple[tuple[str, ValueKind, SemanticRole], ...] = (
    ("amount", ValueKind.NUMBER, SemanticRole.MONEY_AMOUNT),
    ("currency", ValueKind.CURRENCY_CODE, SemanticRole.CURRENCY),
    ("to", ValueKind.TEXT, SemanticRole.RECIPIENT),
)

_REQUIRED_RATIONALE = "irreversible money movement: every argument must be grounded"
_NOT_REQUIRED_RATIONALE = "no implementation in this deployment's checker table"


def _checks() -> dict[CheckId, CheckRequirement]:
    """Total coverage of the closed enum, derived mechanically.

    REQUIRED for every check that HAS an implementation; NOT_REQUIRED (with a
    rationale) for the rest. A hand-written literal would stop covering a check
    the day the library adds one -- and the lint would then reject this
    registry loudly, which is the good outcome, but only after a deploy.
    """
    out: dict[CheckId, CheckRequirement] = {}
    for cid in CheckId:
        if cid in STANDARD_CHECKERS:
            out[cid] = CheckRequirement(CheckStatus.REQUIRED, _REQUIRED_RATIONALE)
        else:
            out[cid] = CheckRequirement(CheckStatus.NOT_REQUIRED, _NOT_REQUIRED_RATIONALE)
    return out


def build_registry() -> ActionRegistry:
    params = {
        name: ParamSpec(
            name=name,
            value_kind=kind,
            required_role=role,
            checks=MappingProxyType(_checks()),
        )
        for name, kind, role in PARAM_SHAPE
    }
    spec = ActionSpec(
        name=ACTION,
        reversibility=Reversibility.IRREVERSIBLE,
        params=MappingProxyType(params),
    )
    return ActionRegistry(actions=MappingProxyType({ACTION: spec}))


def build_gate(*, formatting_enabled: bool | None) -> Gate:
    """One construction site. `formatting_enabled` is the ONLY per-request knob,
    because it is the only one that describes the request rather than the
    deployment; everything else is fixed above."""
    registry = build_registry()
    # Refuse to start if any IRREVERSIBLE action carries a NOT_IMPLEMENTED
    # check. A Gate that blocks loudly is a valid object; a deployment that
    # boots with an unimplemented check on a money transfer is not.
    lint_deployment(registry, STANDARD_CHECKERS)
    return Gate(
        registry=registry,
        checkers=STANDARD_CHECKERS,
        text_of=raw_text_of,
        provenance=TranscriptProvenance(TEXT_FIELD, formatting_enabled, EXTRACTOR_ID),
        confidence_floor=CONFIDENCE_FLOOR,
        max_span_words=MAX_SPAN_WORDS,
        role_window=ROLE_WINDOW,
        max_transcript_words=MAX_TRANSCRIPT_WORDS,
        require_known_provenance=REQUIRE_KNOWN_PROVENANCE,
    )
