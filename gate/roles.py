# ============================================================================
# gate/roles.py       🔴 THE PARSER. Determines role from transcript context only.
# ============================================================================
"""Assigns a SemanticRole to a decoded transcript span, using only the words
that surround that span in the transcript. This module never sees a proposal,
an action name or a candidate value — see gate/witness.py's D1 red line for
why that separation is the point of the whole package."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, final

from .normalize import Decoded, canonicalize_token
from .transcript import TextExtractor, Word


class SemanticRole(Enum):
    MONEY_AMOUNT = "money_amount"
    CURRENCY = "currency"
    RECIPIENT = "recipient"
    STREET_NUMBER = "street_number"
    CLOCK_TIME = "clock_time"
    UNDETERMINED = "undetermined"   # 🔴 never a valid ParamSpec.required_role (lint L3)


# ---- the cue manifest (hand-authored English; see Bounded Residues R1) -----
STREET_CUES: Final[frozenset[str]] = frozenset(
    {"street", "st", "avenue", "ave", "road", "rd", "boulevard", "blvd",
     "drive", "lane", "way", "court", "crescent"}
)
TIME_RIGHT_CUES: Final[frozenset[str]] = frozenset(
    {"am", "pm", "oclock", "hours"}
)
CURRENCY_UNIT_CUES: Final[frozenset[str]] = frozenset(
    {"dollars", "dollar", "cents", "cent", "euros", "euro"}
)
RECIPIENT_LEFT_CUES: Final[frozenset[str]] = frozenset({"to", "for"})

ROLE_RULE_ORDER: Final[tuple[SemanticRole, ...]] = (
    SemanticRole.STREET_NUMBER,
    SemanticRole.CLOCK_TIME,
    SemanticRole.MONEY_AMOUNT,
    SemanticRole.CURRENCY,
    SemanticRole.RECIPIENT,
)
"""🔴 Evaluation order is part of the contract, not an implementation detail.
STREET_NUMBER precedes MONEY_AMOUNT: "i live at five hundred maple street" must
tag 500 as a street number even though "at" is also a time cue. TS-33 pins the
order; reordering these five entries must turn TS-2 red."""


@final
@dataclass(frozen=True, slots=True)
class _RoleInputs:
    """Everything a role rule is allowed to read, and nothing else. Private to
    this module: it is a parameter record, not an extension point.

    🔴 It carries no proposal, no action name and no candidate value — the same
    D1 red line gate/witness.py states, one level down.

    `left_adjacent` is the canonicalized text of the word IMMEDIATELY left of the
    span, or None when the span starts the transcript. It is deliberately NOT a
    window: R5' (v3) replaced "any token anywhere in left_window" with strict
    left adjacency, so there is no left window any more. `role_window` still
    governs `right_window` and only `right_window` — the asymmetry is intentional
    and is argued in the contract (A3): English prepositions abut their object,
    while the right side has fillers such as "two hundred canadian dollars"."""

    right_window: tuple[str, ...]
    left_adjacent: str | None
    decoded: Decoded
    span_start: int
    span_end: int
    core_tokens: frozenset[int]


_RoleRule = Callable[[_RoleInputs], bool]
"""A rule takes the _RoleInputs record — every window in it already
canonicalized — and answers whether ITS role applies. tag_role consults these
through ROLE_RULE_ORDER, so the order the rules run in is read from that tuple
at call time, not baked into a chain of if/elif statements: reordering
ROLE_RULE_ORDER changes runtime behaviour, which is what TS-33 depends on."""


def _rule_street_number(inputs: _RoleInputs) -> bool:
    # R1 STREET_NUMBER : any token of right_window in STREET_CUES
    #                    AND isinstance(decoded.value, int)          (v3, F3)
    # 🔴 The value-type guard is part of the RULE, not a nicety: without it
    # "my sister street" was tagged STREET_NUMBER on a str value (measured).
    return (
        any(token in STREET_CUES for token in inputs.right_window)
        and isinstance(inputs.decoded.value, int)
    )


def _rule_clock_time(inputs: _RoleInputs) -> bool:
    # R2 CLOCK_TIME : any token of right_window in TIME_RIGHT_CUES
    #                 AND isinstance(decoded.value, int)             (v3, F3)
    # 🔴 Same guard, same measured gap: "my sister pm" was tagged CLOCK_TIME.
    return (
        any(token in TIME_RIGHT_CUES for token in inputs.right_window)
        and isinstance(inputs.decoded.value, int)
    )


def _rule_money_amount(inputs: _RoleInputs) -> bool:
    # R3 MONEY_AMOUNT : any token of right_window in CURRENCY_UNIT_CUES
    #                   AND isinstance(decoded.value, int)
    return (
        any(token in CURRENCY_UNIT_CUES for token in inputs.right_window)
        and isinstance(inputs.decoded.value, int)
    )


def _rule_currency(inputs: _RoleInputs) -> bool:
    # R4 CURRENCY : decoded.decoder_id == "currency_spelling"
    return inputs.decoded.decoder_id == "currency_spelling"


def _rule_recipient(inputs: _RoleInputs) -> bool:
    # R5' RECIPIENT : ALL of --
    #   (i)   span_start > 0 and the canonicalized word immediately left of the
    #         span is in RECIPIENT_LEFT_CUES   (left-ADJACENT, not "in a window")
    #   (ii)  isinstance(decoded.value, str)
    #   (iii) the span shares no index with a number core token
    # 🔴 (iii) uses core tokens only, NOT connectives: "alice and bob" is still a
    # legal recipient, while "ana two" is not.
    return (
        inputs.left_adjacent is not None
        and inputs.left_adjacent in RECIPIENT_LEFT_CUES
        and isinstance(inputs.decoded.value, str)
        and not (set(range(inputs.span_start, inputs.span_end)) & inputs.core_tokens)
    )


_ROLE_RULES: Final[Mapping[SemanticRole, _RoleRule]] = MappingProxyType({
    SemanticRole.STREET_NUMBER: _rule_street_number,
    SemanticRole.CLOCK_TIME: _rule_clock_time,
    SemanticRole.MONEY_AMOUNT: _rule_money_amount,
    SemanticRole.CURRENCY: _rule_currency,
    SemanticRole.RECIPIENT: _rule_recipient,
})


def tag_role(
    words: Sequence[Word],
    span_start: int,
    span_end: int,
    decoded: Decoded,
    text_of: TextExtractor,
    role_window: int,
    core_tokens: frozenset[int],      # NEW: word indices whose token is a number core token
) -> SemanticRole:
    """Assign a semantic role to words[span_start:span_end].

    Pre : 0 <= span_start < span_end <= len(words); role_window >= 0.
    Pre : `core_tokens` holds every word index i for which
          is_number_core_token(canonicalize_token(text_of(words[i]))) is True.
          It is computed once per transcript at W1a in gate/witness.py, from the
          transcript ALONE — it is not a policy knob and not proposal-derived.
    Post: a member of SemanticRole. Returns UNDETERMINED when no rule fires --
          UNDETERMINED is fail-closed: it yields no witness.

    Rules, first match wins, in ROLE_RULE_ORDER:
      R1 STREET_NUMBER : any token of right_window in STREET_CUES
                         AND isinstance(decoded.value, int)
      R2 CLOCK_TIME    : any token of right_window in TIME_RIGHT_CUES
                         AND isinstance(decoded.value, int)
      R3 MONEY_AMOUNT  : any token of right_window in CURRENCY_UNIT_CUES
                         AND isinstance(decoded.value, int)
      R4 CURRENCY      : decoded.decoder_id == "currency_spelling"
      R5' RECIPIENT    : ALL of --
            (i)   span_start > 0 and canonicalize_token(text_of(words[span_start-1]))
                  in RECIPIENT_LEFT_CUES          # left-ADJACENT, replaces
                                                  # "anywhere in left_window"
            (ii)  isinstance(decoded.value, str)
            (iii) not (set(range(span_start, span_end)) & core_tokens)
    where right_window = canonicalized texts of words[span_end : span_end+role_window]
    ("canonicalized" here means canonicalize_token, the same single entry point.)

    🔴 ALL FOUR value-carrying roles now carry a value-type guard, and the guard
    is part of the rule rather than a matter of implementation taste. STREET_NUMBER
    / CLOCK_TIME / MONEY_AMOUNT are numeric roles; a `str` value may not occupy
    them. The change can only REMOVE witnesses -- fail-closed in both directions.

    🔴 THERE IS NO LEFT WINDOW ANY MORE. R5' reads exactly one word, the one
    immediately left of the span. `role_window` still governs R1/R2/R3, i.e. the
    RIGHT side only. The asymmetry is deliberate: English prepositions abut their
    object, whereas the right side carries fillers ("two hundred canadian
    dollars") at distance 2, so making the right side adjacent would break the
    published happy path.

    🔴 `role_window` is counted in WORDS, not in characters or milliseconds. That
    is the arithmetic B-24's fail-open sub-residual lives in: a formatting rewrite
    that merges or deletes tokens shortens the distance from a value span to its
    cue. Read B-24 before changing this.

    🔴 Parameter list contains no proposal, no action, no candidate value.
    """
    right_stop = min(len(words), span_end + role_window)
    right_window: tuple[str, ...] = tuple(
        canonicalize_token(text_of(word)) for word in words[span_end:right_stop]
    )
    left_adjacent: str | None = (
        canonicalize_token(text_of(words[span_start - 1])) if span_start > 0 else None
    )

    inputs = _RoleInputs(
        right_window=right_window,
        left_adjacent=left_adjacent,
        decoded=decoded,
        span_start=span_start,
        span_end=span_end,
        core_tokens=core_tokens,
    )

    for role in ROLE_RULE_ORDER:
        if _ROLE_RULES[role](inputs):
            return role
    return SemanticRole.UNDETERMINED
