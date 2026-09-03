# tests/test_gate_ts17_31.py
"""Test specifications TS-17 .. TS-31 of `design_v3.md` (voice-action gate).

Scope of THIS file: TS-17, TS-18, TS-19, TS-20, TS-21, TS-22, TS-23, TS-24,
TS-25, TS-26, TS-27, TS-28, TS-29, TS-30, TS-31 -- no more, no less.
TS-1..16 and TS-32..47 live in sibling files written by other lanes.

Reading order honoured while writing this file: the `# v3 权威修订段` (A0-A19)
first, then the body; on conflict the amendment段 wins.

🔴 EVERY expected value below is derived from the CONTRACT ONLY. No `gate/*.py`
implementation file was read while writing this. A test whose expectation is
back-derived from the implementation proves only that the implementation equals
itself and carries 0 bit.

🔴 DISCIPLINE (router, verbatim): "一条测试红了,是【回报给 architect 的
finding】,不是改测试或改实现去迁就对方的许可。" If an assertion here is red,
report it; do not soften it and do not "fix" the implementation to match it
without going back through the contract.

🔴 MECHANICAL ENUMERATION (DN-1 / TI-1): wherever the design asks for an
enumeration, this file enumerates from the closed source (`CheckId`,
`BlockReason`, `WORD_KEYS`, `STANDARD_CHECKERS`, `Path.rglob`), never from a
hand-written list. DN-1 and TI-1 both record accidents caused by hand lists.

Every threshold used here is a module-local constant in THIS file, passed into
`Gate(...)`. Nothing threshold-shaped is imported from `gate/` (requirement 21).

Run:
    python3 -m unittest tests.test_gate_ts17_31 -v
    python3 -m pytest tests/test_gate_ts17_31.py
"""

from __future__ import annotations

import ast
import copy
import inspect
import pickle
import sys
import threading
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator

# --------------------------------------------------------------------------
# sys.path bootstrap
# ⚠ MAY DUPLICATE THE OTHER TWO LANES -- router de-dupes at collection time.
# --------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import gate  # noqa: E402
from gate.checks import STANDARD_CHECKERS  # noqa: E402
from gate.decision import Evidence, ExecuteCapability, Gate, Verdict  # noqa: E402
from gate.errors import (  # noqa: E402
    CapabilityForgeryError,
    PolicyError,
    TranscriptFormatError,
)
from gate.executor import execute_transfer, require_capability  # noqa: E402
from gate.normalize import VALUE_UNDECODABLE, ValueKind, canonicalize_text  # noqa: E402
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
)
from gate.roles import SemanticRole  # noqa: E402
from gate.transcript import (  # noqa: E402
    WORD_KEYS,
    TranscriptProvenance,
    parse_transcript,
    parse_word,
    raw_text_of,
)
from gate.witness import RejectCause, generate_witnesses  # noqa: E402

# ==========================================================================
# Test-module-local policy constants.
# 🔴 These are the ONLY numbers in play, and they live here, not in gate/.
# Values taken from `## Test Specifications` line "Standard policy used unless
# stated" and from TS-7's test-module locals.
# ⚠ MAY DUPLICATE THE OTHER TWO LANES -- router de-dupes.
# ==========================================================================
FLOOR_HIGH = 0.90
FLOOR_LOW = 0.40
CONF_HIGH = 0.99
MAX_SPAN_WORDS = 3
ROLE_WINDOW = 2
MAX_TRANSCRIPT_WORDS = 200

PROVENANCE = TranscriptProvenance("text", None, "raw_text_of")

RATIONALE = "test fixture: a human wrote this sentence so lint L6 has one to read"

# The grounded happy-path fixture, shared by TS-17/19/20/21/22/24/28/30/31.
GROUNDED_UTTERANCE = "please transfer two hundred canadian dollars to my sister"
GROUNDED_AMOUNT = 200
GROUNDED_ARGS = {"amount": GROUNDED_AMOUNT, "currency": "CAD", "to": "my sister"}

# TS-2's fixture, reused by TS-31 as the deterministic BLOCK arm.
STREET_UTTERANCE = (
    "i live at five hundred maple street "
    "please transfer two hundred canadian dollars to my sister"
)
STREET_ARGS = {"amount": 500, "currency": "CAD", "to": "my sister"}

# TS-27's non-ASCII payload, written as an escape so the byte sequence in this
# file cannot be silently normalised by a transport on its way here.
NON_ASCII_NAME = "se\u00f1ora"

# The reasons E2/E3/E4/E6 can produce BEFORE any per-parameter work happens.
# Everything else in the enum is per-parameter BY CONSTRUCTION, so a newly added
# BlockReason member lands in PER_PARAM_REASONS automatically (deny-by-default).
GATE_LEVEL_REASONS = frozenset(
    {
        BlockReason.TRANSCRIPT_PROVENANCE_UNKNOWN,
        BlockReason.TRANSCRIPT_TOO_LONG,
        BlockReason.NO_FINAL_WORDS,
        BlockReason.ACTION_NOT_REGISTERED,
    }
)
PER_PARAM_REASONS = frozenset(BlockReason) - GATE_LEVEL_REASONS


# ==========================================================================
# Fixture helpers.
# ⚠ MAY DUPLICATE THE OTHER TWO LANES -- router de-dupes.
# ==========================================================================
def word_dicts(
    utterance: str, *, conf: float = CONF_HIGH, final: bool = True
) -> list[dict[str, Any]]:
    """`w(text, conf, final=True)` from `## Test Specifications`, vectorised.

    start = i*100, end = i*100+90, exactly as the shared fixture helper says.
    """
    return [
        {
            "text": token,
            "start": i * 100,
            "end": i * 100 + 90,
            "confidence": conf,
            "word_is_final": final,
        }
        for i, token in enumerate(utterance.split())
    ]


def transcript_of(utterance: str, *, conf: float = CONF_HIGH, final: bool = True):
    return parse_transcript(word_dicts(utterance, conf=conf, final=final))


def proposal_of(action: str, arguments: dict[str, Any]):
    return parse_proposal({"action": action, "arguments": dict(arguments)})


def check_map(
    *, read_back_status: CheckStatus, read_back_rationale: str = RATIONALE
) -> Any:
    """Full CheckId coverage, ENUMERATED FROM THE CLOSED ENUM.

    lint L2 demands `set(param.checks) == set(CheckId)`; writing the four names
    by hand is exactly the hand-list DN-1 forbids -- a fifth CheckId would then
    be silently uncovered here while L2 rejected it at load, and the failure
    would read as "the registry fixture is stale" rather than as itself.

    Everything a shipped checker exists for is REQUIRED; anything else is
    NOT_REQUIRED with a rationale. Today that is exactly "the three checks
    REQUIRED, READ_BACK_CONFIRMED per the caller" which is what TS-17 asks for,
    but it is derived from STANDARD_CHECKERS rather than restated.
    """
    out: dict[CheckId, CheckRequirement] = {}
    for check_id in CheckId:
        if check_id is CheckId.READ_BACK_CONFIRMED:
            out[check_id] = CheckRequirement(read_back_status, read_back_rationale)
        elif check_id in STANDARD_CHECKERS:
            out[check_id] = CheckRequirement(CheckStatus.REQUIRED, RATIONALE)
        else:
            out[check_id] = CheckRequirement(CheckStatus.NOT_REQUIRED, RATIONALE)
    return MappingProxyType(out)


# The three parameters of `transfer`, taken verbatim from the `reference.py`
# contract block. This is a contract table, not a closed enum, so it is quoted
# rather than enumerated.
TRANSFER_PARAMS = (
    ("amount", ValueKind.NUMBER, SemanticRole.MONEY_AMOUNT),
    ("currency", ValueKind.CURRENCY_CODE, SemanticRole.CURRENCY),
    ("to", ValueKind.TEXT, SemanticRole.RECIPIENT),
)


def build_registry(
    *,
    reversibility: Reversibility = Reversibility.IRREVERSIBLE,
    read_back_status: CheckStatus = CheckStatus.NOT_REQUIRED,
    action_name: str = "transfer",
) -> ActionRegistry:
    checks = check_map(read_back_status=read_back_status)
    params = {
        name: ParamSpec(
            name=name, value_kind=kind, required_role=role, checks=checks
        )
        for name, kind, role in TRANSFER_PARAMS
    }
    spec = ActionSpec(
        name=action_name,
        reversibility=reversibility,
        params=MappingProxyType(params),
    )
    return ActionRegistry(actions=MappingProxyType({action_name: spec}))


def build_gate(registry: ActionRegistry | None = None, **overrides: Any) -> Gate:
    """Every Gate knob is spelled out: `Gate` is kw_only with zero defaults."""
    kwargs: dict[str, Any] = {
        "registry": build_registry() if registry is None else registry,
        "checkers": STANDARD_CHECKERS,
        "text_of": raw_text_of,
        "provenance": PROVENANCE,
        "confidence_floor": FLOOR_HIGH,
        "max_span_words": MAX_SPAN_WORDS,
        "role_window": ROLE_WINDOW,
        "max_transcript_words": MAX_TRANSCRIPT_WORDS,
        "require_known_provenance": False,
    }
    kwargs.update(overrides)
    return Gate(**kwargs)


def witnesses_for(utterance: str, *, conf: float = CONF_HIGH, final: bool = True):
    """A witness set generated INDEPENDENTLY of `Gate.evaluate`."""
    return generate_witnesses(
        transcript_of(utterance, conf=conf, final=final),
        text_of=raw_text_of,
        confidence_floor=FLOOR_HIGH,
        max_span_words=MAX_SPAN_WORDS,
        role_window=ROLE_WINDOW,
    )


def make_evidence() -> Evidence:
    """A syntactically valid Evidence for tests that need one as a payload."""
    return Evidence(
        provenance=PROVENANCE,
        confidence_floor=FLOOR_HIGH,
        max_span_words=MAX_SPAN_WORDS,
        role_window=ROLE_WINDOW,
        max_transcript_words=MAX_TRANSCRIPT_WORDS,
        witness_count=0,
        rejected_count=0,
        matched=MappingProxyType({}),
        records=(),
    )


def mint_capability() -> ExecuteCapability:
    """Mint one capability THROUGH THE GATE -- the only sanctioned way.

    🔴 This helper deliberately does NOT import `gate.decision._MINT_KEY`. A test
    file that imported the key in order to fabricate a capability would itself be
    the second minting site TS-18/TS-37 exist to forbid, and it would make the
    forgery guard untestable from the outside.
    """
    verdict = build_gate().evaluate(
        proposal_of("transfer", GROUNDED_ARGS), transcript_of(GROUNDED_UTTERANCE)
    )
    if verdict.capability is None:
        raise AssertionError(
            "happy-path fixture minted no capability: "
            f"outcome={verdict.outcome} reasons={verdict.reasons}"
        )
    return verdict.capability


# ==========================================================================
# AST helpers for the structural half of TS-18.
# ⚠ MAY DUPLICATE THE OTHER TWO LANES (TS-15 / TS-34..38 need the same shapes)
#   -- router de-dupes.
# ==========================================================================
_gate_file = getattr(gate, "__file__", None)
GATE_DIR = (
    Path(_gate_file).resolve().parent if _gate_file else (_REPO_ROOT / "gate").resolve()
)


def gate_sources() -> list[tuple[Path, str]]:
    """Every `.py` under `gate/`, enumerated by rglob -- never a hand list.

    🔴 The population is the thing that goes wrong silently (a glob that matches
    nothing reports "no violations"), so callers MUST assert the population is
    non-empty and contains the file they care about. TS-18 does.
    """
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(GATE_DIR.rglob("*.py"))]


def iter_nodes_with_scope(node: ast.AST, prefix: str = "") -> Iterator[tuple[ast.AST, str]]:
    """Yield `(node, qualname_of_enclosing_scope)` for every descendant."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child, prefix
            inner = f"{prefix}.{child.name}" if prefix else child.name
            yield from iter_nodes_with_scope(child, inner)
        else:
            yield child, prefix
            yield from iter_nodes_with_scope(child, prefix)


def callee_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# ==========================================================================
# TS-17
# ==========================================================================
class TestTS17HappyPath(unittest.TestCase):
    """TS-17 — happy path, and what the capability carries.

    Contract anchors: `Gate.evaluate` E13 (the capability carries the DECODED
    mapping, not `proposal.arguments`), `Evidence.matched`,
    `executor.execute_transfer`.
    """

    # 🔴 **Mutation:** in E13, pass `proposal.arguments` instead of the decoded
    # mapping. The test includes the variant `{"amount": "200"}`, whose
    # `capability.arguments["amount"]` must still be `int`; the mutation makes it
    # `str`. Red.
    # ⇒ 本测试必红。
    def test_happy_path_allows_and_capability_carries_decoded_values(self) -> None:
        gate_obj = build_gate()
        verdict = gate_obj.evaluate(
            proposal_of("transfer", GROUNDED_ARGS), transcript_of(GROUNDED_UTTERANCE)
        )

        self.assertIs(verdict.outcome, Outcome.ALLOW, msg=f"reasons={verdict.reasons}")
        self.assertEqual(verdict.reasons, ())
        self.assertIsNotNone(verdict.capability)

        cap = verdict.capability
        self.assertEqual(cap.action, "transfer")
        self.assertEqual(dict(cap.arguments), dict(GROUNDED_ARGS))
        # `type(...) is int` rather than isinstance: bool is an int subclass and
        # the whole point of B-6 is that the two must never be confused.
        self.assertIs(type(cap.arguments["amount"]), int)

        self.assertIs(
            verdict.evidence.matched["amount"].role, SemanticRole.MONEY_AMOUNT
        )
        self.assertEqual(verdict.evidence.confidence_floor, FLOOR_HIGH)

    def test_string_amount_still_arrives_as_int(self) -> None:
        """The variant TS-17 names explicitly: `{"amount": "200"}`."""
        gate_obj = build_gate()
        args = dict(GROUNDED_ARGS, amount="200")
        verdict = gate_obj.evaluate(
            proposal_of("transfer", args), transcript_of(GROUNDED_UTTERANCE)
        )

        self.assertIs(verdict.outcome, Outcome.ALLOW, msg=f"reasons={verdict.reasons}")
        cap = verdict.capability
        self.assertIsNotNone(cap)
        self.assertIs(
            type(cap.arguments["amount"]),
            int,
            msg="E13 must carry the DECODED value; a str here means the raw "
            "proposal mapping was passed through",
        )
        self.assertEqual(cap.arguments["amount"], GROUNDED_AMOUNT)

    def test_executor_consumes_the_capability(self) -> None:
        """`execute_transfer(capability, ledger)` returns a receipt and moves 200.

        ⚠ ASSUMPTION, stated rather than hidden: the design says only
        "mutates the ledger by 200" and never fixes the ledger's key shape. This
        asserts the weakest defensible reading -- some key moved by exactly 200.
        If the implementation's ledger contract differs, that is an ambiguity to
        report to architect, not an assertion to relax.
        """
        cap = mint_capability()
        ledger: dict[str, int] = {}
        receipt = execute_transfer(cap, ledger)

        self.assertIsInstance(receipt, str)
        self.assertNotEqual(receipt.strip(), "", msg="receipt id must be non-empty")
        self.assertTrue(ledger, msg="the ledger was not mutated at all")
        self.assertIn(
            GROUNDED_AMOUNT,
            {abs(v) for v in ledger.values()},
            msg=f"no ledger entry moved by {GROUNDED_AMOUNT}: {ledger!r}",
        )


# ==========================================================================
# TS-18
# ==========================================================================
class TestTS18NoDirectConstruction(unittest.TestCase):
    """TS-18 — direct construction of a capability is refused.

    ⚠ HONEST SCOPE (carried here because a reader of this test meets it here,
    and it is the same boundary as `gate/decision.py`'s module docstring): the
    structural half below asserts a property of THIS PACKAGE'S SOURCE, not of
    the process. It DETECTS the edit; it does not PREVENT it.
    `object.__new__` + `object.__setattr__`, `unittest.mock.patch`, and anyone
    who can edit `decision.py` are all outside it. Do not upgrade this into a
    security claim.

    🔴 TWO DIRECTIONS, BOTH REQUIRED (router discipline #3). "Execute 凭据只能
    由闸构造" fails in two independent ways and one assertion cannot see both:
      (A) the forgery GUARD is deleted  -> `test_foreign_mint_key_is_refused`
      (B) a SECOND MINTING SITE is added -> `test_exactly_one_minting_site`
    A suite that only had (A) would stay green while someone added a second
    `ExecuteCapability(..., _mint_key=_MINT_KEY)` call elsewhere in the package;
    a suite that only had (B) would stay green while the guard was deleted and
    every `object()` became a valid key. Both, or neither is worth anything.

    ⚠ Direction (B) OVERLAPS TS-37 by design and by different needles: TS-37
    classifies references to the NAME `_MINT_KEY`; this counts CONSTRUCTION CALLS
    of `ExecuteCapability`. An alias (`K = _MINT_KEY; ExecuteCapability(..., 
    _mint_key=K)`) is caught by TS-37's OTHER category and by this one's call
    count. Router: if TS-37's lane objects to the overlap, keep both -- the
    redundancy is the point, not an accident.
    """

    # 🔴 **Mutation:** delete the `_mint_key is not _MINT_KEY` comparison in
    # `__post_init__`. Red.
    # ⇒ 本测试必红。
    def test_foreign_mint_key_is_refused(self) -> None:
        """Direction (A): the guard exists and rejects every key but the real one."""
        evidence = make_evidence()
        for label, key in (("a fresh object()", object()), ("None", None)):
            with self.subTest(mint_key=label):
                with self.assertRaises(CapabilityForgeryError):
                    ExecuteCapability(
                        action="transfer",
                        arguments={},
                        evidence=evidence,
                        _mint_key=key,
                    )

    def test_exactly_one_minting_site(self) -> None:
        """Direction (B): adding a second construction site turns this red.

        Population: every `.py` under `gate/`, from rglob -- not a hand list.
        Needle: every `ast.Call` whose callee name is `ExecuteCapability`.
        Annotations (`cap: ExecuteCapability`) are `Name` nodes, not `Call`
        nodes, so the executor's signature does not count.
        """
        sources = gate_sources()

        # Population self-check FIRST. A glob that matched nothing would make
        # "zero minting sites" indistinguishable from "the scan is broken".
        self.assertTrue(sources, msg=f"no .py files found under {GATE_DIR}")
        names = {p.name for p, _ in sources}
        self.assertIn(
            "decision.py",
            names,
            msg=f"scanned {sorted(names)} -- decision.py absent, population is wrong",
        )

        sites: list[tuple[str, int, str]] = []
        for path, src in sources:
            tree = ast.parse(src, filename=str(path))
            for node, qualname in iter_nodes_with_scope(tree):
                if isinstance(node, ast.Call) and callee_name(node.func) == (
                    "ExecuteCapability"
                ):
                    sites.append((path.name, node.lineno, qualname))

        self.assertEqual(
            len(sites),
            1,
            msg=(
                "ExecuteCapability must be constructed in exactly one place in "
                f"gate/. Found {len(sites)}: {sites}"
            ),
        )

        filename, _lineno, qualname = sites[0]
        # Contract anchors: the `gate/decision.py` module header
        # ("THE ONLY MODULE THAT CAN MINT AN ExecuteCapability"), A7 assertion 3
        # (enclosing qualname exactly `Gate.evaluate`), and the A-vs-B decision
        # "Where the mint key lives".
        # ⚠ CONTRACT CONFLICT, reported not resolved: A19's closing note says
        # "gate/capability.py(`_MINT_KEY` 唯一铸造点)". A7, the Contract module
        # header, Requirement Coverage row 2 and the A/B decision all say
        # `gate/decision.py`. This test follows the three-against-one reading.
        # If it is red on `capability.py`, that is a finding for architect.
        self.assertEqual(filename, "decision.py")
        self.assertEqual(qualname, "Gate.evaluate")

    def test_the_one_site_passes_the_module_private_key_by_keyword(self) -> None:
        """The single site mints with `_mint_key=_MINT_KEY`, not with a literal.

        Without this, direction (B) could be satisfied by a single site that
        passes `object()` -- one minting site that mints nothing.
        """
        decision_path = GATE_DIR / "decision.py"
        self.assertTrue(decision_path.is_file(), msg=f"missing {decision_path}")
        tree = ast.parse(decision_path.read_text(encoding="utf-8"), filename="decision.py")

        calls = [
            node
            for node, _qual in iter_nodes_with_scope(tree)
            if isinstance(node, ast.Call) and callee_name(node.func) == "ExecuteCapability"
        ]
        self.assertEqual(len(calls), 1)

        keywords = {kw.arg: kw.value for kw in calls[0].keywords if kw.arg}
        self.assertIn("_mint_key", keywords, msg="the mint is not keyed at all")
        key_node = keywords["_mint_key"]
        self.assertIsInstance(
            key_node,
            ast.Name,
            msg="the minting key must be the module-private name, not an expression",
        )
        self.assertEqual(key_node.id, "_MINT_KEY")


# ==========================================================================
# TS-19
# ==========================================================================
class TestTS19CopyAndPickleRefused(unittest.TestCase):
    """TS-19 — copy and pickle are refused.

    These are the ACCIDENTAL duplication paths (B-20): each of them would build
    a second capability without `__init__` ever running, i.e. without the mint
    key ever being checked.
    """

    # 🔴 **Mutation:** delete `__reduce__`. The pickle assertion goes red (and,
    # on a slots dataclass, `copy.copy` would otherwise succeed via the reduce
    # protocol, so `__copy__`'s deletion is caught by the first assertion).
    # ⇒ 本测试必红。
    def test_copy_deepcopy_and_pickle_all_raise(self) -> None:
        cap = mint_capability()
        for label, operation in (
            ("copy.copy", lambda c: copy.copy(c)),
            ("copy.deepcopy", lambda c: copy.deepcopy(c)),
            ("pickle.dumps", lambda c: pickle.dumps(c)),
        ):
            with self.subTest(operation=label):
                with self.assertRaises(CapabilityForgeryError):
                    operation(cap)


# ==========================================================================
# TS-20
# ==========================================================================
class TestTS20SubclassingRefused(unittest.TestCase):
    """TS-20 — subclassing is refused at runtime.

    `@final` is type-checker-only; `__init_subclass__` is the part that holds at
    runtime. This test also guards the `slots=True` class-rebuild subtlety: if
    the dataclass machinery ever swallowed the hook, this test says so.
    """

    # 🔴 **Mutation:** delete `__init_subclass__` (leaving only `@final`, which
    # is type-checker-only). Red. This test also guards the `slots=True`
    # class-rebuild subtlety: if the dataclass machinery ever swallowed the
    # hook, this test says so.
    # ⇒ 本测试必红。
    def test_defining_a_subclass_raises(self) -> None:
        with self.assertRaises(CapabilityForgeryError):

            class Forged(ExecuteCapability):  # noqa: F811 - defined for its side effect
                pass

    def test_subclass_refusal_survives_extra_class_keywords(self) -> None:
        """`__init_subclass__(cls, **kwargs)` must refuse regardless of kwargs."""
        with self.assertRaises(CapabilityForgeryError):

            class ForgedWithKwargs(ExecuteCapability, metaclass=type):
                pass


# ==========================================================================
# TS-21
# ==========================================================================
class TestTS21ExecutorNeedsCapability(unittest.TestCase):
    """TS-21 — the executor cannot be reached without a capability."""

    # 🔴 **Mutation:** drop the action comparison in `require_capability`. Red.
    # ⇒ 本测试必红。
    def test_require_capability_rejects_a_different_action(self) -> None:
        cap = mint_capability()
        with self.assertRaises(CapabilityForgeryError):
            require_capability(cap, "wire_transfer")

    def test_require_capability_returns_the_decoded_arguments(self) -> None:
        """The paired arm: without it, a `require_capability` that always raises
        would satisfy the negative assertion above."""
        cap = mint_capability()
        returned = require_capability(cap, "transfer")
        self.assertEqual(dict(returned), dict(cap.arguments))

    def test_execute_transfer_signature_demands_a_capability(self) -> None:
        signature = inspect.signature(execute_transfer)
        parameters = list(signature.parameters.values())
        self.assertGreaterEqual(len(parameters), 1)

        first = parameters[0]
        self.assertEqual(first.name, "cap")
        self.assertIs(
            first.default,
            inspect.Parameter.empty,
            msg="the authority-bearing parameter must not have a default",
        )
        # The annotation is either the class or its string form, depending on
        # whether the module uses `from __future__ import annotations`.
        self.assertIn(
            first.annotation,
            (ExecuteCapability, "ExecuteCapability"),
            msg=f"first parameter annotated {first.annotation!r}",
        )
        self.assertEqual(parameters[1].name, "ledger")


# ==========================================================================
# TS-22
# ==========================================================================
class TestTS22VerdictInvariant(unittest.TestCase):
    """TS-22 — the Verdict invariant, both directions.

    outcome is ALLOW  <=>  capability is not None  <=>  reasons == ()
    """

    def setUp(self) -> None:
        self.evidence = make_evidence()
        self.capability = mint_capability()

    # 🔴 **Mutation:** delete `Verdict.__post_init__`. Red. Second mutation:
    # check only one direction (`allow == (capability is not None)` without the
    # reasons clause). The third assertion goes red.
    # ⇒ 本测试必红。
    def test_illegal_shapes_raise_policy_error(self) -> None:
        illegal = (
            (
                "ALLOW without a capability",
                (Outcome.ALLOW, None, (), self.evidence),
            ),
            (
                "BLOCK carrying a capability",
                (Outcome.BLOCK, self.capability, (), self.evidence),
            ),
            (
                "ALLOW carrying reasons",
                (
                    Outcome.ALLOW,
                    self.capability,
                    (BlockReason.NO_WITNESS,),
                    self.evidence,
                ),
            ),
        )
        for label, args in illegal:
            with self.subTest(shape=label):
                with self.assertRaises(PolicyError):
                    Verdict(*args)

    def test_the_two_legal_shapes_construct(self) -> None:
        """The paired arm: a `__post_init__` that raised unconditionally would
        satisfy every negative assertion above."""
        allow = Verdict(Outcome.ALLOW, self.capability, (), self.evidence)
        self.assertIs(allow.outcome, Outcome.ALLOW)

        block = Verdict(
            Outcome.BLOCK, None, (BlockReason.NO_WITNESS,), self.evidence
        )
        self.assertIs(block.outcome, Outcome.BLOCK)
        self.assertIsNone(block.capability)


# ==========================================================================
# TS-23
# ==========================================================================
class TestTS23NoFinalWords(unittest.TestCase):
    """TS-23 — empty transcript and all-non-final transcript."""

    # 🔴 **Mutation:** delete the E4 guard **and** the W3 guard separately; each
    # deletion turns one half of this test red.
    # ⇒ 本测试必红。
    def test_empty_transcript_blocks_with_no_final_words(self) -> None:
        """Half one: the E4 guard."""
        verdict = build_gate().evaluate(
            proposal_of("transfer", GROUNDED_ARGS), parse_transcript([])
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)
        self.assertIn(BlockReason.NO_FINAL_WORDS, verdict.reasons)

    def test_all_non_final_transcript_blocks_and_yields_no_witness(self) -> None:
        """Half two: the E4 guard AND the W3 guard, asserted separately."""
        transcript = transcript_of(GROUNDED_UTTERANCE, final=False)
        verdict = build_gate().evaluate(
            proposal_of("transfer", GROUNDED_ARGS), transcript
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.NO_FINAL_WORDS, verdict.reasons)

        witness_set = witnesses_for(GROUNDED_UTTERANCE, final=False)
        self.assertEqual(
            witness_set.witnesses,
            (),
            msg="a non-final word produced a witness -- W3 is not firing",
        )
        self.assertTrue(
            witness_set.rejected,
            msg="no spans were enumerated at all; the fixture is not exercising W3",
        )
        causes = {r.cause for r in witness_set.rejected}
        self.assertEqual(
            causes,
            {RejectCause.NOT_FINAL},
            msg=f"every rejected span must carry NOT_FINAL; got {causes}",
        )


# ==========================================================================
# TS-24
# ==========================================================================
class TestTS24TranscriptTooLong(unittest.TestCase):
    """TS-24 — transcript longer than policy."""

    # 🔴 **Mutation:** raise an exception instead of appending the reason. Red
    # (`assertRaises` is not used; the test asserts a Verdict is returned).
    # ⇒ 本测试必红。
    def test_over_long_transcript_is_a_block_not_an_exception(self) -> None:
        transcript = transcript_of(GROUNDED_UTTERANCE)
        self.assertEqual(
            len(transcript.words),
            9,
            msg="fixture drifted: TS-24 needs a 9-word transcript against a cap of 5",
        )

        gate_obj = build_gate(max_transcript_words=5)
        verdict = gate_obj.evaluate(proposal_of("transfer", GROUNDED_ARGS), transcript)

        # Asserting the TYPE is the whole point: resource exhaustion must not
        # become an unhandled path (B-2).
        self.assertIsInstance(verdict, Verdict)
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.TRANSCRIPT_TOO_LONG, verdict.reasons)
        self.assertIsNone(verdict.capability)


# ==========================================================================
# TS-25
# ==========================================================================
class TestTS25PolicyValidation(unittest.TestCase):
    """TS-25 — policy validation at construction."""

    # 🔴 **Mutation:** delete the `math.isnan` clause specifically. The NaN
    # assertion goes red while the range assertions stay green — which is exactly
    # why NaN is asserted separately rather than folded into a range check.
    # ⇒ 本测试必红。
    def test_illegal_policy_values_raise_at_construction(self) -> None:
        illegal = (
            ("confidence_floor", float("nan")),
            ("confidence_floor", -0.1),
            ("confidence_floor", 1.1),
            ("max_span_words", 0),
            ("role_window", -1),
            ("max_transcript_words", 0),
        )
        for knob, value in illegal:
            with self.subTest(knob=knob, value=repr(value)):
                with self.assertRaises(PolicyError):
                    build_gate(**{knob: value})

    def test_nan_floor_is_refused_on_its_own(self) -> None:
        """Asserted separately from the range cases on purpose.

        `x < nan` is False for every x, so a NaN floor admits every word: it is
        the ONE fail-open value in the domain. Folded into a range check it would
        be invisible, and deleting the `math.isnan` clause would leave the range
        assertions green.
        """
        with self.assertRaises(PolicyError):
            build_gate(confidence_floor=float("nan"))

    def test_legal_policy_values_construct(self) -> None:
        """The paired arm: a `__post_init__` that raised unconditionally would
        satisfy every negative assertion above."""
        self.assertIsInstance(build_gate(), Gate)
        for knob, value in (
            ("confidence_floor", 0.0),
            ("confidence_floor", 1.0),
            ("role_window", 0),
            ("max_span_words", 1),
            ("max_transcript_words", 1),
        ):
            with self.subTest(knob=knob, value=value):
                self.assertIsInstance(build_gate(**{knob: value}), Gate)


# ==========================================================================
# TS-26
# ==========================================================================
BASE_WORD: dict[str, Any] = {
    "text": "two",
    "start": 100,
    "end": 190,
    "confidence": CONF_HIGH,
    "word_is_final": True,
}


def word_with(**changes: Any) -> dict[str, Any]:
    raw = dict(BASE_WORD)
    raw.update(changes)
    return raw


class TestTS26StrictWordParsing(unittest.TestCase):
    """TS-26 — strict word parsing."""

    def test_control_arm_a_well_formed_word_parses(self) -> None:
        """Without this, a `parse_word` that raised unconditionally would pass
        every negative assertion below."""
        word = parse_word(dict(BASE_WORD))
        self.assertEqual(word.text, "two")
        self.assertEqual(word.start, 100)
        self.assertEqual(word.end, 190)
        self.assertEqual(word.confidence, CONF_HIGH)
        self.assertIs(word.word_is_final, True)

    # 🔴 **Mutation:** replace `type(x) is bool` with an `isinstance` inversion,
    # or drop the NaN clause — each drops one assertion to red.
    # ⇒ 本测试必红。
    def test_every_missing_key_raises(self) -> None:
        """The five keys are ENUMERATED FROM `WORD_KEYS`, never re-listed here.

        A hand list would silently stop covering a sixth key the day one is
        added, and the gap would be invisible (DN-1).
        """
        self.assertTrue(WORD_KEYS, msg="WORD_KEYS is empty; the population is wrong")
        for key in sorted(WORD_KEYS):
            with self.subTest(missing_key=key):
                raw = dict(BASE_WORD)
                del raw[key]
                with self.assertRaises(TranscriptFormatError):
                    parse_word(raw)

    def test_malformed_fields_raise(self) -> None:
        malformed = (
            ("confidence is NaN", word_with(confidence=float("nan"))),
            ("confidence above the domain", word_with(confidence=1.5)),
            ("confidence below the domain", word_with(confidence=-0.1)),
            ("end < start", word_with(start=200, end=100)),
            ("word_is_final is int 1, not bool", word_with(word_is_final=1)),
            ("start is a bool where an int is required", word_with(start=True)),
            ("text is None", word_with(text=None)),
        )
        for label, raw in malformed:
            with self.subTest(case=label):
                with self.assertRaises(TranscriptFormatError):
                    parse_word(raw)

    def test_extra_unknown_key_is_ignored(self) -> None:
        with_extra = parse_word(word_with(speaker="A", turn_is_formatted=True))
        without_extra = parse_word(dict(BASE_WORD))
        self.assertEqual(with_extra, without_extra)

    def test_end_equal_to_start_is_accepted(self) -> None:
        """The documented rule is `end < start` raises, so `end == start` must
        not. A zero-length word is a boundary, not an error."""
        word = parse_word(word_with(start=100, end=100))
        self.assertEqual(word.start, word.end)


# ==========================================================================
# TS-27
# ==========================================================================
class TestTS27NonEnglishFailsClosed(unittest.TestCase):
    """TS-27 — non-English input fails closed (ARCHITECTURE V-4).

    The refusal must be EXPLICIT: a Verdict carrying ARGUMENT_UNDECODABLE, not
    a crash and not a silent zero-witness pass.
    """

    # 🔴 **Mutation:** widen `CANONICAL_ALPHABET` to accept anything, or give
    # `canonicalize_text` a strip-and-continue fallback. Red.
    # ⇒ 本测试必红。
    def test_non_ascii_argument_blocks_without_raising(self) -> None:
        utterance = f"please transfer two hundred canadian dollars to {NON_ASCII_NAME}"
        args = dict(GROUNDED_ARGS, to=NON_ASCII_NAME)

        verdict = build_gate().evaluate(
            proposal_of("transfer", args), transcript_of(utterance)
        )

        self.assertIsInstance(verdict, Verdict)
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIsNone(verdict.capability)
        self.assertIn(BlockReason.ARGUMENT_UNDECODABLE, verdict.reasons)

    def test_canonicalize_text_declines_non_ascii_directly(self) -> None:
        """Asserted independently of the gate so the refusal is located, not
        merely observed at the end of a long pipeline.

        🔴 `assertIs`, never a truth test: `Undecodable.__bool__` raises on
        purpose, and `if decoded:` is the exact shape TS-39 forbids.
        """
        self.assertIs(canonicalize_text(NON_ASCII_NAME), VALUE_UNDECODABLE)


# ==========================================================================
# TS-28
# ==========================================================================
class TestTS28ArgumentSetMismatch(unittest.TestCase):
    """TS-28 — undeclared and missing arguments."""

    # 🔴 **Mutation:** delete either E7 set-difference loop. One assertion each
    # goes red.
    # ⇒ 本测试必红。
    def test_undeclared_argument_blocks(self) -> None:
        args = dict(GROUNDED_ARGS, memo="hi")
        verdict = build_gate().evaluate(
            proposal_of("transfer", args), transcript_of(GROUNDED_UTTERANCE)
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.UNDECLARED_ARGUMENT, verdict.reasons)
        self.assertIsNone(verdict.capability)

    def test_missing_argument_blocks(self) -> None:
        args = {k: v for k, v in GROUNDED_ARGS.items() if k != "currency"}
        verdict = build_gate().evaluate(
            proposal_of("transfer", args), transcript_of(GROUNDED_UTTERANCE)
        )
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.MISSING_ARGUMENT, verdict.reasons)
        self.assertIsNone(verdict.capability)


# ==========================================================================
# TS-29
# ==========================================================================
class TestTS29UnregisteredAction(unittest.TestCase):
    """TS-29 — unregistered action."""

    # 🔴 **Mutation:** continue into E7 with `spec=None`. The test's "no per-param
    # reasons" assertion goes red, or an AttributeError escapes — either way, red.
    # ⇒ 本测试必红。
    def test_unregistered_action_blocks_before_any_per_param_work(self) -> None:
        gate_obj = build_gate(registry=reference_registry())
        verdict = gate_obj.evaluate(
            proposal_of("launch_missiles", GROUNDED_ARGS),
            transcript_of(GROUNDED_UTTERANCE),
        )

        self.assertIsInstance(verdict, Verdict)
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.ACTION_NOT_REGISTERED, verdict.reasons)

        # The set of per-parameter reasons is DERIVED from the closed enum by
        # subtracting the four E2/E3/E4/E6 reasons -- so a BlockReason added
        # later lands on the "must not appear" side automatically. A hand list
        # here would go stale silently, which is the DN-1 accident.
        leaked = set(verdict.reasons) & PER_PARAM_REASONS
        self.assertEqual(
            leaked,
            set(),
            msg=f"E6 must jump to E11; these per-param reasons leaked: {leaked}",
        )
        self.assertEqual(
            verdict.evidence.records,
            (),
            msg="no per-param work may run against an unknown spec (B-10)",
        )


# ==========================================================================
# TS-30
# ==========================================================================
def _boom_checker(ctx: Any) -> Any:
    raise RuntimeError("boom")


class TestTS30CheckerRaises(unittest.TestCase):
    """TS-30 — a checker that raises."""

    # 🔴 **Mutation:** remove the `try/except`. The test goes red with an
    # escaping `RuntimeError`. Second mutation: catch and record but do **not**
    # append the reason. Red — this is the "swallowed exception becomes a pass"
    # direction.
    # ⇒ 本测试必红。
    def test_a_raising_checker_becomes_a_block_reason(self) -> None:
        # Derived from the shipped table, not rebuilt by hand: any checker the
        # package ships stays wired, and only WITNESS_PRESENT is swapped.
        checkers = dict(STANDARD_CHECKERS)
        self.assertIn(
            CheckId.WITNESS_PRESENT,
            checkers,
            msg="STANDARD_CHECKERS no longer ships WITNESS_PRESENT; fixture is stale",
        )
        checkers[CheckId.WITNESS_PRESENT] = _boom_checker

        gate_obj = build_gate(checkers=MappingProxyType(checkers))
        verdict = gate_obj.evaluate(
            proposal_of("transfer", GROUNDED_ARGS), transcript_of(GROUNDED_UTTERANCE)
        )

        self.assertIsInstance(verdict, Verdict)
        self.assertIs(verdict.outcome, Outcome.BLOCK)
        self.assertIn(BlockReason.CHECKER_RAISED, verdict.reasons)
        self.assertIsNone(verdict.capability)

        raised = [r for r in verdict.evidence.records if r.outcome == "raised"]
        self.assertTrue(
            raised, msg=f"no record with outcome 'raised': {verdict.evidence.records}"
        )
        self.assertTrue(
            any("boom" in r.detail for r in raised),
            msg=f"the exception text was swallowed: {[r.detail for r in raised]}",
        )


# ==========================================================================
# TS-31
# ==========================================================================
def _snapshot(verdict: Verdict) -> tuple[Any, ...]:
    return (verdict.outcome, verdict.reasons, verdict.capability is not None)


class TestTS31DeterminismAndThreadSafety(unittest.TestCase):
    """TS-31 — determinism and thread safety."""

    REPEATS = 50
    THREADS = 8

    # 🔴 **Mutation:** replace a `sorted(...)` in E7/E8/E9 with `set` iteration,
    # or cache a witness set on `self` via `object.__setattr__`. Red.
    # ⇒ 本测试必红。
    def test_reason_ordering_is_deterministic(self) -> None:
        gate_obj = build_gate()
        proposal = proposal_of("transfer", STREET_ARGS)
        transcript = transcript_of(STREET_UTTERANCE)

        snapshots = [
            _snapshot(gate_obj.evaluate(proposal, transcript))
            for _ in range(self.REPEATS)
        ]
        first = snapshots[0]
        # A BLOCK with at least two reasons is what makes ordering observable;
        # if the fixture ever degenerates to one reason this assertion says so
        # rather than passing vacuously.
        self.assertIs(first[0], Outcome.BLOCK, msg=f"snapshot={first}")
        for index, snapshot in enumerate(snapshots):
            self.assertEqual(
                snapshot, first, msg=f"evaluation #{index} diverged: {snapshot}"
            )

    def test_one_shared_gate_under_eight_threads(self) -> None:
        gate_obj = build_gate()
        cases = (
            (proposal_of("transfer", STREET_ARGS), transcript_of(STREET_UTTERANCE)),
            (proposal_of("transfer", GROUNDED_ARGS), transcript_of(GROUNDED_UTTERANCE)),
        )
        baseline = [_snapshot(gate_obj.evaluate(p, t)) for p, t in cases]

        # The two fixtures must not agree, or interleaving proves nothing.
        self.assertNotEqual(
            baseline[0],
            baseline[1],
            msg="both fixtures gave the same verdict; the interleaving is not "
            "discriminating",
        )

        results: list[list[tuple[int, tuple[Any, ...]]]] = [
            [] for _ in range(self.THREADS)
        ]
        errors: list[BaseException] = []
        barrier = threading.Barrier(self.THREADS)

        def worker(slot: int) -> None:
            try:
                barrier.wait(timeout=30)
                for n in range(self.REPEATS):
                    which = (slot + n) % len(cases)
                    proposal, transcript = cases[which]
                    results[slot].append(
                        (which, _snapshot(gate_obj.evaluate(proposal, transcript)))
                    )
            except BaseException as exc:  # noqa: BLE001 - recorded, then asserted
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(slot,), name=f"gate-{slot}")
            for slot in range(self.THREADS)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(errors, [], msg=f"threads raised: {errors}")
        for slot, produced in enumerate(results):
            self.assertEqual(
                len(produced),
                self.REPEATS,
                msg=f"thread {slot} produced {len(produced)} results",
            )
            for index, (which, snapshot) in enumerate(produced):
                self.assertEqual(
                    snapshot,
                    baseline[which],
                    msg=(
                        f"thread {slot} evaluation #{index} on fixture {which} "
                        f"diverged from the single-threaded result"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
