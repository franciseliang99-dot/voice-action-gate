# ============================================================================
# gate/checks.py
# ============================================================================
"""Checkers: the REQUIRED-status implementations the registry can reference.

Every checker here is veto-only — it can add a BlockReason, never remove one
and never itself construct anything that looks like a pass beyond CheckOk().
Nothing in this module can mint an ExecuteCapability; that is decision.py's
sole responsibility."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol, TypeAlias, final

from .normalize import Decoded
from .reasons import BlockReason
from .registry import CheckId, ParamSpec
from .witness import WitnessSet


@final
@dataclass(frozen=True, slots=True)
class CheckContext:
    action: str
    param: ParamSpec
    argument: Decoded          # already decoded; a checker never sees the raw proposal value
    witnesses: WitnessSet
    confidence_floor: float
# Extension point for read-back (ARCHITECTURE section 4): wiring it means adding a
# `confirmation: Transcript` field here, implementing a Checker, registering it in
# STANDARD_CHECKERS, and flipping the registry entry to REQUIRED. Three visible
# edits. No dead placeholder field is added today.


@final
@dataclass(frozen=True, slots=True)
class CheckOk:
    pass


@final
@dataclass(frozen=True, slots=True)
class CheckFailed:
    reason: BlockReason
    detail: str


CheckOutcome: TypeAlias = CheckOk | CheckFailed


class Checker(Protocol):
    def __call__(self, ctx: CheckContext) -> CheckOutcome: ...


def check_witness_present(ctx: CheckContext) -> CheckOutcome:
    """Ok iff the value is present under some role -- expressed via
    `ctx.witnesses.explain(v, role) is not BlockReason.NO_WITNESS`.
    Failed(NO_WITNESS) otherwise."""
    value = ctx.argument.value
    role = ctx.param.required_role
    # `WitnessSet.explain`'s documented precondition is `satisfies(value, role) is
    # False`. When satisfies() is already True the value is trivially "present
    # under some role" (that role, specifically), so we short-circuit to Ok
    # without calling explain() and without violating its precondition.
    if ctx.witnesses.satisfies(value, role):
        return CheckOk()
    reason = ctx.witnesses.explain(value, role)
    if reason is BlockReason.NO_WITNESS:
        return CheckFailed(
            reason=BlockReason.NO_WITNESS,
            detail=f"no witness in the transcript grounds value {value!r} under any role",
        )
    return CheckOk()


def check_role_match(ctx: CheckContext) -> CheckOutcome:
    """Ok iff ctx.witnesses.satisfies(ctx.argument.value, ctx.param.required_role).
    Failed(ctx.witnesses.explain(...)) otherwise.
    🔴 This is the check that makes the gate a parser instead of a matcher."""
    value = ctx.argument.value
    role = ctx.param.required_role
    if ctx.witnesses.satisfies(value, role):
        return CheckOk()
    reason = ctx.witnesses.explain(value, role)
    return CheckFailed(
        reason=reason,
        detail=(
            f"no witness grounds value {value!r} under required role "
            f"{role.value!r}"
        ),
    )


def check_confidence_floor(ctx: CheckContext) -> CheckOutcome:
    """Failed(CONFIDENCE_BELOW_FLOOR) iff
    ctx.witnesses.rejected_for_confidence(ctx.argument.value). Ok otherwise.
    Veto-only: it can add a reason, never remove one."""
    value = ctx.argument.value
    if ctx.witnesses.rejected_for_confidence(value):
        return CheckFailed(
            reason=BlockReason.CONFIDENCE_BELOW_FLOOR,
            detail=(
                f"a span decoding to {value!r} was rejected for falling below "
                f"the configured confidence floor {ctx.confidence_floor!r}"
            ),
        )
    return CheckOk()


STANDARD_CHECKERS: Final[Mapping[CheckId, Checker]] = MappingProxyType({
    CheckId.WITNESS_PRESENT: check_witness_present,
    CheckId.ROLE_MATCH: check_role_match,
    CheckId.CONFIDENCE_FLOOR: check_confidence_floor,
})
# 🔴 CheckId.READ_BACK_CONFIRMED is deliberately absent. Any registry that marks it
# REQUIRED against this table fails lint L1 at load time -- loudly. Any registry
# that marks it NOT_IMPLEMENTED on an irreversible action blocks that action at
# runtime. Both failures are visible; neither is silent.
