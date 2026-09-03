# ============================================================================
# gate/witness.py                     🔴 D1: THIS FILE CANNOT SEE THE PROPOSAL.
# ============================================================================
"""Builds the witness set: the set of (value, role) pairs the transcript --
and only the transcript -- actually supports. Nothing in this module reads a
Proposal, an action name or a candidate value; it does not import
gate.proposal at all (TS-36 pins that mechanically). A later module
(gate/decision.py, via gate/checks.py) asks *this* set whether a proposed
value is grounded. That ordering -- witnesses first, proposal second -- is
what keeps this a parser instead of a matcher (see Design Decisions, "Witness
typing", and TS-2/TS-3)."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, final

from .normalize import (
    NUMBER_CONNECTIVE_TOKENS,
    Normalization,
    ScalarValue,
    Undecodable,
    canonicalize_token,
    decode_span,
    is_number_core_token,
)
from .reasons import BlockReason
from .roles import SemanticRole, tag_role
from .transcript import TextExtractor, Transcript, Word


@final
@dataclass(frozen=True, slots=True)
class Span:
    start_index: int   # inclusive word index
    end_index: int     # exclusive word index
    start_ms: int
    end_ms: int
    text: str          # joined extracted text, diagnostics only


@final
@dataclass(frozen=True, slots=True)
class Witness:
    value: ScalarValue
    role: SemanticRole
    span: Span
    min_confidence: float
    decoder_id: str


class RejectCause(Enum):
    NOT_FINAL = "not_final"
    BELOW_CONFIDENCE_FLOOR = "below_confidence_floor"
    UNDECODABLE = "undecodable"
    ROLE_UNDETERMINED = "role_undetermined"
    SUBSUMED = "subsumed"          # NEW (W5a)


@final
@dataclass(frozen=True, slots=True)
class RejectedSpan:
    span: Span
    cause: RejectCause
    decoded_value: ScalarValue | None
    min_confidence: float


@final
@dataclass(frozen=True, slots=True)
class WitnessSet:
    witnesses: tuple[Witness, ...]
    rejected: tuple[RejectedSpan, ...]
    """🔴 `rejected` is DIAGNOSTIC ONLY. It carries decoded values for spans that
    were thrown out. Anything that reads `rejected` in order to SATISFY a
    requirement re-opens exactly the hole the confidence floor closes."""

    def satisfies(self, value: ScalarValue, role: SemanticRole) -> bool:
        """True iff some w in self.witnesses has w.value == value and w.role is role.
        🔴 Reads self.witnesses ONLY. Must not touch self.rejected."""
        return any(w.value == value and w.role is role for w in self.witnesses)

    def _any_value_match(self, value: ScalarValue) -> bool:
        """Value-only membership, role ignored. 🔴 THIS IS THE MATCHER. It exists
        solely so `explain` can distinguish ROLE_MISMATCH from NO_WITNESS.
        Referenced from exactly one place in this package: `explain`. TS-38 pins that."""
        return any(w.value == value for w in self.witnesses)

    def rejected_for_confidence(self, value: ScalarValue) -> bool:
        """True iff some r in self.rejected has r.decoded_value == value and
        r.cause is RejectCause.BELOW_CONFIDENCE_FLOOR. Return type is bool used
        only to ADD a block reason -- it can never grant a pass."""
        return any(
            r.decoded_value == value and r.cause is RejectCause.BELOW_CONFIDENCE_FLOOR
            for r in self.rejected
        )

    def explain(self, value: ScalarValue, role: SemanticRole) -> BlockReason:
        """Pre : self.satisfies(value, role) is False.
        Post: ROLE_MISMATCH if self._any_value_match(value) else NO_WITNESS.
        🔴 Return type is BlockReason. There is no expressible 'allow' return."""
        if self._any_value_match(value):
            return BlockReason.ROLE_MISMATCH
        return BlockReason.NO_WITNESS


_NUMBER_DECODER_IDS: Final[frozenset[str]] = frozenset({"digits", "number_words"})
"""The decoder ids W5a governs. Currency spellings and free text are NOT subject
to the token-run rule: they have no sub-span over-generation of the kind B-29
measured, and constraining them would silently narrow RECIPIENT / CURRENCY.

🔴 Read the sentence above LITERALLY -- "of the kind B-29 measured" -- and do NOT
read it as "free text does not over-generate sub-spans". Free text DOES
over-generate sub-spans. B-30 (recipient fragments) and B-31 (recipient prefix
truncation) are exactly that, and B-31 is a LIVE fail-open registered as
`deferred`, not a closed class: given `to alice and bob`, the spans `alice`,
`alice and` and `alice and bob` all witness as RECIPIENT. What the sentence above
claims is only that free-text over-generation is not of the kind W5a can address,
so it is handled elsewhere: R5' (left-adjacency plus core-token disjointness)
narrows the class, and the residue R5' cannot close is held only by the published
registry's deny-by-default ceiling, which lint_deployment checks. W5a does not
close it, and the absence of a currency/text entry in this set must not be cited
as evidence that it is closed."""


def _span_min_confidence(words: Sequence[Word]) -> float:
    return min(word.confidence for word in words)


def _build_span(
    words: Sequence[Word], start_index: int, end_index: int, text_of: TextExtractor
) -> Span:
    span_words = words[start_index:end_index]
    return Span(
        start_index=start_index,
        end_index=end_index,
        start_ms=span_words[0].start,
        end_ms=span_words[-1].end,
        text=" ".join(text_of(word) for word in span_words),
    )


def _is_number_token(token: str) -> bool:
    """A token that may appear ANYWHERE inside a number phrase: a core token or a
    connective. Runs are maximal over this predicate; they are then trimmed to
    begin and end with a CORE token, so a connective can never be a boundary."""
    return is_number_core_token(token) or token in NUMBER_CONNECTIVE_TOKENS


def _number_token_runs(tokens: Sequence[str]) -> frozenset[tuple[int, int]]:
    """W1a. The number token runs of `tokens`, as half-open (start, end) bounds.

    A run is a maximal contiguous block of `_is_number_token` tokens, trimmed at
    both ends so that it begins and ends with a core token. A block that trims
    away to nothing (a lone "and") contributes no run.

    🔴 O(len(tokens)). Each token is examined a constant number of times; there
    is no scan over spans and no scan over supersets of spans. B-2 is a real
    boundary: the transcript is attacker-influenced, so an O(k^2)-per-span
    implementation of this rule would manufacture a resource surface on the
    request path. See A4.

    🔴 Computed from `tokens` alone -- no proposal, no action name, no candidate
    value. D1 is unchanged by this function's existence."""
    runs: set[tuple[int, int]] = set()
    index = 0
    length = len(tokens)

    while index < length:
        if not _is_number_token(tokens[index]):
            index += 1
            continue

        start = index
        while index < length and _is_number_token(tokens[index]):
            index += 1
        end = index

        while start < end and not is_number_core_token(tokens[start]):
            start += 1
        while end > start and not is_number_core_token(tokens[end - 1]):
            end -= 1

        if start < end:
            runs.add((start, end))

    return frozenset(runs)


def _number_core_indices(tokens: Sequence[str]) -> frozenset[int]:
    """W1a. The word indices whose canonicalized token is a number core token.
    Read-only downstream; handed to tag_role so R5' can require that a recipient
    span be disjoint from the numbers the speaker uttered."""
    return frozenset(
        index for index in range(len(tokens)) if is_number_core_token(tokens[index])
    )


def generate_witnesses(
    transcript: Transcript,
    *,
    text_of: TextExtractor,
    confidence_floor: float,
    max_span_words: int,
    role_window: int,
) -> WitnessSet:
    """🔴 D1 RED LINE. This signature contains no proposal, no action name and no
    candidate value, and this module imports nothing from gate.proposal.
    It is a function of the transcript and policy alone. TS-36 pins that
    mechanically; TS-2 pins it behaviourally.
    🔴 THE SIGNATURE IS UNCHANGED BY THE v2 AND v3 REVISIONS. v3 added W1a and
    W5a to the BODY; the parameter list is byte-identical, which is exactly why
    TS-36 stays green (A19 item 6). W1a's products -- the run bounds and the
    core-token index set -- are internal quantities, NOT new policy knobs, and
    they are not reachable from outside this function.

    Pre : max_span_words >= 1; role_window >= 0; 0.0 <= confidence_floor <= 1.0.
    Post: every Span in the result satisfies end_index - start_index <= max_span_words;
          witnesses and rejected together account for every enumerated span exactly once.

    Steps, in this order (the order is contractual -- see boundary B-12):
      W1  tokens[i] = canonicalize_token(text_of(words[i])) for every word     [unchanged]
          🔴 This is where confirmed formatting rewrites (capitalization, appended
          trailing punctuation) are absorbed. It runs before decode_span sees
          anything. See ARCHITECTURE section 6.1 and B-23.
      W1a runs = the number token runs of `tokens` (maximal contiguous runs over
          NUMBER_CORE_TOKENS | NUMBER_CONNECTIVE_TOKENS | digit runs, trimmed to
          begin and end with a core token). run_bounds = {(i,j) for each run}.
          core_tokens = frozenset(i for i in range(len(tokens))
                                  if is_number_core_token(tokens[i]))
          🔴 Computed from `tokens` alone. No proposal, no action name, no
          candidate value. D1 RED LINE unchanged. This is the only cross-span
          state in the function and it is read-only thereafter.
      W2  enumerate every span (i, j) with 1 <= j-i <= max_span_words          [unchanged]
      W3  NOT_FINAL                                                            [unchanged]
      W4  decoded = decode_span(tokens[i:j]); UNDECODABLE                      [unchanged]
      W5  min_conf gate -> BELOW_CONFIDENCE_FLOOR                              [unchanged]
      W5a if decoded.decoder_id in {"digits","number_words"} and (i,j) not in run_bounds
             -> RejectedSpan(cause=SUBSUMED, decoded_value=decoded.value)
          🔴 W5a runs AFTER W5 on purpose: a span that already failed W3/W4/W5
          keeps its original cause, so every existing rejected-cause assertion
          (TS-4, TS-7, TS-9, TS-23) is untouched and `rejected_for_confidence`
          is unaffected.
      W6  role = tag_role(words, i, j, decoded, text_of, role_window, core_tokens)
          if UNDETERMINED -> RejectedSpan(ROLE_UNDETERMINED) else -> Witness(...)

    🔴 WHY W5a RATHER THAN A NAIVE MAXIMAL-SPAN RULE (the naive one was explicitly
    rejected): decode_span falls through to canonicalize_text, which accepts ANY
    ordinary lowercase alphanumeric span, so the longest DECODABLE span containing
    a number is almost always a TEXT span. Maximality across decoders would
    therefore suppress the MONEY witness and keep the text one. W5a is computed at
    the TOKEN layer and is INDEPENDENT of `max_span_words`: the policy knob can
    only make the gate refuse more, never admit more. A security rule that is a
    function of a policy knob is not a rule (B-29).

    🔴 Complexity: W1a is O(n), W5a is a frozenset lookup per span, so the total
    remains O(n*k). Never implement W5a by scanning a span's supersets."""
    words: tuple[Word, ...] = transcript.words
    tokens: tuple[str, ...] = tuple(canonicalize_token(text_of(word)) for word in words)  # W1

    run_bounds: frozenset[tuple[int, int]] = _number_token_runs(tokens)       # W1a
    core_tokens: frozenset[int] = _number_core_indices(tokens)                # W1a

    witnesses: list[Witness] = []
    rejected: list[RejectedSpan] = []

    word_count = len(words)
    for start_index in range(word_count):                                    # W2
        last_end = min(word_count, start_index + max_span_words)
        for end_index in range(start_index + 1, last_end + 1):
            span_words = words[start_index:end_index]
            span: Span = _build_span(words, start_index, end_index, text_of)
            min_conf: float = _span_min_confidence(span_words)

            if any(word.word_is_final is not True for word in span_words):    # W3
                rejected.append(RejectedSpan(
                    span=span,
                    cause=RejectCause.NOT_FINAL,
                    decoded_value=None,
                    min_confidence=min_conf,
                ))
                continue

            decoded: Normalization = decode_span(tokens[start_index:end_index])  # W4
            if isinstance(decoded, Undecodable):
                rejected.append(RejectedSpan(
                    span=span,
                    cause=RejectCause.UNDECODABLE,
                    decoded_value=None,
                    min_confidence=min_conf,
                ))
                continue

            if min_conf < confidence_floor:                                  # W5
                rejected.append(RejectedSpan(
                    span=span,
                    cause=RejectCause.BELOW_CONFIDENCE_FLOOR,
                    decoded_value=decoded.value,
                    min_confidence=min_conf,
                ))
                continue

            if (                                                             # W5a
                decoded.decoder_id in _NUMBER_DECODER_IDS
                and (start_index, end_index) not in run_bounds
            ):
                rejected.append(RejectedSpan(
                    span=span,
                    cause=RejectCause.SUBSUMED,
                    decoded_value=decoded.value,
                    min_confidence=min_conf,
                ))
                continue

            role: SemanticRole = tag_role(
                words, start_index, end_index, decoded, text_of, role_window, core_tokens
            )                                                                 # W6
            if role is SemanticRole.UNDETERMINED:
                rejected.append(RejectedSpan(
                    span=span,
                    cause=RejectCause.ROLE_UNDETERMINED,
                    decoded_value=decoded.value,
                    min_confidence=min_conf,
                ))
                continue

            witnesses.append(Witness(
                value=decoded.value,
                role=role,
                span=span,
                min_confidence=min_conf,
                decoder_id=decoded.decoder_id,
            ))

    return WitnessSet(witnesses=tuple(witnesses), rejected=tuple(rejected))
