# ============================================================================
# gate/transcript.py
# ============================================================================
"""Strict parsing of the word-level ASR transcript shape, plus the
TextExtractor seam (ARCHITECTURE V-1 / section 6.1) that decides which field
of a Word a caller reads as "the text"."""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias, final

from .errors import TranscriptFormatError

WORD_KEYS: Final[frozenset[str]] = frozenset(
    {"text", "start", "end", "confidence", "word_is_final"}
)


@final
@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: int          # milliseconds
    end: int            # milliseconds
    confidence: float   # domain [0.0, 1.0] -- these two bounds are the FIELD's domain,
                        # not a calibrated threshold. No threshold lives in this package.
    word_is_final: bool


def parse_word(raw: Mapping[str, object]) -> Word:
    """Strict parse of one streaming ASR word.

    Pre : `raw` is any mapping.
    Post: returns a Word, or raises. Never returns a partially-defaulted Word.
    Raises TranscriptFormatError when:
      - any key in WORD_KEYS is missing;
      - `text` is not str; `start`/`end` are not int (bool is rejected: `type(x) is bool`);
      - `word_is_final` is not exactly a bool;
      - `confidence` is not a float/int, is NaN, or lies outside [0.0, 1.0];
      - `end < start`.
    Extra keys are ignored (documented behaviour; they carry no meaning here).
    """
    missing = WORD_KEYS - set(raw)
    if missing:
        raise TranscriptFormatError(
            f"word is missing required key(s): {sorted(missing)}"
        )

    text = raw["text"]
    if not isinstance(text, str):
        raise TranscriptFormatError(
            f"word.text must be str, got {type(text).__name__}"
        )

    start = raw["start"]
    if type(start) is not int:
        raise TranscriptFormatError(
            f"word.start must be int (not bool), got {type(start).__name__}"
        )

    end = raw["end"]
    if type(end) is not int:
        raise TranscriptFormatError(
            f"word.end must be int (not bool), got {type(end).__name__}"
        )

    confidence = raw["confidence"]
    if not isinstance(confidence, (int, float)):
        raise TranscriptFormatError(
            f"word.confidence must be float or int, got {type(confidence).__name__}"
        )
    confidence = float(confidence)
    if math.isnan(confidence):
        raise TranscriptFormatError("word.confidence must not be NaN")
    if not (0.0 <= confidence <= 1.0):
        raise TranscriptFormatError(
            f"word.confidence out of domain [0.0, 1.0]: {confidence!r}"
        )

    word_is_final = raw["word_is_final"]
    if type(word_is_final) is not bool:
        raise TranscriptFormatError(
            f"word.word_is_final must be exactly bool, got {type(word_is_final).__name__}"
        )

    if end < start:
        raise TranscriptFormatError(f"word.end ({end}) < word.start ({start})")

    return Word(
        text=text, start=start, end=end, confidence=confidence,
        word_is_final=word_is_final,
    )


@final
@dataclass(frozen=True, slots=True)
class Transcript:
    words: tuple[Word, ...]


def parse_transcript(raw: Sequence[Mapping[str, object]]) -> Transcript:
    """Applies parse_word to every element, in order. Raises on the first bad word,
    with the element index in the message."""
    words: list[Word] = []
    for index, item in enumerate(raw):
        try:
            words.append(parse_word(item))
        except TranscriptFormatError as exc:
            raise TranscriptFormatError(f"word at index {index}: {exc}") from exc
    return Transcript(words=tuple(words))


TextExtractor: TypeAlias = Callable[[Word], str]
"""🔴 THE REPLACEABLE BOUNDARY (ARCHITECTURE V-1 / section 6.1).

The risk is CONFIRMED, not hypothetical: the official streaming documentation
carries a verbatim pair of examples in which, for the same `turn_order` and the
same audio, the formatted final's `words[].text` differs from the unformatted
final's -- `"my"` -> `"My"` and `"sonny"` -> `"Sonny."` -- while `start`, `end`
and `confidence` are byte-identical. Formatting rewrites the WORD, not only the
aggregate `transcript` string.

⚠ Honest label, copied forward rather than paraphrased: those quotations come
from a single documentation survey and were NOT independently re-verified against
the official page. Acting on them only demands STRONGER normalization, so
believing them cannot loosen this gate.

This package therefore never reads `word.text` directly outside this seam. The
caller must name which extractor it used and must describe its provenance; the
choice is recorded in Evidence so a later measurement can invalidate past
decisions instead of silently reinterpreting them."""


def raw_text_of(word: Word) -> str:
    """The one extractor shipped: returns `word.text` verbatim.

    It is NOT a claim that `word.text` is unformatted. It is the identity
    extractor; the claim, if any, lives in the TranscriptProvenance the caller
    pairs with it."""
    return word.text


@final
@dataclass(frozen=True, slots=True)
class TranscriptProvenance:
    field_name: str                  # which key of the ASR word the text came from
    formatting_enabled: bool | None  # None == UNKNOWN
    extractor_id: str                # stable id of the TextExtractor used
    """🔴 CONTRACT CONSTRAINT ON THE CALLER (ARCHITECTURE section 6.1, table row 4):

    `formatting_enabled` MUST be derived from the `format_turns` parameter the
    caller itself sent when opening the connection, or left as None. It MUST NOT
    be derived from the `turn_is_formatted` field on the Turn message.

    Reason, recorded as the conflict it is and not smoothed over: the official
    documentation states that under the Pro model `turn_is_formatted` "always
    matches `end_of_turn`", while our own probe measured the joint distribution
    `(end_of_turn=False, turn_is_formatted=True) x 24` and
    `(True, True) x 2`. Those two statements contradict each other on their face.
    We do not know which is wrong, and this unit does not need to know -- it needs
    only to refuse to build a safety-relevant field out of a field whose meaning
    is in dispute. `None` is the honest value; `require_known_provenance=True` is
    the switch for a caller that cannot establish it and would rather block."""
