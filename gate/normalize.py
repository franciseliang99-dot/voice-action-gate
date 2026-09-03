# ============================================================================
# gate/normalize.py                    🔴 PARTIAL. NO FALLBACK RETURN. EVER.
# ============================================================================
"""Normalization and decoding, on both sides of the gate.

Every decoder in this module is a partial function: it either returns a
`Decoded` value or the singleton `VALUE_UNDECODABLE`. There is no third
option, and no decoder ever guesses. `canonicalize_token` is the one
normalization entry point both the transcript side (W1, in witness.py) and
the proposal side (`decode_argument`, below) go through before any decoder
sees a token."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import ClassVar, Final, NoReturn, TypeAlias, final

__all__ = [
    "ValueKind",
    "Undecodable",
    "VALUE_UNDECODABLE",
    "ScalarValue",
    "Decoded",
    "Normalization",
    "NUMBER_WORD_MIN",
    "NUMBER_WORD_MAX",
    "CANONICAL_ALPHABET",
    "STRIPPABLE_PUNCTUATION",
    "CURRENCY_CODES",
    "CURRENCY_SPELLINGS",
    "NUMBER_CORE_TOKENS",
    "NUMBER_CONNECTIVE_TOKENS",
    "canonicalize_token",
    "is_number_core_token",
    "decode_number_span",
    "decode_currency_span",
    "canonicalize_text",
    "decode_span",
    "decode_argument",
]
# 🔴 This list is the module's FULL public surface, not a subset. It exists
# because v3 (A19 item 2) requires the three new number-token names to be
# exported; enumerating everything else alongside them keeps the list from
# silently narrowing the surface that gate/witness.py and gate/decision.py
# already import by name. The private grammar tables (`_ONES_0_19`, `_TENS`,
# `_HUNDRED`, `_THOUSAND`, `_AND`) are deliberately absent: TS-32's renderer
# must write standard English cardinals independently, never import ours.


class ValueKind(Enum):
    """Declared by the registry per parameter. Decoding an argument requires it,
    so decoding never has to guess which reading was intended."""
    NUMBER = "number"
    CURRENCY_CODE = "currency_code"
    TEXT = "text"


@final
class Undecodable:
    """The 'I could not read this' value. Singleton.

    🔴 __bool__ raises on purpose. `if decoded:` is the exact shape by which a
    partial function silently degrades into a total one; here it is a loud crash
    instead of a quiet pass. Branch with `isinstance(x, Undecodable)`."""
    __slots__ = ()
    _instance: ClassVar["Undecodable | None"] = None

    def __new__(cls) -> "Undecodable":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "VALUE_UNDECODABLE"

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "VALUE_UNDECODABLE has no truth value -- branch with "
            "isinstance(x, Undecodable) instead of `if decoded:`"
        )


VALUE_UNDECODABLE: Final[Undecodable] = Undecodable()

ScalarValue: TypeAlias = int | str


@final
@dataclass(frozen=True, slots=True)
class Decoded:
    value: ScalarValue
    decoder_id: str     # "number_words" | "digits" | "currency_spelling" | "text"


Normalization: TypeAlias = Decoded | Undecodable

# --- domain constants of the declared grammar / alphabet -------------------
# These are NOT policy knobs and NOT thresholds. They define the closed
# sub-classes audited by TS-32 / TS-33; widening one is a visible manifest edit
# that changes the mechanically generated test grid.
NUMBER_WORD_MIN: Final[int] = 0
NUMBER_WORD_MAX: Final[int] = 999_999
CANONICAL_ALPHABET: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789 "
)
STRIPPABLE_PUNCTUATION: Final[frozenset[str]] = frozenset(".,!?;:'\"")
CURRENCY_CODES: Final[frozenset[str]] = frozenset({"CAD", "USD", "EUR"})
CURRENCY_SPELLINGS: Final[Mapping[tuple[str, ...], str]] = MappingProxyType({
    ("canadian", "dollars"): "CAD",
    ("canadian", "dollar"): "CAD",
    ("us", "dollars"): "USD",
    ("us", "dollar"): "USD",
    ("euros",): "EUR",
    ("euro",): "EUR",
})
# 🔴 DELIBERATELY ABSENT: ("dollars",). A bare "dollars" does not determine
# CAD vs USD, so it MUST decode to VALUE_UNDECODABLE. Adding it here would be
# the normalizer manufacturing a witness for a currency nobody named.

_STRIPPABLE_CHARS: Final[str] = "".join(sorted(STRIPPABLE_PUNCTUATION))


def canonicalize_token(raw: str) -> str:
    """🔴 THE SINGLE NORMALIZATION ENTRY POINT. Both sides go through this and
    only this before any decoder sees a token: the transcript side at W1, the
    proposal side inside decode_argument.

    Total. Lowercases, and strips characters in STRIPPABLE_PUNCTUATION from both
    ENDS ONLY. Does not judge the result -- that is the decoders' job.

    🔴 The two operations are UNCONDITIONAL and are now load-bearing on confirmed
    evidence, not a precaution: ARCHITECTURE section 6.1 documents that formatting
    rewrites `words[].text` by exactly (a) capitalization and (b) appended
    trailing punctuation. Removing either operation re-opens that hole. TS-43
    pins both.

    🔴 PRECONDITION: it receives ONE token. STRIPPABLE_PUNCTUATION contains no
    whitespace character, so handing this function a whole multi-word string
    strips nothing from around the words inside it. Callers split FIRST; see
    decode_argument's tokenization rule (v3, F2).

    Post: idempotent -- canonicalize_token(canonicalize_token(s)) == canonicalize_token(s).
    Post: interior characters are untouched. "twenty-five", "o'clock", "200,000"
          and "$200" survive with their interior characters intact and will
          subsequently fail to decode -- fail-closed by design, see B-24."""
    return raw.lower().strip(_STRIPPABLE_CHARS)


# --- the number-word grammar -------------------------------------------------
# The grammar itself IS part of the contract as of v3: decode_number_span's
# docstring states it exhaustively (productions + the "and" position rules
# A1/A2/A3 + F6's absence of an implied "one"). What is private to this module
# is only the TABLES below and the recursive-descent parser that walks them.
# Nothing outside normalize.py may import these private names, so they add no
# cross-module surface (rule 7) -- and TS-32's renderer is forbidden from
# importing them for a second reason: an oracle built from the implementation's
# own tables carries zero bits.

_ONES_0_19: Final[Mapping[str, int]] = MappingProxyType({
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
})
_ONES_1_9: Final[Mapping[str, int]] = MappingProxyType(
    {word: value for word, value in _ONES_0_19.items() if 1 <= value <= 9}
)
_TENS: Final[Mapping[str, int]] = MappingProxyType({
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
})
_HUNDRED: Final[str] = "hundred"
_THOUSAND: Final[str] = "thousand"
_AND: Final[str] = "and"

NUMBER_CORE_TOKENS: Final[frozenset[str]] = (
    frozenset(_ONES_0_19) | frozenset(_TENS) | frozenset({_HUNDRED, _THOUSAND})
)
NUMBER_CONNECTIVE_TOKENS: Final[frozenset[str]] = frozenset({_AND})
# 🔴 Both constants are derived MECHANICALLY from the parser's own tables, never
# hand-listed. A hand-listed copy would drift away from the grammar silently,
# and W1a in gate/witness.py reads them to decide which spans may witness at all.
# 🔴 Note what NUMBER_CORE_TOKENS contains and what it does NOT: `hundred` and
# `thousand` ARE core tokens (they can begin or end a number phrase) even though
# neither decodes on its own (F6); `and` is NOT core, it is connective. TS-32's
# divergence assertion pins exactly that pair of facts.


def _is_readable_digit_run(token: str) -> bool:
    """NARROW. One token this module can read an integer VALUE out of: a run of
    ASCII decimal digits. Sole consumer: decode_number_span's digit branch, which
    holds the only `int()` call site in this module.

    🔴 The question this predicate answers is "can I turn this token into a
    value?" -- NOT "may this token appear inside a number phrase?". That second
    question belongs to _is_number_shaped_token, which is deliberately WIDER and
    must stay that way; see its docstring for why the two are not one function.

    Both connectives are load-bearing (A20.4). Dropping either reopens one half:

      * `isdigit()` alone is True for U+00B2 (superscript two), for which `int()`
        raises ValueError -- and that exception is NOT contained. Measured: it
        propagates out of decode_number_span, out through decode_span, and out of
        the gate. This grid was an uncaught CRASH path, not merely a fail-open:
        a speaker whose ASR renders a superscript makes the gate raise rather
        than refuse.
      * `isdigit()` alone is also True for Arabic-Indic (U+0663 ...), fullwidth
        and Devanagari digits, every one of which `int()` accepts HAPPILY --
        grounding a value that canonicalize_text would have refused, because
        CANONICAL_ALPHABET is ASCII-only. decode_number_span runs BEFORE
        canonicalize_text inside decode_span, so that ASCII gate never gets to
        evaluate at all. See B-32 and ARCHITECTURE V-4.
      * `isdecimal()` is NOT sufficient. It is True for U+0663 and for the
        fullwidth and Devanagari digits, and `int()` takes all of them -- so
        `isdecimal()` closes only the crash half and leaves the grounding half
        wide open. A mutation battery that probes only U+00B2 cannot tell the two
        candidate predicates apart; it needs an Arabic-Indic arm.
      * `isascii()` alone would admit "" (on which `int()` raises) and "ab";
        `isdigit()` excludes both. Hence the conjunction, not either half.

    Pre: `token` has already passed canonicalize_token."""
    return token.isascii() and token.isdigit()


def _is_number_shaped_token(token: str) -> bool:
    """WIDE. One token SHAPED like a number, whether or not a value can be read
    out of it. Sole consumer: is_number_core_token -- i.e. membership of the
    number-token alphabet that W1a builds its runs over and that R5'(iii)
    excludes recipients from.

    🔴 THESE TWO PREDICATES MUST NEVER BE MERGED AGAIN, AND THIS ONE MUST NEVER
    BE NARROWED TO MATCH _is_readable_digit_run. They answer different questions,
    and the two questions have OPPOSITE safe directions.

    ⚠ WHAT ENFORCES THAT INJUNCTION, stated so you do not have to guess. When the
    R7 architect review was written, the honest answer was NOTHING: narrowing this
    predicate left the whole suite green, and this comment was the only thing
    standing between the repo and the measured fail-open. That is no longer true.
    TS-48b now pins it, measured by re-running the narrowing mutation on a
    scratchpad copy of this tree:

        _is_number_shaped_token -> `isascii() and isdigit()`   =>  4 tests red
          TS48bMemberPredicateStaysWiderThanDecodable
            .test_a_non_ascii_token_inside_a_number_run_yields_no_money_witness
            .test_the_two_predicates_disagree_on_at_least_one_token
                (subtests U+0663.U+0664, fullwidth, U+00B2)

    So: narrow this and the suite goes RED, by design. If you ever find yourself
    narrowing it and the suite stays green, TS-48b has been weakened or deleted --
    treat that as the defect, not this comment as stale.

    Narrowing membership SPLITS number token runs. A split run hands W1a a pair of
    NEW exact boundaries in `run_bounds`, so sub-spans that W5a had been rejecting
    as SUBSUMED are promoted to witnesses: narrowing this predicate WIDENS the
    gate. Measured on `send <U+0663 U+0664> twenty dollars`, max_span_words=2,
    role_window=2, confidence floor 0.5:

        wide membership (this predicate)     -> money witnesses  {}
        narrow membership (the merged one)   -> money witnesses  {(20, MONEY_AMOUNT)}

    A previous revision merged the two predicates and shipped exactly that
    widening; the whole reason this function exists separately is that measurement.

    WIDENING is the safe direction, and it is safe for BOTH consumers at once:
      * runs only ever MERGE. A merged run is longer, so it matches fewer spans
        exactly under W5a; and containing a token no decoder can read, it decodes
        to nothing itself -- so it emits no witness AND subsumes every sub-span
        inside it.
      * R5'(iii) excludes MORE indices, so RECIPIENT is tagged less often.
        ⚠ UNSTATED PREMISE, named here rather than left implicit (m-1): "tagged
        less often" only means "fewer witnesses" because RECIPIENT is the LAST
        entry of roles.ROLE_RULE_ORDER. That tuple's own docstring says
        reordering it CHANGES RUNTIME BEHAVIOUR. Move RECIPIENT ahead of another
        rule and suppressing it would let a LATER rule fire instead -- turning
        "can only REMOVE witnesses" into "can SUBSTITUTE a different role", and
        this whole argument false. TS-33 pins the order; if you reorder it,
        re-derive this paragraph, do not assume it survives.
        ⚠ AND IT IS UNREACHABLE TODAY (m-2): any span whose (iii) verdict this
        widening changes must CONTAIN the newly-core token -- which is exactly
        the token no decoder can read, so the span is rejected at W4 before
        tag_role ever runs. Measured: decode_span of ['U+0663 U+0664'],
        [it + 'twenty'], ['twenty' + it], [it,'to','alice'] are all UNDECODABLE.
        This half is belt-and-braces. Do not go looking for a fixture that
        exhibits it and conclude the note is wrong when you cannot find one.
    Both consumers can therefore only REMOVE witnesses. That asymmetry is the
    whole argument, and it does not survive merging.

    🔴 The rationale the merged version gave for itself -- that membership and
    readability would otherwise "drift apart" -- is refuted by this design's own
    established shape. F6: `hundred` and `thousand` ARE core tokens and NEVER
    decode on their own. Member-but-not-readable is not drift here, it is the
    documented rule, and TS-32's divergence assertion pins it. So "they would be
    inconsistent" was never a reason to share one predicate.

    Pre: `token` has already passed canonicalize_token."""
    return token.isdigit()


def is_number_core_token(token: str) -> bool:
    """True iff `token` can begin or end a number phrase. Digit runs count.
    Pre: `token` has already passed canonicalize_token."""
    return token in NUMBER_CORE_TOKENS or _is_number_shaped_token(token)


def _parse_tail(tokens: Sequence[str]) -> int | None:
    """Parses the 0..99 tail of a GROUP: (TENS [ONES_1_9]) | ONES_0_19.

    Must consume the WHOLE slice: a tail that parses a prefix and leaves tokens
    behind is a grammar violation, not a partial success. Returns None on any
    violation; never returns a partial accumulator."""
    if not tokens:
        return None

    if tokens[0] in _TENS:
        value = _TENS[tokens[0]]
        if len(tokens) == 1:
            return value
        if len(tokens) == 2 and tokens[1] in _ONES_1_9:
            return value + _ONES_1_9[tokens[1]]
        return None

    if len(tokens) == 1 and tokens[0] in _ONES_0_19:
        return _ONES_0_19[tokens[0]]

    return None


def _parse_number_group(tokens: Sequence[str]) -> int | None:
    """Parses a single GROUP -- a 1..999 chunk containing no "thousand" token.

        GROUP := ONES_1_9 "hundred" [ "and" ]? [ TAIL ] | TAIL

    🔴 F6: there is no implied "one". The hundreds phrase requires an explicit
    ONES_1_9 multiplier, so a bare "hundred" reaches _parse_tail, which does not
    know that word, and the whole group is rejected.

    🔴 A1: the connector "and" is accepted ONLY immediately after a hundreds
    phrase this call actually consumed, and ONLY when at least one further token
    of the group follows it. Everything else is a violation.

    Total over its own domain in the sense that it never returns a partial int:
    the instant the grammar is violated it returns None, and the caller discards
    everything."""
    if not tokens:
        return None

    index = 0
    length = len(tokens)
    value = 0
    consumed_hundreds = False

    if (
        length - index >= 2
        and tokens[index] in _ONES_1_9
        and tokens[index + 1] == _HUNDRED
    ):
        value = _ONES_1_9[tokens[index]] * 100
        index += 2
        consumed_hundreds = True

    if consumed_hundreds and index == length:
        return value                    # "two hundred"

    if consumed_hundreds and tokens[index] == _AND:
        index += 1                      # A1: legal here, and only here
        if index == length:
            return None                 # "two hundred and" -- nothing follows

    tail = _parse_tail(tokens[index:])
    if tail is None:
        return None
    return value + tail


def _parse_number_words(tokens: Sequence[str]) -> int | None:
    """Parses the full SPAN production over [0, 999_999]:

        SPAN := GROUP | GROUP "thousand" [ "and" ]? [ GROUP ]?

    🔴 F6: the left GROUP is REQUIRED. A bare leading "thousand" supplies a word
    the speaker did not say, so it is a violation rather than 1000.

    🔴 A2: one "and" may follow "thousand", and only when the remaining
    right-hand group is non-empty AND contains no hundreds phrase.

    Never returns a partial accumulator."""
    tokens = tuple(tokens)
    if not tokens:
        return None
    if tokens.count(_THOUSAND) > 1:
        return None

    if _THOUSAND not in tokens:
        return _parse_number_group(tokens)

    split_at = tokens.index(_THOUSAND)
    left = tokens[:split_at]
    right = tokens[split_at + 1:]

    if not left:
        return None                     # F6: no implied "one" before "thousand"
    thousands = _parse_number_group(left)
    if thousands is None:
        return None

    if right and right[0] == _AND:
        right = right[1:]
        if not right:
            return None                 # "one thousand and" -- nothing follows
        if _HUNDRED in right:
            return None                 # "one thousand and two hundred" -- A2

    if not right:
        return thousands * 1000
    remainder = _parse_number_group(right)
    if remainder is None:
        return None
    return thousands * 1000 + remainder


def decode_number_span(tokens: Sequence[str]) -> Normalization:
    """Digit runs, and English number words in [NUMBER_WORD_MIN, NUMBER_WORD_MAX].

    Pre : every element of `tokens` has already passed through canonicalize_token.
    Post: returns Decoded(int, "digits"|"number_words") or VALUE_UNDECODABLE.
    Post: `tokens == []` returns VALUE_UNDECODABLE (an empty span decodes to
          nothing, never to 0).
    🔴 There is exactly one `return VALUE_UNDECODABLE`-class exit and no partial
    accumulator is ever returned. If any token in `tokens` is not consumable by
    the grammar, the WHOLE span is undecodable -- not the prefix that parsed.

    ====================================================================
    THE GRAMMAR (contractual; the implementer writes the parser, not the rules)
    ====================================================================
    GROUP (a 1..999 chunk, no "thousand" token):
        ONES_1_9 "hundred" [ "and" ]? [ (TENS [ONES_1_9]) | ONES_0_19 ]
      | (TENS [ONES_1_9]) | ONES_0_19
    SPAN:
        GROUP | [ GROUP ]? "thousand" [ "and" ]? [ GROUP ]?

    🔴 F6 -- NO IMPLIED "ONE". A bare `hundred` and a bare `thousand` with no
    multiplier are VALUE_UNDECODABLE. The normalizer does NOT supply a word the
    speaker did not say.
        ["hundred"]            -> VALUE_UNDECODABLE   (was 100 in the delivery)
        ["thousand"]           -> VALUE_UNDECODABLE   (was 1000 in the delivery)
        ["hundred","five"]     -> VALUE_UNDECODABLE   (was 105 in the delivery)
    ⚠ Cost, stated rather than hidden: "transfer hundred dollars" and "transfer
    thousand dollars" -- real if sloppy utterances -- now ground nothing and
    therefore BLOCK. Fail-closed, and it is the cheap side of the asymmetry.
    🔴 Provenance of this rule, recorded because it is why it is here: the
    delivered implementation had the implied-one behaviour, the contract never
    authorized it (this docstring's body was `...`), it appeared only in a
    private implementation docstring -- and TS-4 had already been written to
    assert it as CORRECT. A generosity nobody decided on had acquired a green
    test defending it, inside a test whose own title is "transcript span the
    normalizer cannot read".

    🔴 "and" IS IN THE GRAMMAR, and it is a CONNECTOR: it carries no value and is
    legal in exactly two positions. Everything else is VALUE_UNDECODABLE.

      A1 -- inside a GROUP: at most one "and", ONLY immediately after a hundreds
            phrase that was actually consumed (i.e. ONES_1_9 "hundred"), and ONLY
            when at least one further token of that group follows.
              "two hundred and five"      -> 205        OK
              "two hundred and"           -> UNDECODABLE  (nothing follows)
              "and five"                  -> UNDECODABLE  (no hundreds phrase)
              "twenty and five"           -> UNDECODABLE  (no hundreds phrase)
              "two and hundred"           -> UNDECODABLE  (wrong side)
              "two hundred and and five"  -> UNDECODABLE  (twice in one group)
              "hundred and five"          -> UNDECODABLE  (F6: no bare hundred)

      A2 -- immediately after "thousand": at most one "and", ONLY when the
            remaining right-hand group is non-empty AND contains no hundreds
            phrase.
              "one thousand and five"        -> 1005 OK
              "one thousand and twenty one"  -> 1021 OK
              "one thousand and two hundred" -> UNDECODABLE (right group has a
                    hundreds phrase; the idiomatic form is "one thousand two
                    hundred". Refusing is fail-closed and is a declared choice.)
              "one thousand and"             -> UNDECODABLE (nothing follows)

      A3 -- "and" appears NOWHERE ELSE. Not at span start, not at span end, not
            before "thousand", and never twice within one group.

    Derived post-condition, cheap to assert independently:
        tokens.count("and") <= 2, and == 2 only in the shape
        <GROUP with A1> "thousand" <GROUP with A1>.

    🔴 STATUS OF THIS "and" RULE (router, C3b). Admitting "and" is a USABILITY
    improvement: it is what lets 205 be grounded at all. It is NOT the security
    remedy -- measurement (F5) showed that admitting "and" closes exactly one
    instance of the recipient over-generation class and leaves the class open.
    The security remedy is W5a (A4) + R5' (A3). Do not let this docstring be read
    as closing anything."""
    if not tokens:
        return VALUE_UNDECODABLE

    if len(tokens) == 1 and _is_readable_digit_run(tokens[0]):
        digit_value = int(tokens[0])
        if NUMBER_WORD_MIN <= digit_value <= NUMBER_WORD_MAX:
            return Decoded(value=digit_value, decoder_id="digits")
        return VALUE_UNDECODABLE

    word_value = _parse_number_words(tokens)
    if word_value is None:
        return VALUE_UNDECODABLE
    if NUMBER_WORD_MIN <= word_value <= NUMBER_WORD_MAX:
        return Decoded(value=word_value, decoder_id="number_words")
    return VALUE_UNDECODABLE


def decode_currency_span(tokens: Sequence[str]) -> Normalization:
    """Exact lookup of `tuple(tokens)` in CURRENCY_SPELLINGS.
    Pre : every element of `tokens` has already passed through canonicalize_token.
    Post: Decoded(str, "currency_spelling") or VALUE_UNDECODABLE."""
    code = CURRENCY_SPELLINGS.get(tuple(tokens))
    if code is None:
        return VALUE_UNDECODABLE
    return Decoded(value=code, decoder_id="currency_spelling")


def canonicalize_text(raw: str) -> Normalization:
    """Applies canonicalize_token per whitespace-separated token, then joins with
    single spaces.
    Post: Decoded(str, "text") iff every remaining character is in
    CANONICAL_ALPHABET and the result is non-empty; else VALUE_UNDECODABLE.

    This is where non-English / non-ASCII input becomes an explicit BLOCK rather
    than a silent miss (ARCHITECTURE V-4, fail-closed)."""
    tokens = raw.split()
    result = " ".join(canonicalize_token(token) for token in tokens)
    if result == "":
        return VALUE_UNDECODABLE
    if not set(result) <= CANONICAL_ALPHABET:
        return VALUE_UNDECODABLE
    return Decoded(value=result, decoder_id="text")


def decode_span(tokens: Sequence[str]) -> Normalization:
    """Transcript side. Tries, in this fixed order:
        1. decode_number_span
        2. decode_currency_span
        3. canonicalize_text
    First non-UNDECODABLE wins. Returns VALUE_UNDECODABLE iff all three decline.
    Pre : every element of `tokens` has already passed through canonicalize_token
          (guaranteed by W1).
    🔴 Sees only `tokens`. No proposal, no candidate value, no action name."""
    number_result = decode_number_span(tokens)
    if not isinstance(number_result, Undecodable):
        return number_result

    currency_result = decode_currency_span(tokens)
    if not isinstance(currency_result, Undecodable):
        return currency_result

    return canonicalize_text(" ".join(tokens))


def decode_argument(raw: object, kind: ValueKind) -> Normalization:
    """Proposal side. Sees only `raw` and the registry-declared `kind`.

    🔴 R3 SYMMETRY RULE: every string token reaching a decoder here goes through
    canonicalize_token first, exactly as the transcript side does at W1. Before
    this rule, the NUMBER branch split the raw string without canonicalizing while
    the CURRENCY_CODE branch used `.strip().upper()` and the TEXT branch used
    canonicalize_text -- three different normalizations of the same bytes,
    depending on which parameter they landed in. That asymmetry failed closed
    (it produced BLOCK), but its consequence was that the gate's answer depended
    on the model's serialization cosmetics rather than on evidence, and cosmetics
    are chosen by the adversary. See B-27 for the exact class of inputs whose
    verdict this rule changes.

    - `type(raw) is bool` -> VALUE_UNDECODABLE for every kind, checked FIRST.
      (bool is an int subclass; True must never decode to 1.)

    🔴 TOKENIZATION RULE (v3, F2). Every `str` branch obtains its tokens by the
    SAME expression, with no exceptions:

        tokens = [canonicalize_token(t) for t in raw.split()]

    Argument-less `raw.split()` splits on arbitrary runs of ASCII whitespace and
    discards leading and trailing whitespace, so surrounding and interior
    whitespace is absorbed identically in all three branches. The branches differ
    ONLY in which decoder consumes `tokens`.

    🔴 Do NOT hand a whole `raw` string to `canonicalize_token`. That function's
    precondition is that it receives ONE token, and STRIPPABLE_PUNCTUATION
    contains no whitespace character -- so canonicalize_token("  cad  ") returns
    "  cad  " unchanged and the CURRENCY_CODE branch then refuses a value it
    should read. The v2 contract specified exactly that mistake; this rule is its
    correction. An implementation that reproduces the v2 line is wrong even
    though v2 told it to.

    - kind NUMBER:
          int -> Decoded(raw, "digits")
          str -> decode_number_span(tokens)
          anything else -> VALUE_UNDECODABLE
    - kind CURRENCY_CODE:
          str with len(tokens) == 1 and tokens[0].upper() in CURRENCY_CODES
              -> Decoded(tokens[0].upper(), "currency_spelling")
          str with len(tokens) != 1 -> VALUE_UNDECODABLE. This is not a detail:
              "" and all-whitespace yield zero tokens, and "cad usd" yields two.
              A multi-token string must NEVER collapse into a single code.
          anything else -> VALUE_UNDECODABLE
    - kind TEXT:
          str -> canonicalize_text(raw)   # already tokenizes via raw.split()
          anything else -> VALUE_UNDECODABLE

    🔴 Note what did NOT widen: canonicalize_token strips from the ENDS only, so
    "twenty-five", "$200", "200,000" and "o'clock" remain VALUE_UNDECODABLE on
    both sides. This rule aligns the two sides; it does not add a decoder.
    Whitespace *between* tokens is a separator, never a strippable character:
    "c a d" is three tokens and stays undecodable."""
    if type(raw) is bool:
        return VALUE_UNDECODABLE

    if kind is ValueKind.NUMBER:
        if type(raw) is int:
            # 🔴 CONTRACT NOTE (v3, D-9 -> B-34). This branch applies NO
            # [NUMBER_WORD_MIN, NUMBER_WORD_MAX] range check, unlike every other
            # numeric path in the package: decode_number_span range-checks both
            # its digit exit and its number-word exit. Measured, not inferred:
            # decode_argument(-5, NUMBER)     -> Decoded(-5, "digits")
            # decode_argument(10**9, NUMBER)  -> Decoded(1000000000, "digits")
            # Why that is currently SAFE rather than a hole: a decoded proposal
            # value still has to be matched against a WITNESS, and no witness can
            # carry a negative value or one above NUMBER_WORD_MAX --
            # decode_number_span is the only transcript-side decoder that yields
            # an int, and it range-checks every exit. An out-of-range proposal
            # therefore finds no witness and BLOCKs, fail-closed.
            # ⚠ HONESTY, stated rather than hidden: the sentence above is an
            # ARGUMENT, not a pin. No end-to-end test asserts it, so it is
            # registered as declared gap B-34 and the behaviour is deliberately
            # left unchanged this round. Do not read this note as a guarantee,
            # and do not add the range check here without re-deriving what the
            # witness side actually admits.
            return Decoded(value=raw, decoder_id="digits")
        if isinstance(raw, str):
            tokens = [canonicalize_token(token) for token in raw.split()]
            return decode_number_span(tokens)
        return VALUE_UNDECODABLE

    if kind is ValueKind.CURRENCY_CODE:
        # 🔴 B-33 LIVES HERE (m-4). The NUMBER branch above carries a thorough
        # honesty note; the absence of one here must NOT be read as "this branch
        # is clean". Measured, not inferred:
        #     decode_argument("u<U+017F>d", CURRENCY_CODE)
        #                                 -> Decoded("USD", "currency_spelling")
        #     decode_span(["u<U+017F>d"]) -> VALUE_UNDECODABLE
        # i.e. the PROPOSAL side accepts a spelling the TRANSCRIPT side refuses.
        # canonicalize_token's case folding maps U+017F (long s) onto "s", and
        # `.upper()` then yields "USD". That is a V-4 SYMMETRY defect, registered
        # as B-33 and DELIBERATELY NOT FIXED this round -- not a fail-open: an
        # asymmetric proposal still has to match a witness, and the transcript
        # side cannot produce one, so it BLOCKs. Like B-34 below, that sentence
        # is an ARGUMENT, not a pin. No test asserts it.
        if isinstance(raw, str):
            tokens = [canonicalize_token(token) for token in raw.split()]
            # 🔴 Order matters and is pinned by TS-43 Part 3: canonicalize_token
            # lowercases and strips FIRST, `.upper()` runs SECOND. Upper-casing
            # first would leave the trailing dot of "CAD." unstripped.
            if len(tokens) == 1:
                code = tokens[0].upper()
                if code in CURRENCY_CODES:
                    return Decoded(value=code, decoder_id="currency_spelling")
        return VALUE_UNDECODABLE

    if kind is ValueKind.TEXT:
        if isinstance(raw, str):
            return canonicalize_text(raw)
        return VALUE_UNDECODABLE

    # Unreachable while ValueKind has exactly the three members above; kept
    # fail-closed rather than omitted, in case the enum is ever widened.
    return VALUE_UNDECODABLE
