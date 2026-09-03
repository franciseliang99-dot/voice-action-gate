# ============================================================================
# gate/decision.py      🔴 THE ONLY MODULE THAT CAN MINT AN ExecuteCapability.
# ============================================================================
"""Honest boundary -- required by the brief, and NOT to be strengthened:

    An `ExecuteCapability` can only be constructed here, because `_MINT_KEY` is a
    module-private object and `__post_init__` rejects anything else. What that buys
    is that BYPASSING THE GATE MUST BE AN EXPLICIT, VISIBLE EDIT -- a new call site
    that passes `_MINT_KEY`, or a new module that imports it. It is NOT
    "impossible to bypass".

    Specifically, these remain open and we say so:
      - anyone who can edit this file can add a second minting site;
      - `object.__new__(ExecuteCapability)` followed by `object.__setattr__`
        fabricates one without ever calling `__init__`;
      - `gate.decision._MINT_KEY` is importable by any code in the process;
      - `unittest.mock.patch` can replace any of this at runtime.
    What stops those is code review and the load-time lint, not the type system.
    Do not upgrade this paragraph into a security claim."""

import math
from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from types import MappingProxyType
from typing import Final, NoReturn, final

from .checks import CheckContext, CheckFailed, CheckOk, Checker
from .errors import CapabilityForgeryError, PolicyError
from .normalize import Normalization, ScalarValue, Undecodable, decode_argument
from .proposal import Proposal
from .reasons import BlockReason, Outcome
from .registry import ActionRegistry, CheckId, CheckStatus, Reversibility, lint_registry
from .roles import SemanticRole
from .transcript import TextExtractor, Transcript, TranscriptProvenance
from .witness import Witness, WitnessSet, generate_witnesses

_MINT_KEY: Final[object] = object()
__all__ = [
    "ExecuteCapability", "Gate", "Verdict", "Evidence", "CheckRecord",
]   # _MINT_KEY is deliberately not exported.


@final
@dataclass(frozen=True, slots=True)
class ExecuteCapability:
    action: str
    arguments: Mapping[str, ScalarValue]   # 🔴 the DECODED, grounded values -- not the
                                           # raw proposal. The executor reads these.
    evidence: "Evidence"
    _mint_key: InitVar[object]

    def __post_init__(self, _mint_key: object) -> None:
        """Raises CapabilityForgeryError unless `_mint_key is _MINT_KEY`."""
        if _mint_key is not _MINT_KEY:
            raise CapabilityForgeryError(
                "ExecuteCapability may only be constructed by "
                "gate.decision.Gate.evaluate; no other call site holds a valid "
                "mint key."
            )

    def __init_subclass__(cls, **kwargs: object) -> NoReturn:
        """Runtime refusal to subclass. `@final` is type-checker-only; this is the
        part that holds at runtime."""
        raise CapabilityForgeryError(
            f"ExecuteCapability may not be subclassed (attempted by {cls.__name__!r})."
        )

    def __reduce__(self) -> NoReturn:      # refuses pickle
        raise CapabilityForgeryError("ExecuteCapability refuses pickling.")

    def __copy__(self) -> NoReturn:        # refuses copy.copy
        raise CapabilityForgeryError("ExecuteCapability refuses copy.copy.")

    def __deepcopy__(self, memo: dict) -> NoReturn:  # refuses copy.deepcopy
        raise CapabilityForgeryError("ExecuteCapability refuses copy.deepcopy.")
    # These three close the *accidental* duplication paths, which would otherwise
    # bypass __init__ silently. They do not close object.__new__ (see docstring).


@final
@dataclass(frozen=True, slots=True)
class CheckRecord:
    param: str
    check: CheckId
    status: CheckStatus | None      # None == ABSENT
    outcome: str                    # "ok"|"failed"|"skipped"|"not_implemented"|"absent"|"missing"|"raised"
    reason: BlockReason | None
    detail: str


@final
@dataclass(frozen=True, slots=True)
class Evidence:
    """Every policy value that produced this decision is recorded, so a decision
    can be re-judged against a later calibration instead of silently inheriting it.
    `provenance` in particular is what lets a future V-1 re-measurement invalidate
    past decisions rather than silently reinterpret them."""

    provenance: TranscriptProvenance
    confidence_floor: float
    max_span_words: int
    role_window: int
    max_transcript_words: int
    witness_count: int
    rejected_count: int
    matched: Mapping[str, Witness]      # param name -> the witness that grounded it
    records: tuple[CheckRecord, ...]


@final
@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Outcome
    capability: ExecuteCapability | None
    reasons: tuple[BlockReason, ...]
    evidence: Evidence

    def __post_init__(self) -> None:
        """🔴 Enforces, by raising PolicyError:
             outcome is ALLOW  <=>  capability is not None  <=>  reasons == ()
        Both directions. A Verdict that says BLOCK while carrying a capability, or
        ALLOW while carrying reasons, cannot exist."""
        is_allow = self.outcome is Outcome.ALLOW
        has_capability = self.capability is not None
        has_no_reasons = self.reasons == ()
        if not (is_allow == has_capability == has_no_reasons):
            raise PolicyError(
                "Verdict invariant violated: outcome is ALLOW <=> capability is "
                "not None <=> reasons == () must hold in both directions; got "
                f"outcome={self.outcome!r}, capability_present={has_capability!r}, "
                f"reasons={self.reasons!r}."
            )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Gate:
    registry: ActionRegistry
    checkers: Mapping[CheckId, Checker]
    text_of: TextExtractor
    provenance: TranscriptProvenance
    confidence_floor: float
    max_span_words: int
    role_window: int
    max_transcript_words: int
    require_known_provenance: bool
    # 🔴 Zero defaults. Every knob is an argument the caller had to type. The
    # confidence floor in particular has no default and no module constant:
    # ARCHITECTURE V-2 measured a distribution on studio broadcast audio, which is
    # not this product's domain, so any number written here would be cited as a
    # result. TS-34 fails if any parameter anywhere in gate/ acquires a default.

    def __post_init__(self) -> None:
        """LOAD TIME. In this order:
          P1 raise PolicyError if confidence_floor is not a real float, is NaN
             (math.isnan), or lies outside [0.0, 1.0].
             🔴 The NaN case is the fail-open one: `x < nan` is False for every x,
             so a NaN floor would accept every word silently.
          P2 raise PolicyError if max_span_words < 1, role_window < 0,
             or max_transcript_words < 1.
          P3 lint_registry(self.registry, self.checkers)  -> RegistryLintError
        """
        if not isinstance(self.confidence_floor, float):
            raise PolicyError(
                "confidence_floor must be a real float, got "
                f"{type(self.confidence_floor).__name__}: {self.confidence_floor!r}"
            )
        if math.isnan(self.confidence_floor):
            # 🔴 The NaN case is the fail-open one: `x < nan` is False for every
            # x, so a NaN floor would accept every word silently.
            raise PolicyError("confidence_floor must not be NaN")
        if not (0.0 <= self.confidence_floor <= 1.0):
            raise PolicyError(
                f"confidence_floor must lie in [0.0, 1.0], got {self.confidence_floor!r}"
            )
        if self.max_span_words < 1:
            raise PolicyError(f"max_span_words must be >= 1, got {self.max_span_words!r}")
        if self.role_window < 0:
            raise PolicyError(f"role_window must be >= 0, got {self.role_window!r}")
        if self.max_transcript_words < 1:
            raise PolicyError(
                f"max_transcript_words must be >= 1, got {self.max_transcript_words!r}"
            )
        lint_registry(self.registry, self.checkers)

    def evaluate(self, proposal: Proposal, transcript: Transcript) -> Verdict:
        """Pre : both arguments already parsed by parse_proposal / parse_transcript.
        Post: a Verdict. Never raises for adversarial *content* -- adversarial
              content produces BLOCK, not an exception. Raises only PolicyError if
              the Verdict invariant is violated (a bug in this method).

        Steps, in this order. E5 precedes any read of proposal.arguments; that
        ordering is the D1 red line and TS-2 is its behavioural pin.

          E1  reasons: list[BlockReason] = []
          E2  if self.require_known_provenance and
                 self.provenance.formatting_enabled is None:
                  reasons.append(TRANSCRIPT_PROVENANCE_UNKNOWN)
          E3  if len(transcript.words) > self.max_transcript_words:
                  reasons.append(TRANSCRIPT_TOO_LONG)
          E4  if not any(w.word_is_final for w in transcript.words):
                  reasons.append(NO_FINAL_WORDS)
          E5  witnesses = generate_witnesses(transcript, text_of=self.text_of,
                              confidence_floor=self.confidence_floor,
                              max_span_words=self.max_span_words,
                              role_window=self.role_window)
          E6  spec = self.registry.get(proposal.action)
              if spec is None: reasons.append(ACTION_NOT_REGISTERED); goto E11
          E7  declared = set(spec.params); supplied = set(proposal.arguments)
              for name in sorted(declared - supplied): reasons.append(MISSING_ARGUMENT)
              for name in sorted(supplied - declared): reasons.append(UNDECLARED_ARGUMENT)
          E8  for name in sorted(declared & supplied):
                  pspec = spec.params[name]
                  decoded = decode_argument(proposal.arguments[name], pspec.value_kind)
                  if isinstance(decoded, Undecodable):
                      reasons.append(ARGUMENT_UNDECODABLE); continue
                  E9 for check_id in sorted(CheckId, key=lambda c: c.name):
                       status = self.registry.status(proposal.action, name, check_id)
                       if status is None:
                           record "absent";        reasons.append(CHECK_ABSENT)
                       elif status is NOT_REQUIRED:
                           record "skipped"
                       elif status is NOT_IMPLEMENTED:
                           if spec.reversibility is Reversibility.IRREVERSIBLE:
                               record "not_implemented"
                               reasons.append(CHECK_NOT_IMPLEMENTED)
                           else:
                               record "skipped"
                       else:  # REQUIRED
                           checker = self.checkers.get(check_id)
                           if checker is None:
                               record "missing"; reasons.append(CHECKER_MISSING)
                           else:
                               try:    outcome = checker(CheckContext(...))
                               except Exception:
                                       record "raised"; reasons.append(CHECKER_RAISED)
                               else:
                                   if isinstance(outcome, CheckFailed):
                                       record "failed"; reasons.append(outcome.reason)
                                   else:
                                       record "ok"
                  on success, remember the grounding witness in `matched[name]`
          E10 dedupe reasons preserving first-seen order -> tuple
          E11 evidence = Evidence(...)   # always built, for BLOCK and ALLOW alike
          E12 if reasons: return Verdict(BLOCK, None, tuple(reasons), evidence)
          E13 return Verdict(ALLOW,
                             ExecuteCapability(action=proposal.action,
                                               arguments=MappingProxyType(dict(decoded_args)),
                                               evidence=evidence,
                                               _mint_key=_MINT_KEY),
                             (), evidence)

        🔴 E13 is the ONLY expression in this package that passes `_MINT_KEY`, and
        it is unreachable while `reasons` is non-empty because E12 returns first.
        TS-37 (as rewritten by A7) asserts three AST `Name(id="_MINT_KEY")`
        occurrences, ALL in this file and each in a named role: the module-level
        definition, the guard comparison in `ExecuteCapability.__post_init__`,
        and E13's `_mint_key=` keyword. Every other file under gate/ contains the
        substring zero times. (The earlier wording said "exactly twice" and named
        only two of the three roles -- it omitted the guard, and it conflated the
        AST count with the raw-substring count, which is 12 in this file because
        the prose above mentions the name. Corrected by A20.3.)

        🔴 WHAT A WITNESS SET IS AND IS NOT (contract text, verbatim -- it lives
        here rather than only in the design document because a caller reads this
        docstring and does not read design_v3.md, and B-31 is a live fail-open):

        A witness set is evidence that a value was **spoken**, not evidence that
        it was spoken **as this argument**. Role tagging narrows the second
        question; it does not answer it. Callers must not read `NO_WITNESS`'s
        absence as confirmation that the proposal matches the speaker's intent."""
        # E1
        reasons: list[BlockReason] = []
        records: list[CheckRecord] = []
        matched: dict[str, Witness] = {}
        decoded_args: dict[str, ScalarValue] = {}

        # E2
        if self.require_known_provenance and self.provenance.formatting_enabled is None:
            reasons.append(BlockReason.TRANSCRIPT_PROVENANCE_UNKNOWN)

        # E3
        if len(transcript.words) > self.max_transcript_words:
            reasons.append(BlockReason.TRANSCRIPT_TOO_LONG)

        # E4
        if not any(w.word_is_final for w in transcript.words):
            reasons.append(BlockReason.NO_FINAL_WORDS)

        # E5 -- runs before any read of proposal.arguments (the D1 red line).
        witnesses: WitnessSet = generate_witnesses(
            transcript,
            text_of=self.text_of,
            confidence_floor=self.confidence_floor,
            max_span_words=self.max_span_words,
            role_window=self.role_window,
        )

        # E6
        spec = self.registry.get(proposal.action)
        if spec is None:
            reasons.append(BlockReason.ACTION_NOT_REGISTERED)
        else:
            # E7
            declared = set(spec.params)
            supplied = set(proposal.arguments)
            for _name in sorted(declared - supplied):
                reasons.append(BlockReason.MISSING_ARGUMENT)
            for _name in sorted(supplied - declared):
                reasons.append(BlockReason.UNDECLARED_ARGUMENT)

            # E8
            for name in sorted(declared & supplied):
                pspec = spec.params[name]
                decoded: Normalization = decode_argument(
                    proposal.arguments[name], pspec.value_kind
                )
                if isinstance(decoded, Undecodable):
                    reasons.append(BlockReason.ARGUMENT_UNDECODABLE)
                    continue

                param_ok = True
                # E9
                for check_id in sorted(CheckId, key=lambda c: c.name):
                    status = self.registry.status(proposal.action, name, check_id)
                    if status is None:
                        records.append(CheckRecord(
                            param=name, check=check_id, status=None,
                            outcome="absent", reason=BlockReason.CHECK_ABSENT,
                            detail=(
                                f"no CheckRequirement is written down for "
                                f"({proposal.action!r}, {name!r}, {check_id.value!r})"
                            ),
                        ))
                        reasons.append(BlockReason.CHECK_ABSENT)
                        param_ok = False
                    elif status is CheckStatus.NOT_REQUIRED:
                        records.append(CheckRecord(
                            param=name, check=check_id, status=status,
                            outcome="skipped", reason=None,
                            detail=f"{check_id.value} is NOT_REQUIRED for {name!r}",
                        ))
                    elif status is CheckStatus.NOT_IMPLEMENTED:
                        if spec.reversibility is Reversibility.IRREVERSIBLE:
                            records.append(CheckRecord(
                                param=name, check=check_id, status=status,
                                outcome="not_implemented",
                                reason=BlockReason.CHECK_NOT_IMPLEMENTED,
                                detail=(
                                    f"{check_id.value} is NOT_IMPLEMENTED on an "
                                    f"IRREVERSIBLE action; deny-by-default blocks "
                                    f"{proposal.action!r}"
                                ),
                            ))
                            reasons.append(BlockReason.CHECK_NOT_IMPLEMENTED)
                            param_ok = False
                        else:
                            records.append(CheckRecord(
                                param=name, check=check_id, status=status,
                                outcome="skipped", reason=None,
                                detail=(
                                    f"{check_id.value} is NOT_IMPLEMENTED but "
                                    f"{proposal.action!r} is REVERSIBLE, so it is "
                                    f"skipped rather than blocked"
                                ),
                            ))
                    else:  # REQUIRED
                        checker = self.checkers.get(check_id)
                        if checker is None:
                            records.append(CheckRecord(
                                param=name, check=check_id, status=status,
                                outcome="missing", reason=BlockReason.CHECKER_MISSING,
                                detail=(
                                    f"{check_id.value} is REQUIRED but no Checker "
                                    f"implementation was supplied for it"
                                ),
                            ))
                            reasons.append(BlockReason.CHECKER_MISSING)
                            param_ok = False
                        else:
                            try:
                                outcome = checker(CheckContext(
                                    action=proposal.action,
                                    param=pspec,
                                    argument=decoded,
                                    witnesses=witnesses,
                                    confidence_floor=self.confidence_floor,
                                ))
                            except Exception as exc:
                                records.append(CheckRecord(
                                    param=name, check=check_id, status=status,
                                    outcome="raised", reason=BlockReason.CHECKER_RAISED,
                                    detail=f"{type(exc).__name__}: {exc}",
                                ))
                                reasons.append(BlockReason.CHECKER_RAISED)
                                param_ok = False
                            else:
                                if isinstance(outcome, CheckFailed):
                                    records.append(CheckRecord(
                                        param=name, check=check_id, status=status,
                                        outcome="failed", reason=outcome.reason,
                                        detail=outcome.detail,
                                    ))
                                    reasons.append(outcome.reason)
                                    param_ok = False
                                else:
                                    records.append(CheckRecord(
                                        param=name, check=check_id, status=status,
                                        outcome="ok", reason=None,
                                        detail=f"{check_id.value} passed for {name!r}",
                                    ))

                # on success, remember the decoded value and the grounding witness
                if param_ok:
                    decoded_args[name] = decoded.value
                    grounding = _find_grounding_witness(
                        witnesses, decoded.value, pspec.required_role
                    )
                    if grounding is not None:
                        matched[name] = grounding

        # E10 -- dedupe reasons preserving first-seen order.
        seen: set[BlockReason] = set()
        deduped_reasons: list[BlockReason] = []
        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                deduped_reasons.append(reason)
        reasons_tuple: tuple[BlockReason, ...] = tuple(deduped_reasons)

        # E11 -- Evidence is always built, for BLOCK and ALLOW alike.
        evidence = Evidence(
            provenance=self.provenance,
            confidence_floor=self.confidence_floor,
            max_span_words=self.max_span_words,
            role_window=self.role_window,
            max_transcript_words=self.max_transcript_words,
            witness_count=len(witnesses.witnesses),
            rejected_count=len(witnesses.rejected),
            matched=MappingProxyType(dict(matched)),
            records=tuple(records),
        )

        # E12
        if reasons_tuple:
            return Verdict(Outcome.BLOCK, None, reasons_tuple, evidence)

        # E13 -- the ONLY expression in this package that passes `_MINT_KEY`, and
        # it is unreachable while `reasons_tuple` is non-empty because E12 returns
        # first.
        return Verdict(
            Outcome.ALLOW,
            ExecuteCapability(
                action=proposal.action,
                arguments=MappingProxyType(dict(decoded_args)),
                evidence=evidence,
                _mint_key=_MINT_KEY,
            ),
            (),
            evidence,
        )


def _find_grounding_witness(
    witnesses: WitnessSet, value: ScalarValue, role: SemanticRole
) -> Witness | None:
    """Locates the witness that grounds a parameter which has already passed its
    checks, for Evidence.matched. Reads only `witnesses.witnesses` -- never
    `witnesses.rejected` -- mirroring the same veto-only discipline
    `WitnessSet.satisfies` enforces (see B-12): a rejected span can never be
    reported as the thing that grounded a decision."""
    for witness in witnesses.witnesses:
        if witness.value == value and witness.role is role:
            return witness
    return None
