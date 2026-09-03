"""Test specifications TS-1 .. TS-16 for the voice-action grounding gate.

Scope: this file implements exactly TS-1 through TS-16 of
`design_v3.md` (= design_v2 body + the authoritative `v3 权威修订段` A0-A19).
Where the body and the amendment section disagree, the amendment section wins;
the only amendment that reaches this range is A13 (TS-4's money-witness
assertion).  TS-17 and beyond are written by other paths and are not touched
here.

Discipline notes carried from the design:
  * Every threshold in this file is a test-module local constant that is passed
    into `Gate(...)`.  Nothing threshold-shaped is imported from `gate/`
    (requirement line 21 / TS-34's spirit).
  * Closed vocabularies (`CheckId`, `STANDARD_CHECKERS`) are enumerated
    mechanically, never transcribed into a hand list: a hand list silently
    loses coverage when the table moves (design DN-1 / TI-1).
  * A red test here is a finding to report, not permission to edit the test or
    the implementation until they agree.

⚠ Fixture helpers (`w`, `transcript_of`, the registry builders) may overlap with
the TS-17+ paths; router to collapse the duplication.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
import unittest
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from gate import decision as decision_module
from gate.checks import STANDARD_CHECKERS
from gate.decision import Gate
from gate.errors import DeploymentLintError, RegistryLintError
from gate.normalize import Decoded, ValueKind, canonicalize_token, decode_span
from gate.proposal import Proposal
from gate.reasons import BlockReason, Outcome
from gate.registry import (
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
from gate.roles import SemanticRole
from gate.transcript import TranscriptProvenance, parse_transcript, raw_text_of
from gate.witness import RejectCause, RejectedSpan, Span, WitnessSet, generate_witnesses

# ---------------------------------------------------------------------------
# Test-module policy locals.  None of these is imported from `gate/`; the whole
# point of requirement line 33 is that a threshold is something the caller had
# to type, so the tests type it too.
# ---------------------------------------------------------------------------
FLOOR_HIGH = 0.90
FLOOR_LOW = 0.40
LOW = 0.42
HIGH_CONF = 0.99

MAX_SPAN_WORDS = 3
ROLE_WINDOW = 2
MAX_TRANSCRIPT_WORDS = 200

PROVENANCE = TranscriptProvenance("text", None, "raw_text_of")

RATIONALE = "not required in this test fixture"
RATIONALE_REQUIRED = "grounding is exercised by this fixture"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
def w(text: str, conf: float, final: bool = True, index: int = 0) -> dict[str, object]:
    """The design's shared fixture helper (`## Test Specifications` preamble).

    `index` is the word's position in the utterance; the design writes the
    timings as `start = i*100`, `end = i*100 + 90`.
    """
    return {
        "text": text,
        "start": index * 100,
        "end": index * 100 + 90,
        "confidence": conf,
        "word_is_final": final,
    }


def transcript_of(
    sentence: str,
    *,
    conf: float = HIGH_CONF,
    final: bool = True,
    low_conf_tokens: Iterable[str] = (),
    low_conf: float = LOW,
):
    """Build a parsed Transcript from a whitespace-separated sentence.

    `low_conf_tokens` selects by token text rather than by a hand-written index
    list, so re-wording a fixture cannot silently move the low-confidence words
    somewhere else.
    """
    low = frozenset(low_conf_tokens)
    raw = [
        w(tok, low_conf if tok in low else conf, final, i)
        for i, tok in enumerate(sentence.split())
    ]
    return parse_transcript(raw)


PARAM_SHAPE: tuple[tuple[str, ValueKind, SemanticRole], ...] = (
    ("amount", ValueKind.NUMBER, SemanticRole.MONEY_AMOUNT),
    ("currency", ValueKind.CURRENCY_CODE, SemanticRole.CURRENCY),
    ("to", ValueKind.TEXT, SemanticRole.RECIPIENT),
)


def all_not_required() -> dict[CheckId, CheckRequirement]:
    """Every key of the closed `CheckId` enum, NOT_REQUIRED with a rationale.

    Enumerated from the enum itself: lint rule L2 demands total coverage, and a
    hand-written literal would stop covering a check the day one is added.
    """
    return {cid: CheckRequirement(CheckStatus.NOT_REQUIRED, RATIONALE) for cid in CheckId}


def grounding_checks() -> dict[CheckId, CheckRequirement]:
    """The TS-17 shape: every check that HAS an implementation is REQUIRED, and
    every remaining key of the closed enum is NOT_REQUIRED with a rationale.

    Both halves are derived mechanically -- the REQUIRED set from
    `STANDARD_CHECKERS.keys()` (so lint L1 can never be tripped by this fixture)
    and the remainder from `CheckId` (so lint L2 can never be tripped either).
    """
    checks: dict[CheckId, CheckRequirement] = {}
    for cid in CheckId:
        if cid in STANDARD_CHECKERS:
            checks[cid] = CheckRequirement(CheckStatus.REQUIRED, RATIONALE_REQUIRED)
        else:
            checks[cid] = CheckRequirement(CheckStatus.NOT_REQUIRED, RATIONALE)
    return checks


def make_registry(
    checks_for: Callable[[str], Mapping[CheckId, CheckRequirement]],
    *,
    reversibility: Reversibility = Reversibility.IRREVERSIBLE,
    action: str = "transfer",
) -> ActionRegistry:
    params = {
        name: ParamSpec(
            name=name,
            value_kind=kind,
            required_role=role,
            checks=MappingProxyType(dict(checks_for(name))),
        )
        for name, kind, role in PARAM_SHAPE
    }
    spec = ActionSpec(
        name=action,
        reversibility=reversibility,
        params=MappingProxyType(params),
    )
    return ActionRegistry(actions=MappingProxyType({action: spec}))


def grounding_registry() -> ActionRegistry:
    return make_registry(lambda _name: grounding_checks())


def build_gate(
    registry: ActionRegistry,
    *,
    confidence_floor: float = FLOOR_HIGH,
    max_span_words: int = MAX_SPAN_WORDS,
    role_window: int = ROLE_WINDOW,
    max_transcript_words: int = MAX_TRANSCRIPT_WORDS,
    require_known_provenance: bool = False,
    checkers: Mapping[CheckId, Any] = STANDARD_CHECKERS,
) -> Gate:
    return Gate(
        registry=registry,
        checkers=checkers,
        text_of=raw_text_of,
        provenance=PROVENANCE,
        confidence_floor=confidence_floor,
        max_span_words=max_span_words,
        role_window=role_window,
        max_transcript_words=max_transcript_words,
        require_known_provenance=require_known_provenance,
    )


def witnesses_for(transcript, *, confidence_floor: float = FLOOR_HIGH) -> WitnessSet:
    """Generate a witness set with the standard policy, independently of the Gate."""
    return generate_witnesses(
        transcript,
        text_of=raw_text_of,
        confidence_floor=confidence_floor,
        max_span_words=MAX_SPAN_WORDS,
        role_window=ROLE_WINDOW,
    )


def proposal_of(**arguments: object) -> Proposal:
    return Proposal(action="transfer", arguments=dict(arguments))


def records_for(verdict, param: str) -> tuple:
    return tuple(r for r in verdict.evidence.records if r.param == param)


def money_values(ws: WitnessSet) -> set:
    return {x.value for x in ws.witnesses if x.role is SemanticRole.MONEY_AMOUNT}


# Shared fixture sentences, quoted verbatim from the design.
TS1_SENTENCE = "please transfer two hundred canadian dollars to my sister"
TS2_SENTENCE = (
    "i live at five hundred maple street "
    "please transfer two hundred canadian dollars to my sister"
)
TS4_SENTENCE = "please transfer a couple hundred canadian dollars to my sister"
TS6_SENTENCE = "please transfer two hundred dollars to my sister"

GROUNDED_PROPOSAL = dict(amount=200, currency="CAD", to="my sister")


# ===========================================================================
# TS-1
# ===========================================================================
# 🔴 **Mutation:** in `check_role_match` and `check_witness_present`, replace the
# body with `return CheckOk()`. Test must go red (verdict becomes ALLOW).
# Narrower single-line variant: in `WitnessSet.satisfies`, `return True`.
#
# ⇒ Neutering either checker, or making `satisfies` constantly true, makes this
#   test red: the fabricated amount would stop producing NO_WITNESS.
class TestTS01FabricatedAmount(unittest.TestCase):
    """TS-1 — (a) fabricated amount."""

    def test_fabricated_amount_blocks_with_no_witness(self) -> None:
        gate = build_gate(grounding_registry())
        transcript = transcript_of(TS1_SENTENCE)
        verdict = gate.evaluate(
            proposal_of(amount=500, currency="CAD", to="my sister"), transcript
        )

        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)
        self.assertIn(BlockReason.NO_WITNESS, verdict.reasons)
        # Nothing in the transcript decodes to 500 at all, which is what
        # distinguishes (a) from (b).
        self.assertNotIn(BlockReason.ROLE_MISMATCH, verdict.reasons)


# ===========================================================================
# TS-2
# ===========================================================================
# 🔴 **Mutation:** in `WitnessSet.satisfies`, change the predicate from
# `w.value == value and w.role is role` to `w.value == value`. That single edit
# *is* the matcher. Test must go red. Second mutation: reorder `ROLE_RULE_ORDER`
# so `MONEY_AMOUNT` precedes `STREET_NUMBER` — TS-33 assertion 3 also fires.
#
# ⇒ Dropping the role half of the predicate, or reordering ROLE_RULE_ORDER so
#   the street number is tagged as money, makes this test red.
class TestTS02DiscriminatingArm(unittest.TestCase):
    """TS-2 — (b) D1 discriminating arm. The one that matters. 🔴 UNCHANGED BY v2."""

    def setUp(self) -> None:
        self.gate = build_gate(grounding_registry())
        self.transcript = transcript_of(TS2_SENTENCE)

    def test_1_blocks_and_mints_nothing(self) -> None:
        verdict = self.gate.evaluate(
            proposal_of(amount=500, currency="CAD", to="my sister"), self.transcript
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)

    def test_2_block_came_from_the_role_not_from_decoding(self) -> None:
        verdict = self.gate.evaluate(
            proposal_of(amount=500, currency="CAD", to="my sister"), self.transcript
        )
        self.assertIn(BlockReason.ROLE_MISMATCH, verdict.reasons)
        self.assertNotIn(BlockReason.NO_WITNESS, verdict.reasons)

    def test_3_the_witness_set_does_contain_500_but_not_as_money(self) -> None:
        ws = witnesses_for(self.transcript)
        self.assertTrue(any(x.value == 500 for x in ws.witnesses))
        self.assertFalse(
            any(
                x.value == 500 and x.role is SemanticRole.MONEY_AMOUNT
                for x in ws.witnesses
            )
        )
        five_hundreds = [x for x in ws.witnesses if x.value == 500]
        self.assertTrue(five_hundreds)
        for witness in five_hundreds:
            self.assertIs(witness.role, SemanticRole.STREET_NUMBER)

    def test_4_paired_arm_the_fixture_is_not_blocking_for_an_unrelated_reason(self) -> None:
        verdict = self.gate.evaluate(proposal_of(**GROUNDED_PROPOSAL), self.transcript)
        self.assertIs(verdict.outcome, Outcome.ALLOW)


# ===========================================================================
# TS-3
# ===========================================================================
def naive_match(transcript, value, *, max_span_words: int = MAX_SPAN_WORDS) -> bool:
    """A working matcher, written in the test file rather than imported.

    Value-only membership over exactly the spans W2 enumerates, role ignored.
    It is deliberately NOT built on `generate_witnesses`: the whole content of
    TS-3 is that a matcher and this gate disagree on the same fixture, so the
    matcher must not inherit the gate's role logic.
    """
    tokens = [canonicalize_token(raw_text_of(word)) for word in transcript.words]
    n = len(tokens)
    for i in range(n):
        for j in range(i + 1, min(n, i + max_span_words) + 1):
            decoded = decode_span(tokens[i:j])
            # `isinstance`, never `if decoded:` -- Undecodable.__bool__ raises.
            if isinstance(decoded, Decoded) and decoded.value == value:
                return True
    return False


# 🔴 **Mutation:** same as TS-2's first mutation — the two assertions become
# consistent and the test goes red.
#
# ⇒ Collapsing `satisfies` into value-only membership makes the gate agree with
#   `naive_match`, and this test — which asserts they disagree — goes red.
class TestTS03MatcherOracle(unittest.TestCase):
    """TS-3 — (b) matcher oracle, written into the test file. 🔴 UNCHANGED BY v2."""

    def test_matcher_says_yes_and_the_gate_says_block(self) -> None:
        transcript = transcript_of(TS2_SENTENCE)
        gate = build_gate(grounding_registry())
        verdict = gate.evaluate(
            proposal_of(amount=500, currency="CAD", to="my sister"), transcript
        )
        self.assertTrue(naive_match(transcript, 500))
        self.assertIs(verdict.outcome, Outcome.BLOCK)


# ===========================================================================
# TS-4   (A13 replaces the money-witness clause: EMPTY, not 100)
# ===========================================================================
# 🔴 **Mutation:** in `decode_number_span`, replace the `return VALUE_UNDECODABLE`
# exit with a best-effort return of the partial accumulator
# (`Decoded(value=partial, decoder_id="fallback")`). "a couple hundred" then
# yields 200 and the verdict becomes ALLOW. Test must go red. This is the exact
# mutation the "no fallback return value" red line forbids.
#
# ⇒ Any partial-accumulator fallback in `decode_number_span` grounds 200 and
#   makes this test red.
class TestTS04SpanTheNormalizerCannotRead(unittest.TestCase):
    """TS-4 — (c1) transcript span the normalizer cannot read.

    A13 (v3) replaces this test's money clause.  v2 asserted "the only money
    witness present is 100 (from the bare 'hundred')"; F6 removed the implied
    one, so a bare `hundred` is VALUE_UNDECODABLE and "a couple hundred" grounds
    nothing at all.  The money-witness set must therefore be EMPTY.
    """

    def setUp(self) -> None:
        self.transcript = transcript_of(TS4_SENTENCE)
        self.gate = build_gate(grounding_registry())
        self.verdict = self.gate.evaluate(
            proposal_of(**GROUNDED_PROPOSAL), self.transcript
        )
        self.ws = witnesses_for(self.transcript)

    def test_blocks_with_no_witness(self) -> None:
        self.assertIs(self.verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.NO_WITNESS, self.verdict.reasons)

    def test_the_unreadable_span_is_rejected_as_undecodable(self) -> None:
        # ⚠ FINDING CANDIDATE, recorded here rather than smoothed away.
        # Derived statically from the v3 contract, NOT from the implementation:
        # `decode_span` tries decode_number_span -> decode_currency_span ->
        # canonicalize_text, and "couple hundred" is all-lowercase letters plus a
        # space, i.e. entirely inside CANONICAL_ALPHABET.  canonicalize_text
        # therefore succeeds, so W4 never fires for that span and its cause
        # should be ROLE_UNDETERMINED, not UNDECODABLE.  The assertion below is
        # written exactly as the design specifies it; if it is red, the finding
        # belongs to TS-4 / A13, and neither this test nor decode_span may be
        # bent until they agree.
        #
        # ── A24.6 期望值更正(2026-09-02)────────────────────────────────
        # 原写 `RejectCause.UNDECODABLE`,理由见本测试**自己上方那段静态推导**:
        # 那段推导逐字写着「its cause should be ROLE_UNDETERMINED, not
        # UNDECODABLE」,而底下的断言写的却是 UNDECODABLE —— 红的是【期望值】,
        # 不是实现。上面那段注释一个字未删:它是这次更正的证据本身,删了就看不出
        # 「正确答案早就写在测试里、只是没写进断言」这件事是怎么发生的。
        # ⚠ 方法名**刻意保持不变**:它是 design_v3.md / amendments_v3.md /
        #   arm1-tests-NOTES.md / run.json 四处「那条已知的红」的可 grep 锚点,
        #   改名会让那些指针静默失准(A24.6 记的正是这个病)。
        self.assertTrue(
            any(
                r.cause is RejectCause.ROLE_UNDETERMINED
                and r.span.text == "couple hundred"
                for r in self.ws.rejected
            ),
            "TS-4 requires a RejectedSpan(ROLE_UNDETERMINED) whose span text is "
            "'couple hundred'; observed causes for that span text: "
            + repr(
                sorted(
                    {r.cause.name for r in self.ws.rejected if r.span.text == "couple hundred"}
                )
            ),
        )

    # A24.6 追加的三条 needle。放在独立的用例里(而不是并进上面那条)有两个理由:
    #   ① 上面那条更正的效果必须单独可见 —— 与新 needle 混在一个方法里,它转绿
    #      就会被新 needle 的红盖掉;
    #   ② 三条 needle 各自 subTest,谁红谁报,不互相遮蔽。
    # 载体句刻意与 TS4_SENTENCE 【逐字同框】,只把 "couple hundred" 换成 needle,
    # 于是唯一的自变量就是 needle 本身。
    W4_NEEDLE_FRAME = "please transfer a {needle} canadian dollars to my sister"
    ADDITIONAL_W4_NEEDLES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("non-ASCII letter", ("señora",)),
        ("multi-token non-ASCII", ("café", "au", "lait")),
        ("hyphenated", ("twenty-five",)),
    )

    def test_a24_6_additional_needles_are_genuine_w4_needles(self) -> None:
        """三条 A24.6 追加的 needle,期望落在 UNDECODABLE —— 它们是**真 W4 needle**。

        🩸 **本方法的期望值被改过一次,而改的理由是【派单错了】,不是实现错了。**
        派单原写「它们也应当判 ROLE_UNDETERMINED」;写这条测试的 agent 实测三条全是
        UNDECODABLE,并**拒绝改期望值去迁就**、原样报成 finding —— 那是对的。

        判别链两侧落点相反,回源核过(`CANONICAL_ALPHABET` 是纯 ASCII):
          * `couple hundred` —— 小写字母 + 空格,**全在**字母表内 ⇒ canonicalize_text
            成功 ⇒ W4 不触发 ⇒ ROLE_UNDETERMINED。它是 TS-4 的一条**坏** needle
            (TS-4 讲的是「归一器读不出来的跨度」,而这条其实读得出来),
            所以上一条方法把它的期望值从 UNDECODABLE 改成了 ROLE_UNDETERMINED。
          * `señora` / `café au lait` / `twenty-five` —— 分别含 `ñ` / `é` / `-`,
            三个字符**都不在**字母表内 ⇒ canonicalize_text 失败 ⇒ W4 触发 ⇒ UNDECODABLE。
            它们才是 TS-4 本来要的那种 needle。
        设计 A23.3 独立测过同一件事(`señora` 判 UNDECODABLE),与此一致。

        ⚠ 期望值取自上面这条推导 + A23.3,**不是**从实现读回来的。
        """
        for label, tokens in self.ADDITIONAL_W4_NEEDLES:
            needle = " ".join(tokens)
            with self.subTest(needle=needle, shape=label):
                ws = witnesses_for(
                    transcript_of(self.W4_NEEDLE_FRAME.format(needle=needle))
                )
                observed = sorted(
                    {r.cause.name for r in ws.rejected if r.span.text == needle}
                )
                grounded = sorted(
                    {
                        (repr(x.value), x.role.name)
                        for x in ws.witnesses
                        if x.span.text == needle
                    }
                )
                self.assertTrue(
                    any(
                        r.cause is RejectCause.UNDECODABLE
                        and r.span.text == needle
                        for r in ws.rejected
                    ),
                    "needle %r (%s) should be rejected as UNDECODABLE (it is a "
                    "genuine W4 needle: it contains a character outside "
                    "CANONICAL_ALPHABET, so canonicalize_text must fail); "
                    "observed reject causes for that span text: %r; "
                    "witnesses grounded from that span text: %r"
                    % (needle, label, observed, grounded),
                )
                # 反向断言:它【不】应当是 ROLE_UNDETERMINED —— 少了这一半,
                # 一个把两种 cause 都塞进 rejected 的实现也会绿。
                self.assertNotIn(
                    "ROLE_UNDETERMINED", observed,
                    "needle %r (%s) reached the role stage, so W4 did not fire on "
                    "it — that contradicts it being unreadable. causes: %r"
                    % (needle, label, observed),
                )
                # 正对照:它不该 ground 出任何东西。
                self.assertEqual(
                    grounded, [],
                    "needle %r (%s) grounded a witness despite being unreadable: %r"
                    % (needle, label, grounded),
                )

    def test_a13_the_money_witness_set_is_empty(self) -> None:
        self.assertEqual(money_values(self.ws), set())


# ===========================================================================
# TS-5
# ===========================================================================
# 🔴 **Mutation:** in E8, change `if isinstance(decoded, Undecodable):
# reasons.append(...); continue` to `decoded = Decoded(proposal.arguments[name],
# "raw")`. Red. Second mutation: drop the `type(raw) is bool` guard in
# `decode_argument` → the `True` case decodes to 1 and stops reporting
# `ARGUMENT_UNDECODABLE`. Red. Third mutation: make `canonicalize_token` strip
# punctuation from anywhere rather than from the ends → the third half goes red.
#
# ⇒ Giving E8 a fallback decode, dropping the bool guard, or widening
#   canonicalize_token to strip interior punctuation each makes this test red.
class TestTS05ArgumentTheNormalizerCannotRead(unittest.TestCase):
    """TS-5 — (c2) proposal argument the normalizer cannot read."""

    def setUp(self) -> None:
        self.transcript = transcript_of(TS1_SENTENCE)
        self.gate = build_gate(grounding_registry())

    def _evaluate(self, amount: object):
        return self.gate.evaluate(
            proposal_of(amount=amount, currency="CAD", to="my sister"), self.transcript
        )

    def test_first_half_undecodable_string_argument(self) -> None:
        verdict = self._evaluate("a couple hundred")
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.ARGUMENT_UNDECODABLE, verdict.reasons)
        self.assertIsNone(verdict.capability)
        # E8 `continue`d, so no check was even consulted for an undecodable
        # argument.
        self.assertEqual(records_for(verdict, "amount"), ())

    def test_second_half_argument_types_outside_the_closed_set(self) -> None:
        for amount in (200.0, True, None, [200]):
            with self.subTest(amount=repr(amount), type=type(amount).__name__):
                verdict = self._evaluate(amount)
                self.assertIn(BlockReason.ARGUMENT_UNDECODABLE, verdict.reasons)
                self.assertIs(verdict.outcome, Outcome.BLOCK)

    def test_third_half_interior_character_forms_stay_undecodable(self) -> None:
        # R3 aligned the two sides, it did not add a decoder: canonicalize_token
        # strips from the ENDS only, so an interior hyphen / dollar sign /
        # thousands separator survives and the span fails to decode.
        # 🔴 These three are NEVER legal inputs anywhere in this suite.
        for amount in ("twenty-five", "$200", "200,000"):
            with self.subTest(amount=amount):
                verdict = self._evaluate(amount)
                self.assertIn(BlockReason.ARGUMENT_UNDECODABLE, verdict.reasons)
                self.assertIs(verdict.outcome, Outcome.BLOCK)


# ===========================================================================
# TS-6
# ===========================================================================
# 🔴 **Mutation:** add `("dollars",): "CAD"` to `CURRENCY_SPELLINGS`. Verdict
# becomes ALLOW. Red.
#
# ⇒ Teaching the currency table that a bare "dollars" means CAD makes this test
#   red: the normalizer would manufacture a witness for a currency nobody named.
class TestTS06BareDollarsIsUndecodable(unittest.TestCase):
    """TS-6 — (c3) bare "dollars" is undecodable for a currency code."""

    def setUp(self) -> None:
        self.transcript = transcript_of(TS6_SENTENCE)
        self.gate = build_gate(grounding_registry())
        self.verdict = self.gate.evaluate(
            proposal_of(**GROUNDED_PROPOSAL), self.transcript
        )
        self.ws = witnesses_for(self.transcript)

    def test_blocks_and_the_block_names_the_currency_param(self) -> None:
        self.assertIs(self.verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.NO_WITNESS, self.verdict.reasons)
        currency_records = records_for(self.verdict, "currency")
        self.assertTrue(currency_records)
        self.assertTrue(
            any(r.reason is BlockReason.NO_WITNESS for r in currency_records),
            "expected a CheckRecord naming param 'currency' with reason "
            "NO_WITNESS; got " + repr(currency_records),
        )

    def test_no_currency_witness(self) -> None:
        self.assertIs(self.ws.satisfies("CAD", SemanticRole.CURRENCY), False)

    def test_the_amount_is_grounded_so_the_block_is_precisely_located(self) -> None:
        self.assertIs(self.ws.satisfies(200, SemanticRole.MONEY_AMOUNT), True)


# ===========================================================================
# TS-7
# ===========================================================================
# 🔴 **Mutation:** delete the W5 comparison in `generate_witnesses`
# (`if min_conf < confidence_floor`). The span becomes a witness and the verdict
# becomes ALLOW. Red.
#
# ⇒ Deleting the W5 confidence comparison makes this test red.
class TestTS07WitnessBelowTheConfidenceFloor(unittest.TestCase):
    """TS-7 — (d) witness word below the given confidence floor."""

    def setUp(self) -> None:
        self.transcript = transcript_of(
            TS1_SENTENCE, low_conf_tokens=("two", "hundred"), low_conf=LOW
        )
        self.gate = build_gate(grounding_registry(), confidence_floor=FLOOR_HIGH)
        self.verdict = self.gate.evaluate(
            proposal_of(**GROUNDED_PROPOSAL), self.transcript
        )

    def test_blocks_with_both_reasons(self) -> None:
        self.assertIs(self.verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.CONFIDENCE_BELOW_FLOOR, self.verdict.reasons)
        self.assertIn(BlockReason.NO_WITNESS, self.verdict.reasons)

    def test_the_rejected_span_carries_the_decoded_value_and_the_cause(self) -> None:
        ws = witnesses_for(self.transcript, confidence_floor=FLOOR_HIGH)
        self.assertTrue(
            any(
                r.cause is RejectCause.BELOW_CONFIDENCE_FLOOR and r.decoded_value == 200
                for r in ws.rejected
            )
        )


# ===========================================================================
# TS-8
# ===========================================================================
# 🔴 **Mutation:** hard-code any floor inside `generate_witnesses` instead of
# using the parameter. One of TS-7/TS-8 goes red for every constant chosen.
#
# ⇒ Hard-coding a floor anywhere inside the witness generator makes TS-7 or this
#   test red, whichever side of the constant the fixture falls on.
class TestTS08PairedFloorArm(unittest.TestCase):
    """TS-8 — (d′) the paired arm that proves the floor is what changed the outcome."""

    def test_lowering_only_the_floor_flips_the_verdict(self) -> None:
        transcript = transcript_of(
            TS1_SENTENCE, low_conf_tokens=("two", "hundred"), low_conf=LOW
        )
        gate = build_gate(grounding_registry(), confidence_floor=FLOOR_LOW)
        verdict = gate.evaluate(proposal_of(**GROUNDED_PROPOSAL), transcript)
        self.assertIs(verdict.outcome, Outcome.ALLOW)
        self.assertEqual(verdict.evidence.confidence_floor, FLOOR_LOW)


# ===========================================================================
# TS-9
# ===========================================================================
# 🔴 **Mutation:** change `satisfies` to also scan `self.rejected`. Red. This is
# boundary B-12's pin.
#
# ⇒ Letting `satisfies` read `self.rejected` makes this test red: `rejected`
#   holds exactly the values an attacker wants credited.
class TestTS09RejectedSpansNeverSatisfy(unittest.TestCase):
    """TS-9 — (d″) rejected spans must never satisfy."""

    def setUp(self) -> None:
        span = Span(
            start_index=2,
            end_index=4,
            start_ms=200,
            end_ms=390,
            text="two hundred",
        )
        self.ws = WitnessSet(
            witnesses=(),
            rejected=(
                RejectedSpan(
                    span=span,
                    cause=RejectCause.BELOW_CONFIDENCE_FLOOR,
                    decoded_value=200,
                    min_confidence=LOW,
                ),
            ),
        )

    def test_satisfies_ignores_rejected(self) -> None:
        self.assertIs(self.ws.satisfies(200, SemanticRole.MONEY_AMOUNT), False)

    def test_explain_says_no_witness(self) -> None:
        self.assertIs(
            self.ws.explain(200, SemanticRole.MONEY_AMOUNT), BlockReason.NO_WITNESS
        )

    def test_rejected_for_confidence_is_the_only_reader(self) -> None:
        self.assertIs(self.ws.rejected_for_confidence(200), True)


# ===========================================================================
# TS-10 .. TS-14, TS-16 registry fixtures
# ===========================================================================
NOT_IMPLEMENTED_RATIONALE = "read-back dialogue out of scope this round"
TS11_RATIONALE = "grounding alone is sufficient for this test fixture"


def _ts10_checks(param: str) -> dict[CheckId, CheckRequirement]:
    checks = all_not_required()
    if param == "amount":
        checks[CheckId.READ_BACK_CONFIRMED] = CheckRequirement(
            CheckStatus.NOT_IMPLEMENTED, NOT_IMPLEMENTED_RATIONALE
        )
    return checks


def _ts11_checks(param: str) -> dict[CheckId, CheckRequirement]:
    checks = all_not_required()
    if param == "amount":
        checks[CheckId.READ_BACK_CONFIRMED] = CheckRequirement(
            CheckStatus.NOT_REQUIRED, TS11_RATIONALE
        )
    return checks


def _ts14_checks(param: str) -> dict[CheckId, CheckRequirement]:
    checks = all_not_required()
    if param == "amount":
        # REQUIRED against STANDARD_CHECKERS, which has no implementation for it.
        # The empty rationale is legal: L6 only constrains NOT_REQUIRED and
        # NOT_IMPLEMENTED.
        checks[CheckId.READ_BACK_CONFIRMED] = CheckRequirement(CheckStatus.REQUIRED, "")
    return checks


def _ts16_checks(param: str) -> dict[CheckId, CheckRequirement]:
    checks = all_not_required()
    if param == "amount":
        del checks[CheckId.CONFIDENCE_FLOOR]
    return checks


def ts10_registry() -> ActionRegistry:
    return make_registry(_ts10_checks, reversibility=Reversibility.IRREVERSIBLE)


def ts11_registry() -> ActionRegistry:
    return make_registry(_ts11_checks, reversibility=Reversibility.IRREVERSIBLE)


def ts12_registry() -> ActionRegistry:
    return make_registry(_ts10_checks, reversibility=Reversibility.REVERSIBLE)


def ts14_registry() -> ActionRegistry:
    return make_registry(_ts14_checks, reversibility=Reversibility.IRREVERSIBLE)


def ts16_registry() -> ActionRegistry:
    return make_registry(_ts16_checks, reversibility=Reversibility.IRREVERSIBLE)


# ===========================================================================
# TS-10
# ===========================================================================
# 🔴 **Mutation:** in E9, change the `NOT_IMPLEMENTED` branch to record
# `"skipped"` unconditionally (drop the `IRREVERSIBLE` test and the
# `reasons.append`). Verdict becomes ALLOW. Red.
#
# ⇒ Recording NOT_IMPLEMENTED as "skipped" without appending the reason makes
#   this test red.
class TestTS10NotImplementedBlocksIrreversible(unittest.TestCase):
    """TS-10 — (e) `NOT_IMPLEMENTED` on an irreversible action blocks."""

    def setUp(self) -> None:
        self.registry = ts10_registry()
        self.transcript = transcript_of(TS1_SENTENCE)

    def test_1_not_implemented_is_legal_at_lint_time(self) -> None:
        self.assertIsNone(lint_registry(self.registry, STANDARD_CHECKERS))

    def test_2_the_gate_constructs(self) -> None:
        self.assertIsInstance(build_gate(self.registry), Gate)

    def test_3_evaluate_blocks_and_mints_nothing(self) -> None:
        verdict = build_gate(self.registry).evaluate(
            proposal_of(**GROUNDED_PROPOSAL), self.transcript
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.CHECK_NOT_IMPLEMENTED, verdict.reasons)
        self.assertIsNone(verdict.capability)

    def test_4_the_record_names_the_param_check_status_and_outcome(self) -> None:
        verdict = build_gate(self.registry).evaluate(
            proposal_of(**GROUNDED_PROPOSAL), self.transcript
        )
        self.assertTrue(
            any(
                r.param == "amount"
                and r.check is CheckId.READ_BACK_CONFIRMED
                and r.status is CheckStatus.NOT_IMPLEMENTED
                and r.outcome == "not_implemented"
                for r in verdict.evidence.records
            ),
            "expected CheckRecord(param='amount', check=READ_BACK_CONFIRMED, "
            "status=NOT_IMPLEMENTED, outcome='not_implemented'); got "
            + repr(records_for(verdict, "amount")),
        )


# ===========================================================================
# TS-11
# ===========================================================================
# (The design gives TS-11 no mutation of its own: it IS the paired arm that
#  makes TS-10's mutation legible.)
class TestTS11PairedTriStateArm(unittest.TestCase):
    """TS-11 — (e′) the paired arm."""

    def test_flipping_only_that_entry_allows(self) -> None:
        verdict = build_gate(ts11_registry()).evaluate(
            proposal_of(**GROUNDED_PROPOSAL), transcript_of(TS1_SENTENCE)
        )
        # Proves the TS-10 block came from the tri-state and not from the
        # grounding: this registry checks no grounding at all.
        self.assertIs(verdict.outcome, Outcome.ALLOW)


# ===========================================================================
# TS-12
# ===========================================================================
# 🔴 **Mutation:** drop the `if spec.reversibility is IRREVERSIBLE` condition so
# every `NOT_IMPLEMENTED` blocks. TS-12 goes red. Together TS-10 and TS-12 pin
# *both* sides of the condition; either alone would be satisfied by a constant.
#
# ⇒ Dropping the IRREVERSIBLE condition makes this test red.
class TestTS12NotImplementedOnReversibleDoesNotBlock(unittest.TestCase):
    """TS-12 — (e″) `NOT_IMPLEMENTED` on a REVERSIBLE action does not block."""

    def setUp(self) -> None:
        self.verdict = build_gate(ts12_registry()).evaluate(
            proposal_of(**GROUNDED_PROPOSAL), transcript_of(TS1_SENTENCE)
        )

    def test_allows(self) -> None:
        self.assertIs(self.verdict.outcome, Outcome.ALLOW)

    def test_the_entry_is_recorded_as_skipped(self) -> None:
        self.assertTrue(
            any(
                r.param == "amount"
                and r.check is CheckId.READ_BACK_CONFIRMED
                and r.outcome == "skipped"
                for r in self.verdict.evidence.records
            ),
            "expected outcome == 'skipped' for the NOT_IMPLEMENTED entry on a "
            "REVERSIBLE action; got " + repr(records_for(self.verdict, "amount")),
        )


# ===========================================================================
# TS-13
# ===========================================================================
# 🔴 **Mutation:** delete the `NOT_IMPLEMENTED` scan in `lint_deployment`. Red.
#
# ⇒ Deleting the NOT_IMPLEMENTED scan from `lint_deployment` makes this test red.
class TestTS13StricterDeploymentProfile(unittest.TestCase):
    """TS-13 — (e‴) the stricter deployment profile."""

    def test_deployment_lint_refuses_the_not_implemented_registry(self) -> None:
        with self.assertRaises(DeploymentLintError) as caught:
            lint_deployment(ts10_registry(), STANDARD_CHECKERS)
        message = str(caught.exception)
        for token in ("transfer", "amount", "read_back_confirmed"):
            self.assertIn(token, message)

    def test_deployment_lint_accepts_the_flipped_registry(self) -> None:
        self.assertIsNone(lint_deployment(ts11_registry(), STANDARD_CHECKERS))


# ===========================================================================
# TS-14
# ===========================================================================
# 🔴 **Mutation 1:** delete the L1 rule from `lint_registry`. Construction
# succeeds, no exception, red.
# 🔴 **Mutation 2:** move the `lint_registry(...)` call out of
# `Gate.__post_init__` and into `Gate.evaluate`. Construction succeeds, red.
# This mutation is what "load time, not run time" means, and TS-14 is the only
# thing that detects it.
#
# ⇒ Deleting L1, or moving the lint call out of __post_init__ into evaluate,
#   makes this test red — construction would stop raising.
class TestTS14DanglingCheckerFailsAtLoadTime(unittest.TestCase):
    """TS-14 — (f) dangling checker reference fails at load time."""

    def test_construction_itself_raises_and_the_message_names_the_triple(self) -> None:
        registry = ts14_registry()
        with self.assertRaises(RegistryLintError) as caught:
            # The construction call, not an `evaluate` call.
            build_gate(registry)
        message = str(caught.exception)
        for token in ("transfer", "amount", "read_back_confirmed"):
            self.assertIn(token, message)


# ===========================================================================
# TS-15
# ===========================================================================
# 🔴 **Mutation:** guard the lint behind any new parameter. Red (both the AST
# assertion and TS-34's no-defaults rule fire).
#
# ⇒ Adding any escape parameter to Gate, or moving the lint_registry call out of
#   __post_init__, makes this test red.
GATE_PARAMETER_NAMES = frozenset(
    {
        "registry",
        "checkers",
        "text_of",
        "provenance",
        "confidence_floor",
        "max_span_words",
        "role_window",
        "max_transcript_words",
        "require_known_provenance",
    }
)


def _called_names(node: ast.AST) -> set[str]:
    """Every callee name reachable inside `node`, by AST rather than by text."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


class TestTS15NoUnlintedGate(unittest.TestCase):
    """TS-15 — (f′) there is no unlinted `Gate`."""

    def setUp(self) -> None:
        source_path = decision_module.__file__
        assert source_path is not None
        with open(source_path, "r", encoding="utf-8") as handle:
            self.tree = ast.parse(handle.read(), filename=source_path)

    def _gate_post_init(self) -> ast.FunctionDef:
        gate_classes = [
            n
            for n in ast.walk(self.tree)
            if isinstance(n, ast.ClassDef) and n.name == "Gate"
        ]
        self.assertEqual(len(gate_classes), 1, "expected exactly one class Gate")
        post_inits = [
            n
            for n in gate_classes[0].body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "__post_init__"
        ]
        self.assertEqual(
            len(post_inits), 1, "expected exactly one Gate.__post_init__"
        )
        return post_inits[0]

    def test_lint_registry_is_called_from_gate_post_init(self) -> None:
        self.assertIn("lint_registry", _called_names(self._gate_post_init()))

    def test_gate_init_exposes_no_escape_parameter(self) -> None:
        # Deny-by-default: the parameter set must EQUAL the contract's field set.
        # A blocklist of `skip_lint`-shaped names would be blind to the next
        # escape hatch, whatever it gets called.
        observed = set(inspect.signature(Gate.__init__).parameters) - {"self"}
        self.assertEqual(observed, set(GATE_PARAMETER_NAMES))


# ===========================================================================
# TS-16
# ===========================================================================
# 🔴 **Mutation:** change L2 from `set(param.checks) != set(CheckId)` to
# `not set(param.checks)`. Red.
#
# ⇒ Weakening L2 from "total coverage of the closed enum" to "non-empty" makes
#   this test red.
class TestTS16AbsentCheckKeyFailsTheLint(unittest.TestCase):
    """TS-16 — (f″) an ABSENT check key fails the lint and names itself.

    Honest note, carried from the design rather than paraphrased: because L2
    rejects ABSENT at load and `Gate.__post_init__` always lints, the runtime
    `CHECK_ABSENT` branch at E9 is unreachable through the public API.  It is
    defense in depth.  Its behaviour is pinned by a direct unit test on
    `ActionRegistry.status` returning `None`, not by an end-to-end path -- and
    this test says so rather than pretending otherwise.
    """

    def test_construction_raises_and_the_message_names_itself(self) -> None:
        with self.assertRaises(RegistryLintError) as caught:
            build_gate(ts16_registry())
        message = str(caught.exception)
        for token in ("transfer", "amount", "confidence_floor"):
            self.assertIn(token, message)
        self.assertIn("ABSENT", message)

    def test_absent_is_status_returning_none_not_an_enum_member(self) -> None:
        # The fourth state is unrepresentable: you cannot write it down, you can
        # only fail to write anything.
        self.assertNotIn("ABSENT", {member.name for member in CheckStatus})
        registry = ts16_registry()
        self.assertIsNone(
            registry.status("transfer", "amount", CheckId.CONFIDENCE_FLOOR)
        )
        self.assertIsNone(registry.status("transfer", "nonexistent_param",
                                          CheckId.WITNESS_PRESENT))
        self.assertIsNone(registry.status("nonexistent_action", "amount",
                                          CheckId.WITNESS_PRESENT))


if __name__ == "__main__":
    unittest.main()
