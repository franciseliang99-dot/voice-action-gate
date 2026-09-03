# tests/test_gate_ts32_47.py
"""TS-32 .. TS-47 — grammar audit, role manifest, structural pins, and the v3
over-generation class arms.

Scope of this module: TS-32 through TS-47 inclusive, plus TS-48 / TS-48b
appended at the end (A20.4's ASCII digit gate and A24.1's D-2 predicate split —
the two rulings A24.6.4 records as having no test nail at all). The file name
still says ts32_47; it is kept stable so the module path in the design's
citations does not rot. TS-1..TS-31 live in the sibling test modules; nothing
here imports from them.

Authority: `design_v3.md`, read in its mandated order — the `## v3 权威修订段`
(A0–A19) first, the v2 body second, the revision段 winning every conflict.
Concretely: TS-32 follows A9, TS-33 follows A10, TS-37 follows A7, TS-43 follows
A8, and TS-44/45/46/47 follow A11/A12. Where the v2 body still carries the older
wording, it is *not* what this module asserts.

Two invariants from the revision段 govern this file and are restated here because
a reader of the test must meet them, not only a reader of the design:

  TI-1 (A11).  A test whose subject is a CLASS of fail-open behaviour asserts a
  SET EQUALITY over a mechanically enumerated projection. It never asserts that
  one member is absent, and it never says "X was not grounded". Provenance,
  recorded as an incident rather than a maxim: an arm pinned to the single
  proposal `to="two hundred and five"` was measured (F5) to go GREEN under a fix
  that closed only that one instance while `to="ana two hundred and five"` and
  `to="two hundred and five dollars"` stayed open — and a green arm titled
  "fail-open closed" is worse than no arm, because it reads as closing the class.

  DN-1 (A16).  No witness set is written down as a hand-authored list. A witness
  set is stated only as (i) a generation rule, (ii) the policy values it is a
  function of, and (iii) one measured instance with its fixture and policy. The
  architect violated DN-1 in the same reply that proposed it: it hand-listed 4
  members where the measurement is 13.

🔴 RENDERER DISCIPLINE (A9, router, not optional). The English number renderer
below is written independently from the standard English cardinal rules stated in
A1. It does NOT import and does NOT copy `gate.normalize`'s private tables
(`_ONES_0_19`, `_TENS`, `_HUNDRED`, `_THOUSAND`, `_AND`). Deriving the expected
values from the implementation under test would be a same-source oracle carrying
zero bits. The same rule governs the legal-`and`-index set: it is computed from
the A1/A2/A3 position rules, never by asking the parser.

⚠ EVERY `EXPECTED` LITERAL BELOW IS MARKED `[未执行 · 静态推演]`. Those literals
are the design's static predictions, transcribed verbatim. They are settled by
the A18.1 two-arm projection diff run by the executor. If a literal disagrees
with the implementation, that disagreement is a FINDING: go back to the A1/A3/A4
rules and re-derive. It is not permission to edit the literal, and it is not
permission to edit the implementation to match the literal.

⚠ The tables headed "改动前实测" are the router's measurements of the DELIVERED
(pre-change) code. They appear in comments only. They are not expectations; they
exist so that the over-generation each arm targets is documented as having
actually happened.

Thresholds: every numeric policy value in this file is a module-local constant.
Nothing threshold-shaped is imported from `gate/`.
"""

from __future__ import annotations

import ast
import copy
import inspect
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if _REPO_ROOT not in sys.path:  # keeps `python3 tests/test_gate_ts32_47.py` working too
    sys.path.insert(0, _REPO_ROOT)

import gate  # noqa: E402  (path bootstrap must precede the package import)
from gate.checks import STANDARD_CHECKERS  # noqa: E402
from gate.decision import Gate  # noqa: E402
from gate.errors import DeploymentLintError  # noqa: E402
from gate.normalize import (  # noqa: E402
    CURRENCY_CODES,
    CURRENCY_SPELLINGS,
    NUMBER_CONNECTIVE_TOKENS,
    NUMBER_CORE_TOKENS,
    NUMBER_WORD_MAX,
    NUMBER_WORD_MIN,
    STRIPPABLE_PUNCTUATION,
    Decoded,
    Undecodable,
    VALUE_UNDECODABLE,
    ValueKind,
    canonicalize_text,
    canonicalize_token,
    decode_argument,
    decode_currency_span,
    decode_number_span,
    decode_span,
    is_number_core_token,
)
from gate.proposal import parse_proposal  # noqa: E402
from gate.reasons import BlockReason, Outcome  # noqa: E402
from gate.reference import reference_registry  # noqa: E402
from gate.registry import (  # noqa: E402
    ActionRegistry,
    ActionSpec,
    CheckId,
    CheckRequirement,
    CheckStatus,
    ParamSpec,
    Reversibility,
    lint_deployment,
    lint_registry,
)
from gate.roles import (  # noqa: E402
    CURRENCY_UNIT_CUES,
    RECIPIENT_LEFT_CUES,
    ROLE_RULE_ORDER,
    STREET_CUES,
    TIME_RIGHT_CUES,
    SemanticRole,
    tag_role,
)
from gate.transcript import (  # noqa: E402
    TranscriptProvenance,
    parse_transcript,
    raw_text_of,
)
from gate.witness import RejectCause, generate_witnesses  # noqa: E402

# ---------------------------------------------------------------------------
# Test-module-local policy constants. NOTHING here is imported from gate/.
# (Requirement line 21: no hard-coded confidence threshold may act as the
# "correct answer" inside the package; the numbers live here and are typed into
# Gate(...) / generate_witnesses(...) by the caller, which is this test.)
# ---------------------------------------------------------------------------
CONF_HIGH = 0.99
CONF_LOW = 0.42
FLOOR_HIGH = 0.90
FLOOR_LOW = 0.40
STANDARD_K = 3
STANDARD_RW = 2
MAX_TRANSCRIPT_WORDS = 200

PROVENANCE_UNKNOWN = TranscriptProvenance("text", None, "raw_text_of")
PROVENANCE_KNOWN_UNFORMATTED = TranscriptProvenance("text", False, "raw_text_of")


# ===========================================================================
# Shared helpers.
# ⚠ These may duplicate helpers written by the parallel test-authoring paths
#   (TS-1..31). Router to collapse the duplicates at integration time.
# ===========================================================================
def transcript_from_tokens(tokens, *, conf=CONF_HIGH, final=True, conf_overrides=None):
    """Build a parsed Transcript from a token list.

    `conf_overrides` maps word index -> confidence, so a single word can be
    dropped below a floor without touching the rest of the fixture.
    """
    raw = []
    for index, text in enumerate(tokens):
        confidence = conf
        if conf_overrides is not None and index in conf_overrides:
            confidence = conf_overrides[index]
        raw.append(
            {
                "text": text,
                "start": index * 100,
                "end": index * 100 + 90,
                "confidence": confidence,
                "word_is_final": final,
            }
        )
    return parse_transcript(raw)


def transcript_from_sentence(sentence, **kwargs):
    return transcript_from_tokens(sentence.split(), **kwargs)


def canonical_tokens(transcript):
    """The W1 projection of a transcript, computed test-side through the one
    public normalization entry point."""
    return [canonicalize_token(raw_text_of(word)) for word in transcript.words]


def core_indices(tokens):
    """W1a's `core_tokens`, computed test-side from the public predicate."""
    return frozenset(i for i, tok in enumerate(tokens) if is_number_core_token(tok))


def witness_projection(transcript, *, floor, k, rw):
    """The projection every class arm in this module asserts on: the WHOLE
    witness set as `{(value, role)}`. Not a slice of it (TI-1)."""
    result = generate_witnesses(
        transcript,
        text_of=raw_text_of,
        confidence_floor=floor,
        max_span_words=k,
        role_window=rw,
    )
    return {(w.value, w.role) for w in result.witnesses}


def witness_set_of(transcript, *, floor, k, rw):
    return generate_witnesses(
        transcript,
        text_of=raw_text_of,
        confidence_floor=floor,
        max_span_words=k,
        role_window=rw,
    )


def role_of(tokens, span_start, span_end, *, role_window):
    """Call `tag_role` the way `generate_witnesses` does at W6: decoded value
    comes from `decode_span` over canonicalized tokens, and `core_tokens` is the
    W1a index set. Returns (role, decoded)."""
    transcript = transcript_from_tokens(tokens)
    canon = canonical_tokens(transcript)
    decoded = decode_span(canon[span_start:span_end])
    if isinstance(decoded, Undecodable):
        raise AssertionError(
            f"fixture error: span {tokens[span_start:span_end]!r} does not decode"
        )
    role = tag_role(
        transcript.words,
        span_start,
        span_end,
        decoded,
        raw_text_of,
        role_window,
        core_indices(canon),
    )
    return role, decoded


def _checks(read_back_status, read_back_rationale):
    return {
        CheckId.WITNESS_PRESENT: CheckRequirement(
            CheckStatus.REQUIRED, "grounding is the point of this gate"
        ),
        CheckId.ROLE_MATCH: CheckRequirement(
            CheckStatus.REQUIRED, "role typing is what makes this a parser"
        ),
        CheckId.CONFIDENCE_FLOOR: CheckRequirement(
            CheckStatus.REQUIRED, "the floor is a caller-supplied policy value"
        ),
        CheckId.READ_BACK_CONFIRMED: CheckRequirement(
            read_back_status, read_back_rationale
        ),
    }


def permissive_registry(*, reversibility=Reversibility.IRREVERSIBLE):
    """A test-local `transfer` registry whose READ_BACK_CONFIRMED is
    NOT_REQUIRED, so that a grounded proposal can reach ALLOW.

    🔴 It is deliberately NOT the shipped registry: `reference_registry()` blocks
    every transfer (TS-42), which is correct for the product and useless for an
    arm that needs to observe the grounding layer's own answer.
    """
    checks = _checks(
        CheckStatus.NOT_REQUIRED,
        "test fixture: grounding alone is what this arm is measuring",
    )
    params = {
        "amount": ParamSpec("amount", ValueKind.NUMBER, SemanticRole.MONEY_AMOUNT, dict(checks)),
        "currency": ParamSpec("currency", ValueKind.CURRENCY_CODE, SemanticRole.CURRENCY, dict(checks)),
        "to": ParamSpec("to", ValueKind.TEXT, SemanticRole.RECIPIENT, dict(checks)),
    }
    return ActionRegistry({"transfer": ActionSpec("transfer", reversibility, params)})


def build_gate(
    registry,
    *,
    floor=FLOOR_HIGH,
    k=STANDARD_K,
    rw=STANDARD_RW,
    provenance=PROVENANCE_UNKNOWN,
    require_known_provenance=False,
    checkers=None,
):
    return Gate(
        registry=registry,
        checkers=STANDARD_CHECKERS if checkers is None else checkers,
        text_of=raw_text_of,
        provenance=provenance,
        confidence_floor=floor,
        max_span_words=k,
        role_window=rw,
        max_transcript_words=MAX_TRANSCRIPT_WORDS,
        require_known_provenance=require_known_provenance,
    )


def proposal_of(**arguments):
    return parse_proposal({"action": "transfer", "arguments": dict(arguments)})


# ===========================================================================
# AST helpers for the structural tests (TS-34..TS-38, TS-41).
# ===========================================================================
GATE_DIR = os.path.join(_REPO_ROOT, "gate")


def gate_python_files():
    names = sorted(n for n in os.listdir(GATE_DIR) if n.endswith(".py"))
    return [(n, os.path.join(GATE_DIR, n)) for n in names]


def read_source(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def parse_with_parents(source, filename):
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._parent = node  # noqa: SLF001 (test-local annotation)
    return tree


def enclosing_qualname(node):
    parts = []
    current = getattr(node, "_parent", None)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(current.name)
        current = getattr(current, "_parent", None)
    return ".".join(reversed(parts))


def docstring_constant_ids(tree):
    """ids of the Constant nodes that are module/class/function docstrings."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def is_dataclass_decorated(class_node):
    for dec in class_node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = None
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        if name == "dataclass":
            return True
    return False


# ===========================================================================
# The independent English cardinal renderer (A9 renderer discipline).
#
# Authored from the A1 grammar and standard English cardinal spelling. Nothing
# here is imported from or copied out of gate/.
#
#   GROUP := ONES_1_9 "hundred" ["and"]? [ (TENS [ONES_1_9]) | ONES_0_19 ]
#          | (TENS [ONES_1_9]) | ONES_0_19
#   SPAN  := GROUP | GROUP "thousand" ["and"]? [GROUP]?
#
#   F6: no implied "one". A bare `hundred` / a bare `thousand` is undecodable,
#       so the leading multiplier is REQUIRED in both positions. That is why the
#       SPAN production above shows `GROUP "thousand"`, not `[GROUP]? "thousand"`.
#   A1: at most one "and" per group, only right after a CONSUMED hundreds phrase
#       and only when a further token of that group follows.
#   A2: one "and" right after "thousand", only when the right-hand group is
#       non-empty AND contains no hundreds phrase.
#   A3: "and" appears nowhere else.
#
# 🔴 Hyphenated surface forms ("twenty-five") are NEVER produced here and are
#    never a positive: TS-5 pins them undecodable, and `canonicalize_token`
#    strips from the ENDS only. A renderer that emitted them would be inventing
#    a form the contract refuses.
# ===========================================================================
ONES_WORDS_0_19 = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
TENS_WORDS_BY_DIGIT = {
    2: "twenty", 3: "thirty", 4: "forty", 5: "fifty",
    6: "sixty", 7: "seventy", 8: "eighty", 9: "ninety",
}
INDEPENDENT_ONES = frozenset(ONES_WORDS_0_19)
INDEPENDENT_TENS = frozenset(TENS_WORDS_BY_DIGIT.values())
HUNDRED_WORD = "hundred"
THOUSAND_WORD = "thousand"
AND_WORD = "and"


def _group_prime(n):
    """The single 'and'-free GROUP rendering of 1 <= n <= 999."""
    if not 1 <= n <= 999:
        raise ValueError(f"not a GROUP value: {n}")
    if n < 20:
        return [ONES_WORDS_0_19[n]]
    if n < 100:
        tens = TENS_WORDS_BY_DIGIT[n // 10]
        return [tens] if n % 10 == 0 else [tens, ONES_WORDS_0_19[n % 10]]
    head = [ONES_WORDS_0_19[n // 100], HUNDRED_WORD]
    remainder = n % 100
    return head if remainder == 0 else head + _group_prime(remainder)


def group_forms(n):
    """Every GROUP rendering of 1 <= n <= 999 (A1's optional 'and' included)."""
    prime = _group_prime(n)
    forms = [prime]
    if n >= 100 and n % 100 != 0:
        # A1: the hundreds phrase was consumed and at least one token follows.
        forms.append(prime[:2] + [AND_WORD] + prime[2:])
    return forms


def span_forms(n):
    """Every word form of `n` the grammar allows, in the A1/A2/A3 positions."""
    if n == 0:
        return [[ONES_WORDS_0_19[0]]]
    if n <= 999:
        return group_forms(n)
    thousands, remainder = divmod(n, 1000)
    forms = []
    for left in group_forms(thousands):
        if remainder == 0:
            forms.append(left + [THOUSAND_WORD])
            continue
        for right in group_forms(remainder):
            forms.append(left + [THOUSAND_WORD] + right)
            if remainder < 100:
                # A2: right-hand group is non-empty and contains no hundreds phrase.
                forms.append(left + [THOUSAND_WORD, AND_WORD] + right)
    return forms


def prime_form(n):
    """The unique 'and'-free rendering of n."""
    if n == 0:
        return [ONES_WORDS_0_19[0]]
    if n <= 999:
        return _group_prime(n)
    thousands, remainder = divmod(n, 1000)
    tail = _group_prime(remainder) if remainder else []
    return _group_prime(thousands) + [THOUSAND_WORD] + tail


def _group_form_count(n):
    return 2 if (n >= 100 and n % 100 != 0) else 1


def expected_form_count(n):
    """A second, independent derivation of |span_forms(n)| straight from the
    A1/A2 position rules. It exists so that a renderer that silently emits only
    one surface form per integer becomes VISIBLE (A9: "只吐一种词形的渲染器由此
    可见地欠覆盖")."""
    if n == 0:
        return 1
    if n <= 999:
        return _group_form_count(n)
    thousands, remainder = divmod(n, 1000)
    if remainder == 0:
        return _group_form_count(thousands)
    connector = 2 if remainder < 100 else 1
    return _group_form_count(thousands) * _group_form_count(remainder) * connector


def covered_numbers():
    """0..999 exhaustively, plus a systematic (loop-generated, not hand-listed)
    sample across the thousands scale. DN-1: a rule plus its parameters, never a
    hand list."""
    numbers = list(range(0, 1000))
    for thousands in range(1, 1000, 37):
        for remainder in (0, 1, 5, 19, 20, 21, 99, 100, 105, 110, 205, 999):
            numbers.append(thousands * 1000 + remainder)
    return numbers


def insert_and(tokens, index):
    return tokens[:index] + [AND_WORD] + tokens[index:]


def first_failures(failures, limit=12):
    return failures[:limit]


# ===========================================================================
# TS-32 — closed sub-class audit: the number grammar, the "and" connector, and
#         the absence of an implied "one".   (design_v3.md §A9, replacing v2)
# ===========================================================================
class TS32NumberGrammarAudit(unittest.TestCase):
    """A9. Positive half is a mechanically generated round-trip over every
    integer the grammar can express in [NUMBER_WORD_MIN, NUMBER_WORD_MAX]; the
    "and"-position audit inserts the connector at EVERY index and takes its legal
    index set FROM THE RULES, not from the parser; the negative half writes the
    fail-closed choices out as literals so they are visible in the repository.

    🔴 Oracle provenance: `span_forms` / `prime_form` above are authored from
    A1's production rules. `gate.normalize`'s private word tables are never
    imported. Comparing implementation against implementation would carry 0 bits.
    """

    def test_renderer_never_emits_a_hyphenated_or_glued_form(self):
        # Discipline check on the ORACLE itself: a hyphenated surface form is
        # never a positive anywhere in this package (TS-5 pins it undecodable,
        # and canonicalize_token strips from the ends only).
        for n in (5, 25, 42, 99, 105, 205, 1005, 21021):
            for form in span_forms(n):
                for token in form:
                    self.assertNotIn("-", token, f"renderer emitted a hyphen for {n}")
                    self.assertTrue(token.isalpha(), f"renderer emitted {token!r} for {n}")

    def test_form_count_matches_the_rule_derivation(self):
        failures = []
        for n in covered_numbers():
            got = len(span_forms(n))
            want = expected_form_count(n)
            if got != want:
                failures.append((n, got, want))
        self.assertEqual(
            first_failures(failures), [], f"{len(failures)} integers with a form-count mismatch"
        )

    def test_positive_half_word_forms_and_digit_forms_round_trip(self):
        failures = []
        for n in covered_numbers():
            values = set()
            for form in span_forms(n):
                got = decode_number_span(list(form))
                want = Decoded(n, "number_words")
                if got != want:
                    failures.append((n, form, got))
                elif isinstance(got, Decoded):
                    values.add(got.value)
            digits = decode_number_span([str(n)])
            if digits != Decoded(n, "digits"):
                failures.append((n, [str(n)], digits))
            # A9: "另断言同一个 n 的所有词形解出同一个 .value".
            if len(values) > 1:
                failures.append((n, "word forms disagree on .value", sorted(values)))
        self.assertEqual(
            first_failures(failures), [], f"{len(failures)} grammar round-trip failures"
        )

    def test_and_position_audit_legal_indices_computed_from_the_rules(self):
        """For every legal prime form, insert "and" at every index 0..len(tokens).
        The legal index set is derived from A1/A2/A3 (via `span_forms`), never by
        asking the implementation. Every legal insertion must decode to the same
        Decoded as the prime; EVERY other insertion must be VALUE_UNDECODABLE.
        """
        failures = []
        for n in covered_numbers():
            prime = prime_form(n)
            legal = {tuple(form) for form in span_forms(n)}
            self.assertIn(tuple(prime), legal, f"prime form of {n} is not in its legal set")
            for index in range(len(prime) + 1):
                candidate = insert_and(prime, index)
                got = decode_number_span(list(candidate))
                if tuple(candidate) in legal:
                    if got != Decoded(n, "number_words"):
                        failures.append(("legal insertion misread", n, candidate, got))
                else:
                    if not isinstance(got, Undecodable):
                        failures.append(("illegal insertion accepted", n, candidate, got))
        self.assertEqual(
            first_failures(failures), [], f"{len(failures)} 'and'-position audit failures"
        )

    def test_double_and_insertion_is_undecodable(self):
        """A9: "同一组内双重插入亦然". Take every LEGAL one-'and' form and insert a
        second connector at every index; nothing outside the rule-derived legal
        set may decode."""
        failures = []
        for n in covered_numbers():
            legal = {tuple(form) for form in span_forms(n)}
            for form in span_forms(n):
                if form.count(AND_WORD) == 0:
                    continue
                for index in range(len(form) + 1):
                    candidate = insert_and(form, index)
                    if tuple(candidate) in legal:
                        continue
                    got = decode_number_span(list(candidate))
                    if not isinstance(got, Undecodable):
                        failures.append((n, candidate, got))
        self.assertEqual(
            first_failures(failures), [], f"{len(failures)} double-'and' acceptances"
        )

    def test_negative_half_f6_no_implied_one(self):
        """F6, verbatim from A1/A9. Each of these WAS decodable in the delivered
        implementation (100 / 1000 / 105); the contract never authorized it, and
        TS-4 had already been written to defend the behaviour as correct."""
        for tokens in (["hundred"], ["thousand"], ["hundred", "five"]):
            with self.subTest(tokens=tokens):
                self.assertIsInstance(decode_number_span(list(tokens)), Undecodable)

    def test_negative_half_and_in_an_illegal_position(self):
        for tokens in (
            ["and"],
            ["and", "five"],
            ["two", "and"],
            ["two", "and", "hundred"],
            ["two", "hundred", "and"],
            ["two", "hundred", "and", "and", "five"],
            ["one", "thousand", "and", "two", "hundred"],
            ["two", "hundred", "and", "thousand"],
            ["twenty", "and", "five"],
        ):
            with self.subTest(tokens=tokens):
                self.assertIsInstance(decode_number_span(list(tokens)), Undecodable)

    def test_negative_half_empty_span_and_range_bound(self):
        self.assertIsInstance(decode_number_span([]), Undecodable)
        self.assertNotEqual(decode_number_span([]), Decoded(0, "digits"))
        self.assertNotEqual(decode_number_span([]), Decoded(0, "number_words"))
        self.assertIsInstance(decode_number_span([str(NUMBER_WORD_MAX + 1)]), Undecodable)
        self.assertEqual(decode_number_span([str(NUMBER_WORD_MAX)]), Decoded(NUMBER_WORD_MAX, "digits"))
        self.assertEqual(decode_number_span([str(NUMBER_WORD_MIN)]), Decoded(NUMBER_WORD_MIN, "digits"))

    def test_positive_literals_for_the_and_connector(self):
        self.assertEqual(decode_number_span(["two", "hundred", "and", "five"]), Decoded(205, "number_words"))
        self.assertEqual(decode_number_span(["one", "thousand", "and", "five"]), Decoded(1005, "number_words"))
        self.assertEqual(
            decode_number_span(["one", "thousand", "and", "twenty", "one"]),
            Decoded(1021, "number_words"),
        )

    def test_divergence_the_core_token_table_cannot_drift_from_the_grammar(self):
        """A9's 分家断言. The design writes the right-hand side as
        `set(_ONES_0_19) | set(_TENS)`; importing those private tables would make
        this a same-source assertion, so the right-hand side is this module's own
        independently authored vocabulary. That is strictly stronger: it also
        pins that the shipped table IS the standard English one.

        The content of the assertion is F6: `hundred` and `thousand` are core
        tokens (they can begin/end a number phrase) but are NOT decodable alone.
        """
        singly_decodable = {
            token
            for token in NUMBER_CORE_TOKENS
            if isinstance(decode_number_span([token]), Decoded)
        }
        self.assertEqual(singly_decodable, INDEPENDENT_ONES | INDEPENDENT_TENS)
        self.assertIn(HUNDRED_WORD, NUMBER_CORE_TOKENS)
        self.assertIn(THOUSAND_WORD, NUMBER_CORE_TOKENS)
        self.assertEqual(NUMBER_CONNECTIVE_TOKENS, frozenset({AND_WORD}))
        self.assertEqual(NUMBER_CORE_TOKENS & NUMBER_CONNECTIVE_TOKENS, frozenset())

    def test_is_number_core_token_covers_digit_runs(self):
        self.assertTrue(is_number_core_token("205"))
        self.assertTrue(is_number_core_token("0"))
        self.assertTrue(is_number_core_token(HUNDRED_WORD))
        self.assertTrue(is_number_core_token("twenty"))
        self.assertFalse(is_number_core_token(AND_WORD))
        self.assertFalse(is_number_core_token("sister"))
        self.assertFalse(is_number_core_token(""))

    def test_cheap_independent_invariant_at_most_two_connectors(self):
        """A1's derived post-condition, asserted on the rule-generated corpus and
        on the implementation's answer for it."""
        failures = []
        for n in covered_numbers():
            for form in span_forms(n):
                if form.count(AND_WORD) > 2:
                    failures.append(("renderer", n, form))
                if isinstance(decode_number_span(list(form)), Decoded) and form.count(AND_WORD) > 2:
                    failures.append(("implementation", n, form))
        self.assertEqual(first_failures(failures), [], f"{len(failures)} connector-count violations")


# ===========================================================================
# TS-33 — divergence check for the role manifest, plus the v3 value-type guards
#         and the R5' adjacency / core-token disjointness cells.
#         (design_v3.md §A10, extending the v2 body's items 1-3)
# ===========================================================================
class TS33RoleManifestDivergence(unittest.TestCase):
    """The grid is generated FROM the cue manifest, so widening or narrowing a
    cue set changes the generated cells: coverage cannot drift without a visible
    manifest edit."""

    def _grid(self):
        """Yield (role, cue, tokens, span) cells generated from the manifest."""
        for cue in sorted(STREET_CUES):
            yield (
                SemanticRole.STREET_NUMBER,
                cue,
                ["i", "live", "at", "five", "hundred", cue],
                (3, 5),
            )
        for cue in sorted(TIME_RIGHT_CUES):
            yield (SemanticRole.CLOCK_TIME, cue, ["meet", "me", "at", "five", cue], (3, 4))
        for cue in sorted(CURRENCY_UNIT_CUES):
            yield (
                SemanticRole.MONEY_AMOUNT,
                cue,
                ["transfer", "two", "hundred", cue],
                (1, 3),
            )
        for spelling in sorted(CURRENCY_SPELLINGS):
            tokens = ["transfer", "two", "hundred"] + list(spelling) + ["to", "alice"]
            start = 3
            yield (SemanticRole.CURRENCY, spelling, tokens, (start, start + len(spelling)))
        for cue in sorted(RECIPIENT_LEFT_CUES):
            yield (SemanticRole.RECIPIENT, cue, ["send", cue, "alice", "please"], (2, 3))

    def test_every_manifest_cell_reaches_exactly_its_role(self):
        reached = set()
        failures = []
        for expected_role, cue, tokens, (start, end) in self._grid():
            role, _decoded = role_of(tokens, start, end, role_window=STANDARD_RW)
            reached.add(role)
            if role is not expected_role:
                failures.append((expected_role, cue, tokens[start:end], role))
        self.assertEqual(first_failures(failures), [], f"{len(failures)} manifest cells mis-tagged")
        # Whole-set assertion 1: the implementation reaches every role the
        # manifest declares, and no other.
        self.assertEqual(reached, set(ROLE_RULE_ORDER))

    def test_a_span_with_no_cue_in_either_window_is_undetermined(self):
        role, decoded = role_of(["alpha", "beta", "gamma", "delta"], 1, 2, role_window=STANDARD_RW)
        self.assertIsInstance(decoded, Decoded)
        self.assertIs(role, SemanticRole.UNDETERMINED)

    def test_ordering_pins_the_first_three_rule_order_entries(self):
        street_role, _ = role_of(
            ["i", "live", "at", "five", "hundred", "maple", "street"], 3, 5, role_window=STANDARD_RW
        )
        self.assertIs(street_role, SemanticRole.STREET_NUMBER)
        self.assertIsNot(street_role, SemanticRole.CLOCK_TIME)

        money_role, money_decoded = role_of(
            ["transfer", "two", "hundred", "canadian", "dollars"], 1, 3, role_window=STANDARD_RW
        )
        self.assertIs(money_role, SemanticRole.MONEY_AMOUNT)
        self.assertIsInstance(money_decoded.value, int)

    # --- A10 item 4: value-type guards, one negative cell per numeric role ----
    #
    # ⚠ Measured baseline BEFORE the change (recorded in A10, router's run of the
    #   delivered code):
    #       "my sister street" -> STREET_NUMBER     (no guard)
    #       "my sister pm"     -> CLOCK_TIME        (no guard)
    #       "my sister dollars"-> UNDETERMINED      (guard already present)
    #       "send to five"     -> UNDETERMINED      (guard already present)
    #   So the first two cells are NEW pins; the last two are regression pins.
    def test_street_number_rejects_a_string_valued_span(self):
        role, decoded = role_of(
            ["i", "live", "at", "my", "sister", "street"], 3, 5, role_window=STANDARD_RW
        )
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.UNDETERMINED)
        self.assertIsNot(role, SemanticRole.STREET_NUMBER)

    def test_clock_time_rejects_a_string_valued_span(self):
        role, decoded = role_of(
            ["call", "me", "my", "sister", "pm"], 2, 4, role_window=STANDARD_RW
        )
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.UNDETERMINED)
        self.assertIsNot(role, SemanticRole.CLOCK_TIME)

    def test_money_amount_rejects_a_string_valued_span(self):
        role, decoded = role_of(
            ["transfer", "my", "sister", "dollars"], 1, 3, role_window=STANDARD_RW
        )
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.UNDETERMINED)
        self.assertIsNot(role, SemanticRole.MONEY_AMOUNT)

    def test_recipient_rejects_an_int_valued_span(self):
        """The symmetric cell. ⚠ Honest note: this cell does not DISCRIMINATE
        R5'(ii) from R5'(iii) — any int-decoding span is a number core token by
        definition, so both clauses predict UNDETERMINED here. The (iii)-only pin
        is `test_recipient_rejects_a_span_containing_a_core_token` below."""
        role, decoded = role_of(["send", "to", "five"], 2, 3, role_window=STANDARD_RW)
        self.assertIsInstance(decoded.value, int)
        self.assertIs(role, SemanticRole.UNDETERMINED)
        self.assertIsNot(role, SemanticRole.RECIPIENT)

    # --- A10 item 5: R5' adjacency and core-token disjointness ---------------
    def test_recipient_cue_at_distance_two_no_longer_fires(self):
        """R5'(i): the cue must be LEFT-ADJACENT. Under the v2 rule ("any token
        of left_window"), role_window=2 made this cell a RECIPIENT."""
        role, decoded = role_of(["send", "to", "please", "alice"], 3, 4, role_window=STANDARD_RW)
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.UNDETERMINED)

    def test_recipient_rejects_a_span_containing_a_core_token(self):
        """R5'(iii)."""
        role, decoded = role_of(["send", "to", "ana", "two"], 2, 4, role_window=STANDARD_RW)
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.UNDETERMINED)

    def test_recipient_accepts_a_span_containing_only_the_connective(self):
        """R5'(iii) uses NUMBER_CORE_TOKENS and NOT the connective set: "alice and
        bob" is still a legal recipient, "ana two" is not."""
        role, decoded = role_of(["send", "to", "alice", "and", "bob"], 2, 5, role_window=STANDARD_RW)
        self.assertIsInstance(decoded.value, str)
        self.assertIs(role, SemanticRole.RECIPIENT)


# ===========================================================================
# TS-34 — structural: no default arguments anywhere in gate/.
# ===========================================================================
class TS34NoDefaultArguments(unittest.TestCase):
    def test_no_function_has_a_default_and_no_dataclass_field_has_one(self):
        offenders = []
        for name, path in gate_python_files():
            tree = parse_with_parents(read_source(path), name)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.args.defaults:
                        offenders.append((name, node.name, "positional default"))
                    if any(d is not None for d in node.args.kw_defaults):
                        offenders.append((name, node.name, "keyword-only default"))
                elif isinstance(node, ast.ClassDef) and is_dataclass_decorated(node):
                    for stmt in node.body:
                        if isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                            offenders.append((name, node.name, f"field default: {ast.unparse(stmt)}"))
                        if isinstance(stmt, ast.Assign):
                            offenders.append((name, node.name, f"field assign: {ast.unparse(stmt)}"))
                elif isinstance(node, ast.Call):
                    func = node.func
                    fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                    if fname == "field":
                        for kw in node.keywords:
                            if kw.arg in {"default", "default_factory"}:
                                offenders.append((name, "field()", kw.arg))
        self.assertEqual(offenders, [], "gate/ acquired a default argument (requirement line 13)")


# ===========================================================================
# TS-35 — structural: no confidence-shaped float literal.
# ===========================================================================
class TS35NoConfidenceShapedLiteral(unittest.TestCase):
    SCANNED = ("witness.py", "roles.py", "decision.py", "checks.py")

    def test_float_constants_are_only_the_documented_domain_bounds(self):
        found = {}
        for name in self.SCANNED:
            path = os.path.join(GATE_DIR, name)
            tree = ast.parse(read_source(path), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and type(node.value) is float:
                    found.setdefault(name, set()).add(node.value)
        for name, values in found.items():
            with self.subTest(module=name):
                self.assertTrue(
                    values <= {0.0, 1.0},
                    f"{name} carries threshold-shaped floats: {sorted(values - {0.0, 1.0})}",
                )


# ===========================================================================
# TS-36 — structural: D1 as a compile-time property. UNCHANGED by v2/v3.
# ===========================================================================
class TS36D1CompileTimeProperty(unittest.TestCase):
    SCANNED = ("witness.py", "roles.py", "normalize.py")

    def test_the_witness_pipeline_cannot_import_the_proposal(self):
        offenders = []
        for name in self.SCANNED:
            path = os.path.join(GATE_DIR, name)
            tree = ast.parse(read_source(path), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "proposal" in alias.name.split(".") or alias.name.endswith("Proposal"):
                            offenders.append((name, ast.unparse(node)))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "proposal" in module.split("."):
                        offenders.append((name, ast.unparse(node)))
                    for alias in node.names:
                        if alias.name == "Proposal":
                            offenders.append((name, ast.unparse(node)))
                elif isinstance(node, ast.Name) and node.id == "Proposal":
                    offenders.append((name, "names Proposal"))
                elif isinstance(node, ast.Attribute) and node.attr == "Proposal":
                    offenders.append((name, "names Proposal"))
        self.assertEqual(offenders, [], "D1 red line breached: the witness pipeline can see the proposal")

    def test_generate_witnesses_parameter_names_are_exactly_the_contract_set(self):
        params = set(inspect.signature(generate_witnesses).parameters)
        self.assertEqual(
            params,
            {"transcript", "text_of", "confidence_floor", "max_span_words", "role_window"},
            "A4 states the signature is unchanged; W1a's products are internal, not policy knobs",
        )


# ===========================================================================
# TS-37 — structural: one minting site, one guard, nothing else.
#         (design_v3.md §A7, replacing the v2 flat count)
# ===========================================================================
class TS37OneMintingSiteOneGuard(unittest.TestCase):
    """A7. Classification, not a flat count.

    🔑 Why: a flat count cannot tell the USE of the key from the ENFORCEMENT of
    it, so on a package that structurally needs three references, the cheapest
    way to satisfy "exactly two" is to DELETE THE GUARD. Assertion 2 turns that
    edit red.

    ⚠ Honest scope: this asserts a property of THIS PACKAGE'S SOURCE, not of the
    process. It DETECTS the edit; it does not PREVENT it.
    `object.__new__` + `object.__setattr__`, `unittest.mock.patch`, and anyone who
    can edit `decision.py` are all outside it.
    """

    def _classify(self):
        buckets = {"DEF": [], "GUARD": [], "MINT": [], "OTHER": []}
        for name, path in gate_python_files():
            source = read_source(path)
            tree = parse_with_parents(source, name)
            docstrings = docstring_constant_ids(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "_MINT_KEY":
                    if isinstance(node.ctx, ast.Store):
                        buckets["DEF"].append((name, node))
                        continue
                    parent = getattr(node, "_parent", None)
                    if (
                        isinstance(parent, ast.Compare)
                        and all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops)
                        and (node is parent.left or node in parent.comparators)
                    ):
                        buckets["GUARD"].append((name, node, parent))
                        continue
                    if isinstance(parent, ast.Call) and node in parent.args:
                        buckets["MINT"].append((name, node, parent))
                        continue
                    if isinstance(parent, ast.keyword):
                        grandparent = getattr(parent, "_parent", None)
                        if isinstance(grandparent, ast.Call) and parent.value is node:
                            buckets["MINT"].append((name, node, parent, grandparent))
                            continue
                    buckets["OTHER"].append((name, ast.dump(node)))
                elif isinstance(node, ast.Attribute) and node.attr == "_MINT_KEY":
                    buckets["OTHER"].append((name, "Attribute(_MINT_KEY)"))
                elif (
                    isinstance(node, ast.Constant)
                    and node.value == "_MINT_KEY"
                    and id(node) not in docstrings
                ):
                    buckets["OTHER"].append((name, 'Constant("_MINT_KEY")'))
        return buckets

    def test_assertion_1_exactly_one_module_level_definition(self):
        buckets = self._classify()
        self.assertEqual(len(buckets["DEF"]), 1, buckets["DEF"])
        name, node = buckets["DEF"][0]
        self.assertEqual(name, "decision.py")
        self.assertEqual(enclosing_qualname(node), "", "the key must be module-level")

    def test_assertion_2_exactly_one_forgery_guard_in_post_init(self):
        buckets = self._classify()
        self.assertEqual(len(buckets["GUARD"]), 1, buckets["GUARD"])
        name, node, compare = buckets["GUARD"][0]
        self.assertEqual(name, "decision.py")
        self.assertEqual(enclosing_qualname(node), "ExecuteCapability.__post_init__")
        others = [side for side in [compare.left, *compare.comparators] if side is not node]
        self.assertTrue(
            any(isinstance(side, ast.Name) and side.id == "_mint_key" for side in others),
            "the guard must compare against the InitVar `_mint_key`",
        )

    def test_assertion_3_exactly_one_minting_site_at_e13(self):
        buckets = self._classify()
        self.assertEqual(len(buckets["MINT"]), 1, buckets["MINT"])
        entry = buckets["MINT"][0]
        name, node = entry[0], entry[1]
        self.assertEqual(name, "decision.py")
        self.assertEqual(enclosing_qualname(node), "Gate.evaluate")
        self.assertEqual(len(entry), 4, "the mint must be a keyword argument, not a positional one")
        keyword, call = entry[2], entry[3]
        self.assertEqual(keyword.arg, "_mint_key")
        self.assertTrue(
            isinstance(call.func, ast.Name) and call.func.id == "ExecuteCapability",
            "the sole minting call must construct ExecuteCapability",
        )

    def test_assertion_4_no_other_reference_in_any_form(self):
        buckets = self._classify()
        self.assertEqual(buckets["OTHER"], [], "a fourth reference to the mint key exists")

    def test_assertion_5_containment_no_other_module_may_even_mention_it(self):
        offenders = []
        for name, path in gate_python_files():
            if name == "decision.py":
                continue
            if "_MINT_KEY" in read_source(path):
                offenders.append(name)
        self.assertEqual(offenders, [], "raw-substring containment breached")

    def test_assertion_6_the_key_is_not_exported(self):
        self.assertNotIn("_MINT_KEY", gate.decision.__all__)
        self.assertFalse(hasattr(gate, "_MINT_KEY"))


# ===========================================================================
# TS-38 — structural: the matcher has one caller.
# ===========================================================================
class TS38MatcherHasOneCaller(unittest.TestCase):
    def test_any_value_match_is_referenced_only_from_explain(self):
        references = []
        explain_returns = []
        for name, path in gate_python_files():
            tree = parse_with_parents(read_source(path), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "_any_value_match":
                    references.append((name, enclosing_qualname(node), node))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "explain":
                    explain_returns.append((name, enclosing_qualname(node), node.returns))
        self.assertEqual(len(references), 1, references)
        name, qualname, node = references[0]
        self.assertEqual(qualname, "WitnessSet.explain")
        self.assertIsInstance(getattr(node, "_parent", None), ast.Call)
        self.assertEqual(len(explain_returns), 1, explain_returns)
        _, _, annotation = explain_returns[0]
        rendered = annotation.id if isinstance(annotation, ast.Name) else getattr(annotation, "value", None)
        self.assertEqual(rendered, "BlockReason", "explain must have no expressible 'allow' return")


# ===========================================================================
# TS-39 — VALUE_UNDECODABLE has no truth value.
# ===========================================================================
class TS39UndecodableHasNoTruthValue(unittest.TestCase):
    def test_bool_raises(self):
        with self.assertRaises(TypeError):
            bool(VALUE_UNDECODABLE)

    def test_branching_on_it_raises(self):
        with self.assertRaises(TypeError):
            if VALUE_UNDECODABLE:  # noqa: SIM102 - the crash IS the assertion
                pass

    def test_singleton_and_equality(self):
        self.assertIs(Undecodable(), VALUE_UNDECODABLE)
        self.assertFalse(VALUE_UNDECODABLE == 500)
        self.assertTrue(VALUE_UNDECODABLE == VALUE_UNDECODABLE)


# ===========================================================================
# TS-40 — provenance is carried, and can be made blocking.
# ===========================================================================
class TS40ProvenanceCarriedAndBlocking(unittest.TestCase):
    SENTENCE = "please transfer two hundred canadian dollars to my sister"

    def setUp(self):
        self.transcript = transcript_from_sentence(self.SENTENCE)
        self.proposal = proposal_of(amount=200, currency="CAD", to="my sister")
        self.registry = permissive_registry()

    def test_unknown_provenance_travels_with_an_allow(self):
        verdict = build_gate(self.registry, provenance=PROVENANCE_UNKNOWN).evaluate(
            self.proposal, self.transcript
        )
        self.assertIs(verdict.outcome, Outcome.ALLOW)
        self.assertIsNone(verdict.evidence.provenance.formatting_enabled)

    def test_unknown_provenance_blocks_when_the_caller_demands_it(self):
        verdict = build_gate(
            self.registry, provenance=PROVENANCE_UNKNOWN, require_known_provenance=True
        ).evaluate(self.proposal, self.transcript)
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.TRANSCRIPT_PROVENANCE_UNKNOWN, verdict.reasons)

    def test_known_provenance_satisfies_the_same_switch(self):
        verdict = build_gate(
            self.registry,
            provenance=PROVENANCE_KNOWN_UNFORMATTED,
            require_known_provenance=True,
        ).evaluate(self.proposal, self.transcript)
        self.assertIs(verdict.outcome, Outcome.ALLOW)
        self.assertIs(verdict.evidence.provenance.formatting_enabled, False)


# ===========================================================================
# TS-41 — structural: no network, no file I/O, no third party.
# ===========================================================================
class TS41ImportAllowList(unittest.TestCase):
    ALLOWED = frozenset(
        {"__future__", "dataclasses", "enum", "math", "types", "typing", "collections"}
    )

    def test_every_import_is_on_the_allow_list_or_intra_package(self):
        offenders = []
        for name, path in gate_python_files():
            tree = ast.parse(read_source(path), filename=name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in self.ALLOWED:
                            offenders.append((name, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue  # intra-package relative import
                    module = node.module or ""
                    top = module.split(".")[0]
                    if top not in self.ALLOWED:
                        offenders.append((name, module))
        self.assertEqual(offenders, [], "deny-by-default import allow-list breached")


# ===========================================================================
# TS-42 — the shipped registry's honesty.
# ===========================================================================
class TS42ShippedRegistryHonesty(unittest.TestCase):
    SENTENCE = "please transfer two hundred canadian dollars to my sister"

    def test_shipped_registry_lints_but_fails_the_deployment_profile(self):
        self.assertIsNone(lint_registry(reference_registry(), STANDARD_CHECKERS))
        with self.assertRaises(DeploymentLintError):
            lint_deployment(reference_registry(), STANDARD_CHECKERS)

    def test_shipped_registry_blocks_a_perfectly_grounded_transfer(self):
        verdict = build_gate(reference_registry()).evaluate(
            proposal_of(amount=200, currency="CAD", to="my sister"),
            transcript_from_sentence(self.SENTENCE),
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)
        self.assertIn(BlockReason.CHECK_NOT_IMPLEMENTED, verdict.reasons)


# ===========================================================================
# TS-43 — formatting absorption and cross-side normalization symmetry.
#         (design_v3.md §A8: Part 3 rewritten, Part 5 new)
# ===========================================================================
def _case_variants(surface):
    return [surface, surface.lower(), surface.upper(), surface.title(),
            surface.capitalize(), surface.swapcase()]


def _punctuation_variants(surface):
    out = []
    for char in sorted(STRIPPABLE_PUNCTUATION):
        out.append(char + surface)
        out.append(surface + char)
    return out


_PADS = ("", " ", "  ", "\t", "\n", " \t", "\n ")
_PADS_SMALL = ("", " ", "\t")


def _whitespace_variants(surface, pads=_PADS):
    return [left + surface + right for left in pads for right in pads]


def _base_corpus():
    """Mechanically generated base surface forms: number words (every legal form
    of a loop-chosen integer sample), digit runs, currency codes, currency
    spellings. Not a hand list (DN-1)."""
    bases = []
    for n in (0, 5, 19, 20, 21, 100, 105, 200, 205, 1000, 1005):
        for form in span_forms(n):
            bases.append(" ".join(form))
        bases.append(str(n))
    bases.extend(sorted(CURRENCY_CODES))
    bases.extend(" ".join(spelling) for spelling in sorted(CURRENCY_SPELLINGS))
    return bases


def _all_variants(surface):
    seen = []
    for variant in (
        _case_variants(surface)
        + _punctuation_variants(surface)
        + _whitespace_variants(surface)
    ):
        if variant not in seen:
            seen.append(variant)
    return seen


class TS43FormattingAbsorptionAndSymmetry(unittest.TestCase):
    SENTENCE = "please transfer two hundred canadian dollars to my sister"

    # --- Part 1: the two confirmed rewrite forms are absorbed (R1 / B-23) ----
    def test_part1_documented_formatted_variant_is_indistinguishable(self):
        raw_tokens = self.SENTENCE.split()
        formatted = list(raw_tokens)
        formatted[0] = formatted[0].capitalize()   # "my" -> "My"
        formatted[-1] = formatted[-1] + "."        # "sonny" -> "Sonny."
        raw_projection = witness_projection(
            transcript_from_tokens(raw_tokens), floor=FLOOR_HIGH, k=STANDARD_K, rw=STANDARD_RW
        )
        formatted_projection = witness_projection(
            transcript_from_tokens(formatted), floor=FLOOR_HIGH, k=STANDARD_K, rw=STANDARD_RW
        )
        self.assertEqual(raw_projection, formatted_projection)

        registry = permissive_registry()
        proposal = proposal_of(amount=200, currency="CAD", to="my sister")
        for tokens in (raw_tokens, formatted):
            verdict = build_gate(registry).evaluate(proposal, transcript_from_tokens(tokens))
            self.assertIs(verdict.outcome, Outcome.ALLOW, tokens)

    def test_part1_projection_is_invariant_over_every_token_position(self):
        raw_tokens = self.SENTENCE.split()
        baseline = witness_projection(
            transcript_from_tokens(raw_tokens), floor=FLOOR_HIGH, k=STANDARD_K, rw=STANDARD_RW
        )
        failures = []
        for index in range(len(raw_tokens)):
            variants = [list(raw_tokens)]
            variants[0][index] = raw_tokens[index].capitalize()
            for char in sorted(STRIPPABLE_PUNCTUATION):
                punctuated = list(raw_tokens)
                punctuated[index] = raw_tokens[index] + char
                variants.append(punctuated)
            for tokens in variants:
                got = witness_projection(
                    transcript_from_tokens(tokens), floor=FLOOR_HIGH, k=STANDARD_K, rw=STANDARD_RW
                )
                if got != baseline:
                    failures.append((index, tokens[index], sorted(map(str, got ^ baseline))))
        self.assertEqual(first_failures(failures), [], f"{len(failures)} non-invariant variants")

    # --- Part 2: canonicalize_token is idempotent ---------------------------
    def test_part2_canonicalize_token_is_idempotent(self):
        tokens = set()
        for base in _base_corpus():
            for variant in _all_variants(base):
                tokens.update(variant.split())
        tokens.update(self.SENTENCE.split())
        failures = [t for t in sorted(tokens) if canonicalize_token(canonicalize_token(t)) != canonicalize_token(t)]
        self.assertEqual(first_failures(failures), [], f"{len(failures)} non-idempotent tokens")

    # --- Part 3a: proposal-side variant invariance (this IS R3's claim) ------
    def test_part3a_proposal_side_variant_invariance_across_every_kind(self):
        failures = []
        for base in _base_corpus():
            for kind in ValueKind:
                expected = decode_argument(base, kind)
                for variant in _all_variants(base):
                    got = decode_argument(variant, kind)
                    if got != expected:
                        failures.append((base, kind.name, repr(variant), got, expected))
        self.assertEqual(
            first_failures(failures),
            [],
            f"{len(failures)} variants whose answer depends on the adversary's cosmetics",
        )

    # --- Part 3b: cross-side agreement, NUMBER ------------------------------
    def test_part3b_number_branch_agrees_with_the_transcript_side_decoder(self):
        failures = []
        for base in _base_corpus():
            for variant in _all_variants(base):
                proposal_side = decode_argument(variant, ValueKind.NUMBER)
                transcript_side = decode_number_span(
                    [canonicalize_token(t) for t in variant.split()]
                )
                if proposal_side != transcript_side:
                    failures.append((repr(variant), proposal_side, transcript_side))
        self.assertEqual(first_failures(failures), [], f"{len(failures)} cross-side disagreements")

    # --- Part 3c: the one asymmetry, ASSERTED rather than smoothed over -----
    def test_part3c_the_two_sides_read_different_vocabularies_on_purpose(self):
        """🔑 This is a difference of VOCABULARY, not of NORMALIZATION, and Part 3
        must say so out loud: the proposal side reads ISO CODES, the transcript
        side reads SPELLINGS and never emits a bare code. A later reader who
        "fixes" this apparent divergence by teaching one side the other's
        vocabulary would be performing a real widening, not a cleanup."""
        for code in sorted(CURRENCY_CODES):
            with self.subTest(code=code):
                self.assertEqual(
                    decode_argument(code, ValueKind.CURRENCY_CODE),
                    Decoded(code, "currency_spelling"),
                )
                self.assertIsInstance(decode_currency_span([code.lower()]), Undecodable)
        for spelling in sorted(CURRENCY_SPELLINGS):
            with self.subTest(spelling=spelling):
                self.assertIsInstance(decode_currency_span(list(spelling)), Decoded)
                self.assertIsInstance(
                    decode_argument(" ".join(spelling), ValueKind.CURRENCY_CODE), Undecodable
                )

    # --- Part 4: the loosening is bounded (B-27's upper bound) --------------
    def test_part4_the_loosening_adds_no_witness(self):
        """R3/A2 changed the READING side. If it had widened the EVIDENCE side,
        the ungrounded arm would flip to ALLOW."""
        registry = permissive_registry()
        gate_obj = build_gate(registry)
        grounded = transcript_from_sentence(self.SENTENCE)
        ungrounded_amount = transcript_from_sentence(
            "please transfer three hundred canadian dollars to my sister"
        )
        ungrounded_currency = transcript_from_sentence(
            "please transfer two hundred dollars to my sister"
        )
        failures = []

        for base, canonical in (("two hundred", 200), ("200", 200)):
            canonical_outcomes = {
                "grounded": gate_obj.evaluate(
                    proposal_of(amount=canonical, currency="CAD", to="my sister"), grounded
                ).outcome,
                "ungrounded": gate_obj.evaluate(
                    proposal_of(amount=canonical, currency="CAD", to="my sister"), ungrounded_amount
                ).outcome,
            }
            variants = (
                _case_variants(base)
                + _punctuation_variants(base)
                + _whitespace_variants(base, _PADS_SMALL)
            )
            for variant in variants:
                proposal = proposal_of(amount=variant, currency="CAD", to="my sister")
                for label, transcript in (("grounded", grounded), ("ungrounded", ungrounded_amount)):
                    got = gate_obj.evaluate(proposal, transcript).outcome
                    if got is not canonical_outcomes[label]:
                        failures.append(("amount", label, repr(variant), got))

        canonical_currency = {
            "grounded": gate_obj.evaluate(
                proposal_of(amount=200, currency="CAD", to="my sister"), grounded
            ).outcome,
            "ungrounded": gate_obj.evaluate(
                proposal_of(amount=200, currency="CAD", to="my sister"), ungrounded_currency
            ).outcome,
        }
        currency_variants = (
            _case_variants("CAD")
            + _punctuation_variants("CAD")
            + _whitespace_variants("CAD", _PADS_SMALL)
        )
        for variant in currency_variants:
            proposal = proposal_of(amount=200, currency=variant, to="my sister")
            for label, transcript in (("grounded", grounded), ("ungrounded", ungrounded_currency)):
                got = gate_obj.evaluate(proposal, transcript).outcome
                if got is not canonical_currency[label]:
                    failures.append(("currency", label, repr(variant), got))

        self.assertEqual(first_failures(failures), [], f"{len(failures)} bounded-loosening failures")
        # The arms must differ, or the whole test would be satisfied by a constant.
        self.assertIs(canonical_currency["grounded"], Outcome.ALLOW)
        self.assertIs(canonical_currency["ungrounded"], Outcome.BLOCK)

    # --- Part 5: whitespace is absorbed identically in all three branches ---
    def test_part5_whitespace_absorption_is_identical_across_branches(self):
        failures = []
        for base in _base_corpus():
            for kind in ValueKind:
                expected = decode_argument(base, kind)
                for variant in _whitespace_variants(base):
                    got = decode_argument(variant, kind)
                    if got != expected:
                        failures.append((base, kind.name, repr(variant), got, expected))
        self.assertEqual(first_failures(failures), [], f"{len(failures)} whitespace asymmetries")

    def test_part5_zero_token_and_multi_token_currency_strings_are_refused(self):
        """The negative assertions that bound Part 5: a string that yields zero
        tokens, or two, must NEVER collapse into a single code."""
        self.assertIsInstance(decode_argument("", ValueKind.CURRENCY_CODE), Undecodable)
        self.assertIsInstance(decode_argument("   ", ValueKind.CURRENCY_CODE), Undecodable)
        for code in sorted(CURRENCY_CODES):
            with self.subTest(code=code):
                self.assertIsInstance(
                    decode_argument(code + " " + code, ValueKind.CURRENCY_CODE), Undecodable
                )
        self.assertIsInstance(decode_argument("c a d", ValueKind.CURRENCY_CODE), Undecodable)
        self.assertIsInstance(decode_argument("cad usd", ValueKind.CURRENCY_CODE), Undecodable)


# ===========================================================================
# TS-44 — recipient over-generation is a CLOSED CLASS.
#         (design_v3.md §A11; router ruling C1 takes the R5 version, the R4
#          version is discarded because F5 measured its third arm to go green
#          under a fix that closes exactly one instance.)
# ===========================================================================
#
# [未执行 · 静态推演] — every EXPECTED literal below is the design's static
# prediction for the POST-change contract. It is settled by A18.1's two-arm
# projection diff. A disagreement is a FINDING: re-derive from A1/A3/A4. Do not
# edit the literal to match the implementation, and do not edit the
# implementation to match the literal.
TS44_EXPECTED = {
    3: {("ana", SemanticRole.RECIPIENT)},
    4: {("ana", SemanticRole.RECIPIENT), (205, SemanticRole.MONEY_AMOUNT)},
    5: {("ana", SemanticRole.RECIPIENT), (205, SemanticRole.MONEY_AMOUNT)},
    6: {("ana", SemanticRole.RECIPIENT), (205, SemanticRole.MONEY_AMOUNT)},
}

# [未执行 · 静态推演] — arm 3's prediction, same status.
TS44_EXPECTED_2 = {
    3: {
        ("alice", SemanticRole.RECIPIENT),
        ("alice and", SemanticRole.RECIPIENT),
        ("alice and bob", SemanticRole.RECIPIENT),
        (500, SemanticRole.MONEY_AMOUNT),
    },
}
TS44_EXPECTED_2[4] = set(TS44_EXPECTED_2[3])
TS44_EXPECTED_2[5] = set(TS44_EXPECTED_2[3])
TS44_EXPECTED_2[6] = set(TS44_EXPECTED_2[3])


class TS44RecipientOverGenerationIsAClosedClass(unittest.TestCase):
    """TI-1 in force: arm 1 and arm 3 assert SET EQUALITY over the whole
    `{(value, role)}` projection. The projection is the ENTIRE witness set, not
    the RECIPIENT slice — so a witness the design never predicted, INCLUDING one
    nobody thought to forbid, turns these arms red. That is the property a
    non-membership assertion structurally cannot have.
    """

    FIXTURE_1 = "pay to ana two hundred and five dollars"
    FIXTURE_2 = "transfer to alice and bob five hundred dollars"
    K_GRID = (3, 4, 5, 6)
    RW_GRID = (1, 2, 3)

    def test_arm1_the_whole_projection_equals_the_predicted_class(self):
        transcript = transcript_from_sentence(self.FIXTURE_1)
        for k in self.K_GRID:
            for rw in self.RW_GRID:
                with self.subTest(max_span_words=k, role_window=rw):
                    got = witness_projection(transcript, floor=FLOOR_LOW, k=k, rw=rw)
                    self.assertEqual(got, TS44_EXPECTED[k])

    def test_arm2_one_member_of_the_class_end_to_end(self):
        """This arm pins ONE member of the class. It is not evidence that the
        class is closed. Arm 1 is the class arm. If arm 1 is ever weakened,
        deleting this arm is the honest move, not keeping it as reassurance.
        """
        transcript = transcript_from_sentence(self.FIXTURE_1)
        gate_obj = build_gate(permissive_registry(), floor=FLOOR_LOW, k=4, rw=STANDARD_RW)
        verdict = gate_obj.evaluate(
            proposal_of(amount=205, currency="CAD", to="two hundred and five"), transcript
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.NO_WITNESS, verdict.reasons)
        # Located precisely on `to`, so this arm cannot be satisfied by an
        # unrelated ungrounded parameter (the fixture also fails to ground CAD).
        self.assertTrue(
            any(
                record.param == "to" and record.reason is BlockReason.NO_WITNESS
                for record in verdict.evidence.records
            ),
            verdict.evidence.records,
        )

    def test_arm3_a_fixture_no_and_grammar_fix_can_touch(self):
        """The discriminating arm. Fixture 2 contains NO number-internal "and",
        so a fix that merely teaches the grammar to read "and" has no effect on
        it whatsoever.

        🔴 This arm states plainly what A4 does NOT buy: the recipient set for
        this fixture is NOT reduced. That is the B-31 residue, and this arm's
        purpose is to make it an ASSERTED LITERAL in the repository instead of a
        sentence in a document.

        改动前实测 (router, 2026-09-02, running the DELIVERED code, role_window=2)
        — comment only, NOT an expectation:
            k=3  -> 9 witnesses; RECIPIENT family: alice, alice and,
                    alice and bob, and, and bob, and bob five;
                    MONEY_AMOUNT: 5, 100, 500
            k=4  -> 11 witnesses (+ alice and bob five, and bob five hundred)
            k=5  -> 13 witnesses (+ alice and bob five hundred,
                    and bob five hundred dollars)
            k=6  -> 14 witnesses (+ alice and bob five hundred dollars)
        🩸 The architect hand-listed this set as 4 members (alice / alice and /
        alice and bob / 500) while the measurement at k=5 is 13 — low by 3.25x —
        in the very reply that laid down DN-1. That is why the measurement lives
        here, in a comment, and the expectation lives in a generated projection.
        """
        transcript = transcript_from_sentence(self.FIXTURE_2)
        for k in self.K_GRID:
            for rw in self.RW_GRID:
                with self.subTest(max_span_words=k, role_window=rw):
                    got = witness_projection(transcript, floor=FLOOR_LOW, k=k, rw=rw)
                    self.assertEqual(got, TS44_EXPECTED_2[k])

    def test_arm3_states_the_residue_it_concedes(self):
        """B-31, made mechanical: a proper prefix of the spoken recipient phrase
        is grounded. The speaker said "to alice and bob"; "alice" is a witness.
        ⚠ Direction: fail-OPEN. Registered `deferred`, NOT bounded-residue.
        Its disposition is the deny-by-default ceiling pinned by TS-42 / TS-47,
        not a rule that closes it."""
        transcript = transcript_from_sentence(self.FIXTURE_2)
        projection = witness_projection(transcript, floor=FLOOR_LOW, k=3, rw=STANDARD_RW)
        recipients = {value for value, role in projection if role is SemanticRole.RECIPIENT}
        self.assertEqual(recipients, {"alice", "alice and", "alice and bob"})


# ===========================================================================
# TS-45 — W5a's set equality.   (design_v3.md §A12)
# ===========================================================================
#
# [未执行 · 静态推演] — post-change prediction for the MONEY_AMOUNT value set.
#
# ⚠ A12 states two readings in one sentence: "k∈{2,3} 时 money 集合为空" and then,
#   in the same sentence, corrects itself — "⚠ k=3 时跨度 (1,4) 恰好等于 run,故
#   k=3 预测为 {205},k=2 才为空". This module takes the ⚠-corrected reading, and
#   says so here rather than silently picking one. A12 itself defers the conflict
#   to the settlement experiment (A18.1); if the executor's arm-2 result
#   contradicts this literal, that is the finding, and the resolution is to
#   re-derive from A4's W1a/W5a rules — not to edit either side into agreement.
TS45_EXPECTED_MONEY = {
    2: set(),
    3: {205},
    4: {205},
}


class TS45SubsumedNumberSpans(unittest.TestCase):
    """W5a: a number span yields a witness only when its bounds EXACTLY equal a
    number-token run. Computed at the TOKEN layer, hence independent of
    `max_span_words`: the policy knob can only make the gate more refusing.

    改动前实测 (router, running the DELIVERED code), comment only, NOT an
    expectation:
        fixture `send two hundred five dollars`, max_span_words=3
        -> MONEY_AMOUNT value set = {5, 100, 105, 200, 205}
           (five values; the speaker said 205. The other four were never spoken.)
    """

    FIXTURE = "send two hundred five dollars"

    def test_money_value_set_equals_the_prediction_for_every_k(self):
        transcript = transcript_from_sentence(self.FIXTURE)
        for k in (2, 3, 4):
            with self.subTest(max_span_words=k):
                projection = witness_projection(
                    transcript, floor=FLOOR_LOW, k=k, rw=STANDARD_RW
                )
                money = {value for value, role in projection if role is SemanticRole.MONEY_AMOUNT}
                self.assertEqual(money, TS45_EXPECTED_MONEY[k])

    def test_subsumed_spans_are_rejected_with_the_subsumed_cause(self):
        result = witness_set_of(
            transcript_from_sentence(self.FIXTURE), floor=FLOOR_LOW, k=STANDARD_K, rw=STANDARD_RW
        )
        subsumed = {
            r.decoded_value for r in result.rejected if r.cause is RejectCause.SUBSUMED
        }
        # "two hundred" (200) and "five" (5) are proper sub-spans of the single
        # run `two hundred five`; "hundred" alone is UNDECODABLE under F6 and so
        # keeps its own cause rather than becoming SUBSUMED.
        self.assertIn(200, subsumed)
        self.assertIn(5, subsumed)
        witness_values = {w.value for w in result.witnesses}
        self.assertNotIn(200, witness_values)
        self.assertNotIn(5, witness_values)

    def test_w5a_runs_after_w5_so_existing_causes_are_untouched(self):
        """A4: W5a runs AFTER W5 on purpose, so a span that already failed the
        confidence gate keeps its original cause and `rejected_for_confidence`
        is unaffected (TS-4 / TS-7 / TS-9 / TS-23 depend on this)."""
        transcript = transcript_from_sentence(
            self.FIXTURE, conf_overrides={1: CONF_LOW, 2: CONF_LOW}
        )
        result = witness_set_of(transcript, floor=FLOOR_HIGH, k=STANDARD_K, rw=STANDARD_RW)
        causes_for_200 = {r.cause for r in result.rejected if r.decoded_value == 200}
        self.assertIn(RejectCause.BELOW_CONFIDENCE_FLOOR, causes_for_200)
        self.assertNotIn(RejectCause.SUBSUMED, causes_for_200)


# ===========================================================================
# TS-46 — the instance the design records is a LITERAL in the test file.
#         (design_v3.md §A12 TS-46; the instance itself is recorded in §A15's
#          B-29 entry and in §A12's TS-45 line.)
# ===========================================================================
#
# [未执行 · 静态推演]
TS46_EXPECTED_PROJECTION = {(205, SemanticRole.MONEY_AMOUNT)}


class TS46DocumentedInstanceIsAnAssertion(unittest.TestCase):
    """The instance recorded in `design_v3.md` — fixture `send two hundred five
    dollars`, `max_span_words=3` — asserted as a SET EQUALITY here.

    Citation, so the two can never drift apart silently:
      · design_v3.md §A15, boundary B-29 ("实测: ... MONEY_AMOUNT 值集合 =
        {5, 100, 105, 200, 205} (五个,说话人只说了 205)") — the PRE-change
        measurement of the delivered code.
      · design_v3.md §A12, TS-45 / TS-46 — the post-change prediction.

    🔑 Why this test exists at all: the moment the implementation changes, this
    test goes red and the document has to be re-derived. A number cannot go on
    reading like a measurement after it has quietly become false. If the
    five-element set ever comes back, B-29's mitigation claim is false and this
    test is what says so.
    """

    FIXTURE = "send two hundred five dollars"
    K = 3

    def test_the_documented_instance_projects_to_exactly_one_witness(self):
        projection = witness_projection(
            transcript_from_sentence(self.FIXTURE), floor=FLOOR_LOW, k=self.K, rw=STANDARD_RW
        )
        self.assertEqual(projection, TS46_EXPECTED_PROJECTION)

    def test_the_pre_change_five_element_money_set_is_gone(self):
        """The same instance, stated on the axis the document stated it on.

        This is a set equality, not a non-membership (TI-1): it fails if the
        money set is the old five, and it also fails if the implementation
        invents a sixth value nobody predicted.
        """
        projection = witness_projection(
            transcript_from_sentence(self.FIXTURE), floor=FLOOR_LOW, k=self.K, rw=STANDARD_RW
        )
        money = {value for value, role in projection if role is SemanticRole.MONEY_AMOUNT}
        self.assertEqual(money, {205})
        # The pre-change measurement, kept as a comment and as a contrast literal
        # only — never as an expectation:  {5, 100, 105, 200, 205}.
        self.assertNotEqual(money, {5, 100, 105, 200, 205})


# ===========================================================================
# TS-47 — B-31's reachability condition is pinned by the DETECTOR, not merely
#         named.   (design_v3.md §A12 TS-47, §A6, §A15 B-31)
# ===========================================================================
def flip_read_back_to_not_required(registry):
    """Rebuild `registry` with every NOT_IMPLEMENTED READ_BACK_CONFIRMED entry
    flipped to NOT_REQUIRED.

    🔴 This function IS the deployment edit that B-31 names as its reachability
    condition. It is written out here so the condition is an executable object in
    the repository rather than a sentence in a document.
    """
    new_actions = {}
    for action_name, spec in registry.actions.items():
        new_params = {}
        for param_name, param in spec.params.items():
            checks = dict(param.checks)
            requirement = checks.get(CheckId.READ_BACK_CONFIRMED)
            if requirement is not None and requirement.status is CheckStatus.NOT_IMPLEMENTED:
                checks[CheckId.READ_BACK_CONFIRMED] = CheckRequirement(
                    CheckStatus.NOT_REQUIRED,
                    "TEST-ONLY flip: this is exactly the edit lint_deployment detects",
                )
            new_params[param_name] = ParamSpec(
                param.name, param.value_kind, param.required_role, checks
            )
        new_actions[action_name] = ActionSpec(spec.name, spec.reversibility, new_params)
    return ActionRegistry(new_actions)


class TS47DeploymentLintPinsB31Reachability(unittest.TestCase):
    """B-31 is a LIVE fail-open. It is registered `deferred`, not
    bounded-residue, because its direction is fail-open and this unit is Tier:
    Heavy. Its disposition is a ceiling — "the shipped configuration BLOCKS" —
    and the ceiling is load-bearing only for as long as three things hold:

      (1) the shipped rationale NAMES the residue where a deployer reads it (A6);
      (2) the boundary records the direction and the reachability condition;
      (3) a test asserts that condition mechanically — this class.

    ⚠ Honest ceiling, carried verbatim: read-back is NOT wired this round. The
    ceiling is "the shipped registry blocks", not "read-back protects you".
    """

    TRUNCATION_FIXTURE = "transfer to alice and bob five hundred canadian dollars"

    def test_the_shipped_registry_fails_the_deployment_profile_and_names_the_entry(self):
        with self.assertRaises(DeploymentLintError) as caught:
            lint_deployment(reference_registry(), STANDARD_CHECKERS)
        message = str(caught.exception)
        self.assertIn("transfer", message)
        self.assertIn("read_back_confirmed", message)

    def test_the_flip_is_exactly_what_the_detector_was_detecting(self):
        flipped = flip_read_back_to_not_required(reference_registry())
        self.assertIsNone(lint_registry(flipped, STANDARD_CHECKERS))
        self.assertIsNone(
            lint_deployment(flipped, STANDARD_CHECKERS),
            "after the flip the deployment profile is silent — which identifies the "
            "flip as the edit it was detecting",
        )

    def test_the_shipped_rationale_names_the_residue_where_a_deployer_reads_it(self):
        """A6: the rationale is where a deployer makes the decision; a footnote in
        the design document is not.

        ⚠ Scope note, stated rather than assumed: A6 replaces "the rationale
        string" and A19 item 8 says "transfer 的 READ_BACK_CONFIRMED rationale"
        without fixing WHICH param carries it. So this asserts the naming at the
        ACTION level (the union over the action's params) plus L6's non-emptiness
        per param. If a future revision fixes the placement per-param, tighten
        this — do not loosen it.
        """
        spec = reference_registry().actions["transfer"]
        rationales = []
        for param in spec.params.values():
            requirement = param.checks[CheckId.READ_BACK_CONFIRMED]
            self.assertIs(requirement.status, CheckStatus.NOT_IMPLEMENTED)
            self.assertNotEqual(requirement.rationale.strip(), "", param.name)
            rationales.append(requirement.rationale)
        union = "\n".join(rationales)
        self.assertIn("B-31", union)
        self.assertIn("lint_deployment", union)

    def test_the_ceiling_holds_while_the_entry_stands(self):
        """The truncated-recipient proposal against the SHIPPED registry: the
        speaker said "to alice and bob", the model proposes "alice"."""
        verdict = build_gate(reference_registry(), floor=FLOOR_LOW).evaluate(
            proposal_of(amount=500, currency="CAD", to="alice"),
            transcript_from_sentence(self.TRUNCATION_FIXTURE),
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)
        self.assertIn(BlockReason.CHECK_NOT_IMPLEMENTED, verdict.reasons)

    def test_the_residue_becomes_reachable_exactly_when_the_entry_is_flipped(self):
        """The paired arm, and the uncomfortable one: with the flip, the
        truncated recipient is ALLOWED. A truncated recipient is a different
        recipient. This assertion is B-31 written down as a fact about the code
        rather than as a caveat in prose — if a future rule ever does close the
        class, THIS test is what goes red and forces the boundary entry to be
        re-derived.
        """
        flipped = flip_read_back_to_not_required(reference_registry())
        verdict = build_gate(flipped, floor=FLOOR_LOW).evaluate(
            proposal_of(amount=500, currency="CAD", to="alice"),
            transcript_from_sentence(self.TRUNCATION_FIXTURE),
        )
        self.assertIs(verdict.outcome, Outcome.ALLOW)
        self.assertIsNotNone(verdict.capability)
        self.assertEqual(verdict.capability.arguments["to"], "alice")



# ===========================================================================
# TS-48 — the ASCII digit gate on the number decoder.
#         (design_v3.md §A20.4 "授权的修法(唯一)" + its 测试钉 TS-48 sketch;
#          §A23.3 behaviour battery; §A24.1 D-2 table; §A24.6.4 point 1.)
# ===========================================================================
#
# WHAT IS PINNED.  A20.4 authorises exactly one predicate for the digit branch
# of `decode_number_span`:
#
#     token.isascii() and token.isdigit()
#
# and states, verbatim, that BOTH connectives carry weight:
#   · drop `isascii()`  -> `'²'.isdigit()` is True while `int('²')`
#     raises ValueError, and A20.4 records that the exception is NOT caught, so
#     it leaves the gate: a crash path on attacker-influenced input.  Dropping
#     `isascii()` ALSO re-opens the second face A20.4 found: arabic-indic /
#     fullwidth / devanagari digits are `isdigit()`-True and `int()` takes them
#     happily, grounding a value that `canonicalize_text` would have refused
#     (`CANONICAL_ALPHABET` is ASCII-only)  ->  fail-open, in conflict with V-4.
#   · drop `isdigit()` for a set-membership test such as
#     `set(s) <= set("0123456789")` -> the empty string satisfies it and
#     `int("")` crashes: A20.4 calls that a NEW fail-open, so `''` is pinned too.
#
# 🔴 TWO MUTATION ARMS, AND THE SECOND ONE IS THE POINT (A20.4, A23.3, A24.6.4).
#     arm `²`      — separates `isascii() and isdigit()` from `isdigit()`.
#     arm `٣٤` — separates it from `isdecimal()` as well.
#   A battery that probes only `²` cannot tell the two candidate predicates
#   apart: A20.4 rejects `isdecimal()` explicitly ("coder 提议的修法
#   `isdecimal()` 不足以关闭它"), and A23.3's table shows why — the arabic-indic,
#   fullwidth and devanagari rows are `isdecimal()`-True.  Those three rows are
#   the physical evidence for the rejection, so at least one of them must be an
#   arm here or the rejection has no nail.
#
# 🔴 NOT DERIVED FROM THE IMPLEMENTATION.  Every literal below is transcribed
#   from the design段 named above; the author of this block did not read
#   `gate/*.py`.  Where the design's TS-48 sketch names the layer loosely, the
#   layer is chosen so the claim is the one the design actually settled:
#     · the eight-token undecodable set is asserted on `decode_number_span`,
#       which is where the predicate lives and where A20.4's `int()` crash and
#       empty-string fail-open both live;
#     · the non-ASCII shapes are ALSO asserted on `decode_span`, which is the
#       column A23.3 measured (six shapes, all UNDECODABLE, plus the ASCII
#       control `34` -> `digits=34`).
#     ⚠ `''` and `'4 2'` are deliberately NOT asserted on `decode_span`: they
#       are ASCII and `CANONICAL_ALPHABET` admits letters, digits and the space
#       (see the TS-4 note in `test_gate_ts01_16.py`), so the TEXT branch's
#       answer for them is a separate question that A23.3 never measured.  The
#       design's TS-48 sketch lists them in one undifferentiated set; splitting
#       by layer is how this file avoids asserting something no measurement or
#       structural argument in the design supports.

# The six non-ASCII TOKEN LITERALS are written as \u escapes on purpose: a bare
# glyph can be silently rewritten in transit, and a fixture that quietly decays
# into an ASCII digit turns a discriminating arm into a tautology that passes.
# (Prose below still shows the glyphs; only the values that get asserted on are
# escaped.)  The isdigit/isdecimal columns are A23.3's, transcribed.
TS48_SUPERSCRIPT_TWO = "\u00b2"            # SUPERSCRIPT TWO      isdigit T · isdecimal F
TS48_VULGAR_HALF = "\u00bd"                # VULGAR FRACTION HALF isdigit F · isnumeric T
TS48_CJK_THREE = "\u4e09"                  # CJK THREE            isdigit F · isnumeric T
TS48_ARABIC_INDIC_THREE = "\u0663"         # ARABIC-INDIC 3       isdigit T · isdecimal T
TS48_ARABIC_INDIC_34 = "\u0663\u0664"      # ARABIC-INDIC 3, 4    isdigit T · isdecimal T
TS48_FULLWIDTH_12 = "\uff11\uff12"         # FULLWIDTH 1, 2       isdigit T · isdecimal T

# [未执行 · 静态推演] — A20.4's TS-48 sketch, transcribed. Left side grounds,
# right side is VALUE_UNDECODABLE and must not raise.
TS48_EXPECTED_NUMBER_DECODE = {
    "42": Decoded(42, "digits"),
    "0": Decoded(0, "digits"),
    TS48_SUPERSCRIPT_TWO: VALUE_UNDECODABLE,
    TS48_VULGAR_HALF: VALUE_UNDECODABLE,
    TS48_CJK_THREE: VALUE_UNDECODABLE,
    TS48_ARABIC_INDIC_THREE: VALUE_UNDECODABLE,
    TS48_FULLWIDTH_12: VALUE_UNDECODABLE,
    TS48_ARABIC_INDIC_34: VALUE_UNDECODABLE,
    "": VALUE_UNDECODABLE,
    "4 2": VALUE_UNDECODABLE,
}

# [未执行 · 静态推演] — A23.3's `decode_span` column, transcribed. The three
# `isdecimal()`-True shapes are listed first because they are the arm that
# rejects `isdecimal()`.
TS48_EXPECTED_SPAN_DECODE = {
    TS48_ARABIC_INDIC_34: VALUE_UNDECODABLE,
    TS48_ARABIC_INDIC_THREE: VALUE_UNDECODABLE,
    TS48_FULLWIDTH_12: VALUE_UNDECODABLE,
    TS48_SUPERSCRIPT_TWO: VALUE_UNDECODABLE,
    TS48_VULGAR_HALF: VALUE_UNDECODABLE,
    TS48_CJK_THREE: VALUE_UNDECODABLE,
    "34": Decoded(34, "digits"),
}

# The policy triple A24.6.2 measured its table under. Stated here, not imported.
TS48_FLOOR = 0.5
TS48_K = 2
TS48_RW = 2


def _ts48_call_or_fail(case, func, token, requirement):
    """Call a one-token decoder, turning a RAISE into a FAILURE, not an ERROR.

    🔴 Load-bearing, not defensive style. Under the `isdigit()` mutation
    `decode_number_span(['\u00b2'])` raises ValueError out of `int()`, and A20.4
    records that the exception is not caught anywhere downstream. An uncaught
    exception is reported by unittest as an ERROR, and an error reads as "the
    test is broken" rather than "the gate is broken". A20.4 states the
    requirement as two claims — "VALUE_UNDECODABLE 且**不抛异常**" — so the crash
    has to land on the assertion axis, in every family that touches this path.
    """
    try:
        return func([token])
    except Exception as exc:  # noqa: BLE001 - the catch IS the assertion
        case.fail(
            "%s([%r]) raised %s: %s — %s"
            % (func.__name__, token, type(exc).__name__, exc, requirement)
        )


class TS48AsciiDigitGateOnTheNumberDecoder(unittest.TestCase):
    """A20.4's `isascii() and isdigit()`, pinned on both connectives.

    改动前实测 (A20.4, router, on the DELIVERED pre-change code) — comment only,
    NOT an expectation:
        transcript ["transfer", "٣٤", "dollars"]
        -> witness set {('34', MONEY_AMOUNT)}, value 34
        while `canonicalize_text` on the same string correctly answered
        VALUE_UNDECODABLE.  `decode_number_span` runs first inside `decode_span`,
        so the ASCII gate downstream never got to be evaluated.
    """

    def _decode_number_or_fail(self, token):
        return _ts48_call_or_fail(
            self, decode_number_span, token,
            "A20.4 requires VALUE_UNDECODABLE without raising",
        )

    def _decode_span_or_fail(self, token):
        return _ts48_call_or_fail(
            self, decode_span, token,
            "A23.3 measured VALUE_UNDECODABLE for every non-ASCII shape",
        )

    def test_number_decoder_answer_for_each_token_class_equals_the_prediction(self):
        """Set equality over the whole enumerated input set (TI-1), not a
        non-membership claim about one bad glyph."""
        observed = {}
        for token in TS48_EXPECTED_NUMBER_DECODE:
            with self.subTest(token=token):
                observed[token] = self._decode_number_or_fail(token)
        self.assertEqual(observed, TS48_EXPECTED_NUMBER_DECODE)

    def test_superscript_two_is_declined_and_does_not_crash(self):
        """MUTATION ARM 1 — the only arm `isdigit()` alone fails.

        `'²'.isdigit()` is True and `int('²')` raises; `isdecimal()`
        is False for it, so this arm alone cannot distinguish the authorised
        predicate from `isdecimal()`. That is what arm 2 is for.
        """
        self.assertIs(self._decode_number_or_fail(TS48_SUPERSCRIPT_TWO), VALUE_UNDECODABLE)
        self.assertIs(self._decode_span_or_fail(TS48_SUPERSCRIPT_TWO), VALUE_UNDECODABLE)

    def test_arabic_indic_digits_are_declined_and_do_not_ground(self):
        """MUTATION ARM 2 — the arm `isdecimal()` ALSO fails, and the reason the
        battery cannot stop at arm 1.

        A20.4: "`'٣'.isdecimal()`、`'１２'.isdecimal()`、
        `'٣٤'.isdecimal()` 均为 True 且仍 ground 成 3 / 12 / 34".
        Under `isdecimal()` these become Decoded(3/12/34, "digits") — grounded,
        no crash, and A20.4 grades that fail-open, not a usability bug.
        """
        for token in (TS48_ARABIC_INDIC_THREE, TS48_ARABIC_INDIC_34, TS48_FULLWIDTH_12):
            with self.subTest(token=token):
                self.assertIs(self._decode_number_or_fail(token), VALUE_UNDECODABLE)
                self.assertIs(self._decode_span_or_fail(token), VALUE_UNDECODABLE)

    def test_empty_token_is_declined_and_does_not_crash(self):
        """A20.4's third rejected candidate: `set(s) <= set("0123456789")` is
        True for `''`, and `int("")` crashes. Pinned so the predicate can never
        be "simplified" into a membership test."""
        self.assertIs(self._decode_number_or_fail(""), VALUE_UNDECODABLE)

    def test_span_decoder_declines_every_non_ascii_shape_measured_by_a23(self):
        """A23.3's `decode_span` column, asserted as a set equality including
        its ASCII control row."""
        observed = {}
        for token in TS48_EXPECTED_SPAN_DECODE:
            with self.subTest(token=token):
                observed[token] = self._decode_span_or_fail(token)
        self.assertEqual(observed, TS48_EXPECTED_SPAN_DECODE)

    def test_positive_control_ascii_digits_still_ground(self):
        """🔴 Without this arm an implementation that refuses EVERYTHING is
        green. The gate is supposed to narrow the accepted set, not empty it."""
        self.assertEqual(decode_number_span(["42"]), Decoded(42, "digits"))
        self.assertEqual(decode_number_span(["0"]), Decoded(0, "digits"))
        self.assertEqual(decode_span(["34"]), Decoded(34, "digits"))

    def test_end_to_end_money_set_is_empty_for_a_non_ascii_digit_transcript(self):
        """A20.4's extra requirement: run the whole pipeline, not just the
        decoder, and assert the MONEY_AMOUNT projection is the EMPTY SET.

        Two fixtures: A20.4's own (`transfer ٣٤ dollars`) and
        A24.6.2's (`send ٣٤ dollars`, measured `{}` post-change).
        """
        for tokens in (
            ["transfer", TS48_ARABIC_INDIC_34, "dollars"],
            ["send", TS48_ARABIC_INDIC_34, "dollars"],
        ):
            with self.subTest(tokens=tokens):
                projection = witness_projection(
                    transcript_from_tokens(tokens),
                    floor=TS48_FLOOR,
                    k=TS48_K,
                    rw=TS48_RW,
                )
                money = {
                    value
                    for value, role in projection
                    if role is SemanticRole.MONEY_AMOUNT
                }
                self.assertEqual(money, set())

    def test_end_to_end_positive_control_still_produces_a_money_witness(self):
        """The paired arm for the end-to-end assertion above."""
        projection = witness_projection(
            transcript_from_tokens(["send", "twenty", "dollars"]),
            floor=TS48_FLOOR,
            k=TS48_K,
            rw=TS48_RW,
        )
        money = {
            (value, role)
            for value, role in projection
            if role is SemanticRole.MONEY_AMOUNT
        }
        self.assertEqual(money, {(20, SemanticRole.MONEY_AMOUNT)})


# ===========================================================================
# TS-48b — D-2: the MEMBER predicate must stay WIDER than the DECODABLE one.
#          (design_v3.md §A24.1 "拆成两个,且【明令】不许再合回去";
#           §A24.3 D-1 "再加一条钉住 D-2 的 run-split 用例";
#           §A24.6.2 fixture table; §A24.6.4 point 1.)
# ===========================================================================
#
# THE DEFECT THIS PINS, in the design's own words:
#
#   `_is_readable_digit_run`  (narrow) "我能不能从这个 token 读出一个值?"
#         -> `token.isascii() and token.isdigit()` -> the digit branch of
#            `decode_number_span`.
#   `_is_number_shaped_token` (wide)   "这个 token 可不可以出现在一个数词短语
#         【内部】?" -> `token.isdigit()` -> `is_number_core_token` -> W1a run
#            boundaries -> W5a `run_bounds`; R5'(iii).
#
#   Sharing one predicate is wrong, and the direction of the damage is
#   counter-intuitive: NARROWING the membership set makes the gate MORE
#   permissive.  A24.1: 成员集合变窄 ⇒ 数词 run 被劈开 ⇒ W5a 的 `run_bounds` 里
#   出现新的精确边界对 ⇒ 原本被判 SUBSUMED 的子跨度升格成 witness.
#   Measured (A24.1 H-1, and again in A24.6.2's table): ∅ -> {(20, MONEY_AMOUNT)}.
#
#   🔑 "成员 ≠ 可解" is not an inconsistency to be tidied away — it is the
#   design's established shape.  F6's precedent: `hundred` / `thousand` ARE core
#   tokens and NEVER decode (pinned above in this same module).
#
# 🔴 WHY THIS FAMILY EXISTS AT ALL (A24.6.4 point 1, verbatim): "谁把
#   `_is_number_shaped_token` 收窄回 `isascii() and isdigit()`,133 个测试一个
#   都不会红."  A24.6.2's table is A MEASUREMENT, NOT A GATE.  This class is the
#   gate.

# [未执行 · 静态推演] — A24.6.2's fixture table, transcribed. The middle column
# ("合并谓词时") is recorded as a comment inside the class, never as an
# expectation.
TS48B_EXPECTED_MONEY_SPLIT_RUN = set()
TS48B_EXPECTED_MONEY_CONTROL = {(20, SemanticRole.MONEY_AMOUNT)}
TS48B_EXPECTED_FULL_PROJECTION_RECIPIENT = {("alice", SemanticRole.RECIPIENT)}


class TS48bMemberPredicateStaysWiderThanDecodable(unittest.TestCase):
    """D-2: narrowing the membership predicate would WIDEN the gate.

    改动前实测 (A24.6.2, router) — comment only, NOT an expectation:
        fixture ["send", "٣٤", "twenty", "dollars"], k=2, rw=2,
        floor=0.5
        · split predicates (today):  MONEY projection = {}
        · merged predicate:          MONEY projection = {(20, MONEY_AMOUNT)}
        The speaker never said twenty-as-an-amount on its own; the `٣٤`
        token splits the `٣٤ twenty` run in two, and the fragment
        `twenty` — previously SUBSUMED — is promoted to a witness.
    """

    SPLIT_RUN_FIXTURE = ["send", TS48_ARABIC_INDIC_34, "twenty", "dollars"]
    # m-3 (R7 architect): the MIRROR position. The fixture above puts the
    # unreadable token BEFORE the number word, which exercises run EXTENSION;
    # this one puts it AFTER, which exercises the run TRIM loops instead -- a
    # distinct route to the same widening, previously unexercised by any test.
    # Measured over a 1140-cell wide-vs-narrow sweep before being written down:
    #   wide (shipped) -> MONEY {}          narrow (merged) -> MONEY {(20, ...)}
    MIRROR_RUN_FIXTURE = ["send", "twenty", TS48_ARABIC_INDIC_34, "dollars"]
    CONTROL_FIXTURE = ["send", "twenty", "dollars"]
    RECIPIENT_FIXTURE = ["transfer", TS48_ARABIC_INDIC_34, "to", "alice"]

    def _money(self, tokens):
        projection = witness_projection(
            transcript_from_tokens(tokens), floor=TS48_FLOOR, k=TS48_K, rw=TS48_RW
        )
        return {
            (value, role)
            for value, role in projection
            if role is SemanticRole.MONEY_AMOUNT
        }

    def test_a_non_ascii_token_inside_a_number_run_yields_no_money_witness(self):
        """The D-2 arm. Set equality over the MONEY projection (TI-1): it fails
        if `{(20, MONEY_AMOUNT)}` comes back, and it also fails if some third
        value nobody predicted appears."""
        self.assertEqual(self._money(self.SPLIT_RUN_FIXTURE), TS48B_EXPECTED_MONEY_SPLIT_RUN)

    def test_the_mirror_position_also_yields_no_money_witness(self):
        """m-3. Same claim as the arm above, but the unreadable token sits to the
        RIGHT of the number word, so the widening arrives through the trim loops
        (`_number_token_runs` walks `start` forward and `end` backward until both
        land on core tokens) rather than through block extension.

        🔑 Why this is a separate test and not a subtest of the one above: the
        two inputs reach `run_bounds` by DIFFERENT code paths, so a mutation that
        breaks only one of them would be hidden if a single assertion covered
        both. Expected value taken from the design's wide/narrow sweep, not from
        running this implementation."""
        self.assertEqual(self._money(self.MIRROR_RUN_FIXTURE), TS48B_EXPECTED_MONEY_SPLIT_RUN)

    def test_the_same_sentence_without_the_foreign_digit_still_grounds_twenty(self):
        """🔴 The control that makes the arm above mean something. Without it,
        an implementation that suppresses every MONEY witness is green, and a
        green arm titled "fail-open closed" is worse than no arm (TI-1)."""
        self.assertEqual(self._money(self.CONTROL_FIXTURE), TS48B_EXPECTED_MONEY_CONTROL)

    def test_recipient_tagging_is_not_collateral_damage(self):
        """The second control (A24.6.2's last row): R5'(iii) consults the WIDE
        predicate too, so a change there could silently delete recipients.
        Asserted as the FULL projection, so an extra witness fails it as loudly
        as a missing one."""
        projection = witness_projection(
            transcript_from_tokens(self.RECIPIENT_FIXTURE),
            floor=TS48_FLOOR,
            k=TS48_K,
            rw=TS48_RW,
        )
        self.assertEqual(projection, TS48B_EXPECTED_FULL_PROJECTION_RECIPIENT)

    def test_the_two_predicates_disagree_on_at_least_one_token(self):
        """The invariant stated as an observation about the public surface: the
        MEMBERSHIP predicate must admit a token the DECODER refuses.

        `is_number_core_token` is the public face of the wide predicate; the
        narrow one is private, so its refusal is observed through
        `decode_number_span`. If the two are ever merged, the token below stops
        being a member and this goes red — which is the whole point, since
        A24.6.2 records that today NOTHING goes red on that edit.

        F6 supplies a second, ASCII witness of the same "member but not
        decodable" shape (`hundred`), so this does not rest on one glyph.
        """
        for token in (TS48_ARABIC_INDIC_34, TS48_FULLWIDTH_12, TS48_SUPERSCRIPT_TWO):
            with self.subTest(token=token):
                self.assertTrue(
                    is_number_core_token(token),
                    "%r must remain a number-core token: narrowing the "
                    "membership set splits number runs and PROMOTES subsumed "
                    "sub-spans to witnesses (A24.1)" % (token,),
                )
                self.assertIs(
                    _ts48_call_or_fail(
                        self, decode_number_span, token,
                        "a MEMBER token that the decoder must still refuse",
                    ),
                    VALUE_UNDECODABLE,
                )
        self.assertTrue(is_number_core_token("hundred"))
        self.assertIs(
            _ts48_call_or_fail(
                self, decode_number_span, "hundred",
                "F6's ASCII instance of the same member-but-not-decodable shape",
            ),
            VALUE_UNDECODABLE,
        )

if __name__ == "__main__":  # pragma: no cover - convenience entry point
    unittest.main(verbosity=2)
