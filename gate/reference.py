# ============================================================================
# gate/reference.py
# ============================================================================
"""The registry the demo actually ships. See reference_registry()."""

from types import MappingProxyType
from typing import Final

from collections.abc import Mapping

from .normalize import ValueKind
from .registry import (
    ActionRegistry,
    ActionSpec,
    CheckId,
    CheckRequirement,
    CheckStatus,
    ParamSpec,
    Reversibility,
)
from .roles import SemanticRole

# Shared by all three "transfer" parameters: WITNESS_PRESENT / ROLE_MATCH /
# CONFIDENCE_FLOOR are REQUIRED (grounding is mandatory for every argument of an
# irreversible action); READ_BACK_CONFIRMED is NOT_IMPLEMENTED because the
# read-back dialogue is out of scope this round. It is safe to share one
# MappingProxyType across all three ParamSpecs: CheckRequirement is a frozen
# dataclass, so there is nothing in this mapping any caller could mutate.
_STANDARD_PARAM_CHECKS: Final[Mapping[CheckId, CheckRequirement]] = MappingProxyType({
    CheckId.WITNESS_PRESENT: CheckRequirement(
        status=CheckStatus.REQUIRED,
        rationale="grounding requires a witness for the value under the required role",
    ),
    CheckId.ROLE_MATCH: CheckRequirement(
        status=CheckStatus.REQUIRED,
        rationale=(
            "grounding requires the witness's role to match the parameter's "
            "declared role, not merely the value to appear somewhere in the "
            "transcript"
        ),
    ),
    CheckId.CONFIDENCE_FLOOR: CheckRequirement(
        status=CheckStatus.REQUIRED,
        rationale=(
            "grounding requires every word of the witnessing span to clear the "
            "configured confidence floor"
        ),
    ),
    CheckId.READ_BACK_CONFIRMED: CheckRequirement(
        status=CheckStatus.NOT_IMPLEMENTED,
        rationale=(
            "read-back dialogue is out of scope this round (ARCHITECTURE section 4). "
            "Flipping this entry to NOT_REQUIRED on an IRREVERSIBLE action accepts "
            "B-31: a model may propose a proper prefix of the spoken recipient "
            "phrase and it will be grounded. lint_deployment names this."
        ),
    ),
})


def reference_registry() -> ActionRegistry:
    """The registry the demo actually ships.

    `transfer` is IRREVERSIBLE with params:
      amount   : ValueKind.NUMBER,        required_role MONEY_AMOUNT
      currency : ValueKind.CURRENCY_CODE, required_role CURRENCY
      to       : ValueKind.TEXT,          required_role RECIPIENT
    Every param carries all four CheckId keys. WITNESS_PRESENT / ROLE_MATCH /
    CONFIDENCE_FLOOR are REQUIRED.

    🔴 READ_BACK_CONFIRMED is NOT_IMPLEMENTED, and its rationale (see
    _STANDARD_PARAM_CHECKS above for the exact string) names B-31 explicitly: a
    deployer who flips this entry to NOT_REQUIRED on this IRREVERSIBLE action is
    accepting that a model may propose a proper PREFIX of the spoken recipient
    phrase and have it grounded. The rationale is where a deployer makes that
    decision, so that is where the residue is written down.
    Consequence, stated plainly rather than hidden: this registry BLOCKS every
    transfer, including perfectly grounded ones. That is the deny-by-default rule
    doing its job, and TS-42 asserts it so the honesty cannot rot."""
    params: Mapping[str, ParamSpec] = MappingProxyType({
        "amount": ParamSpec(
            name="amount",
            value_kind=ValueKind.NUMBER,
            required_role=SemanticRole.MONEY_AMOUNT,
            checks=_STANDARD_PARAM_CHECKS,
        ),
        "currency": ParamSpec(
            name="currency",
            value_kind=ValueKind.CURRENCY_CODE,
            required_role=SemanticRole.CURRENCY,
            checks=_STANDARD_PARAM_CHECKS,
        ),
        "to": ParamSpec(
            name="to",
            value_kind=ValueKind.TEXT,
            required_role=SemanticRole.RECIPIENT,
            checks=_STANDARD_PARAM_CHECKS,
        ),
    })

    transfer = ActionSpec(
        name="transfer",
        reversibility=Reversibility.IRREVERSIBLE,
        params=params,
    )

    return ActionRegistry(actions=MappingProxyType({"transfer": transfer}))
