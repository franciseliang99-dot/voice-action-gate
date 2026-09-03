# ============================================================================
# gate/registry.py
# ============================================================================
"""Declares what an action needs, and in what state each check for each of
its parameters currently is. This is data, not behaviour: a Gate reads it at
__post_init__ time (lint_registry) and again on every evaluate() call
(Gate.evaluate E9) to decide which checks to run, skip, or treat as a
load-time-visible gap."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, final

from .errors import DeploymentLintError, RegistryLintError
from .normalize import ValueKind
from .roles import SemanticRole

if TYPE_CHECKING:                       # avoids a runtime import cycle with checks.py
    from .checks import Checker


class Reversibility(Enum):
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class CheckId(Enum):
    """The closed universe of checks. Because it is closed, lint rule L2 can
    demand total coverage mechanically."""
    WITNESS_PRESENT = "witness_present"
    ROLE_MATCH = "role_match"
    CONFIDENCE_FLOOR = "confidence_floor"
    READ_BACK_CONFIRMED = "read_back_confirmed"   # interface slot; no implementation


class CheckStatus(Enum):
    REQUIRED = "REQUIRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
# The fourth state, ABSENT, is not a member: it is `ActionRegistry.status(...) is None`.
# It is unrepresentable on purpose -- you cannot *write down* ABSENT, you can only
# fail to write anything, which is what lint L2 detects.


@final
@dataclass(frozen=True, slots=True)
class CheckRequirement:
    status: CheckStatus
    rationale: str      # no default: lint L6 requires non-empty for NOT_REQUIRED
                        # and NOT_IMPLEMENTED. "We decided not to check this" must
                        # be a sentence someone wrote, not an omission.


@final
@dataclass(frozen=True, slots=True)
class ParamSpec:
    name: str
    value_kind: ValueKind
    required_role: SemanticRole
    checks: Mapping[CheckId, CheckRequirement]


@final
@dataclass(frozen=True, slots=True)
class ActionSpec:
    name: str
    reversibility: Reversibility
    params: Mapping[str, ParamSpec]


COMPATIBLE_ROLE_KINDS: Final[Mapping[ValueKind, frozenset[SemanticRole]]] = MappingProxyType({
    ValueKind.NUMBER: frozenset({
        SemanticRole.MONEY_AMOUNT, SemanticRole.STREET_NUMBER, SemanticRole.CLOCK_TIME}),
    ValueKind.CURRENCY_CODE: frozenset({SemanticRole.CURRENCY}),
    ValueKind.TEXT: frozenset({SemanticRole.RECIPIENT}),
})


@final
@dataclass(frozen=True, slots=True)
class ActionRegistry:
    actions: Mapping[str, ActionSpec]

    def get(self, action: str) -> "ActionSpec | None":
        return self.actions.get(action)

    def status(self, action: str, param: str, check: CheckId) -> "CheckStatus | None":
        """None means ABSENT: the action, the param, or the check key is not written
        down. ABSENT is a BLOCK at runtime and a lint failure at load time."""
        spec = self.actions.get(action)
        if spec is None:
            return None
        pspec = spec.params.get(param)
        if pspec is None:
            return None
        requirement = pspec.checks.get(check)
        if requirement is None:
            return None
        return requirement.status


def lint_registry(
    registry: ActionRegistry,
    checkers: Mapping[CheckId, "Checker"],
) -> None:
    """🔴 LOAD TIME. Called from Gate.__post_init__, so there is no way to obtain a
    usable Gate without having passed this.

    Collects ALL violations, then raises a single RegistryLintError whose message
    lists every one, sorted, each naming (action, param, check). Rules:

      L1 status is REQUIRED and check_id not in checkers
         -> "references a checker with no implementation"          [test f]
      L2 for every action and every declared param: set(param.checks) != set(CheckId)
         -> "check key ABSENT" (deny-by-default coverage over the closed enum)
      L3 param.required_role is SemanticRole.UNDETERMINED
      L4 param.required_role not in COMPATIBLE_ROLE_KINDS[param.value_kind]
      L5 action key != ActionSpec.name; param key != ParamSpec.name;
         empty action name after strip; action with zero params
      L6 status in {NOT_REQUIRED, NOT_IMPLEMENTED} and rationale.strip() == ""

    Post: returns None, or raises. Never returns a "mostly fine" result object.
    NOT_IMPLEMENTED is NOT a lint violation -- it is a legal, loud state whose
    consequence is a runtime BLOCK for irreversible actions (test e).
    """
    violations: list[str] = []

    for action_key in sorted(registry.actions):
        spec = registry.actions[action_key]

        if action_key != spec.name:                                                # L5
            violations.append(
                f"action key {action_key!r} does not match ActionSpec.name {spec.name!r}"
            )
        if not spec.name.strip():                                                   # L5
            violations.append(f"action {action_key!r}: action name is empty after strip")
        if not spec.params:                                                         # L5
            violations.append(f"action {action_key!r}: has zero params")

        for param_key in sorted(spec.params):
            pspec = spec.params[param_key]

            if param_key != pspec.name:                                            # L5
                violations.append(
                    f"action {action_key!r} param key {param_key!r} does not match "
                    f"ParamSpec.name {pspec.name!r}"
                )

            if pspec.required_role is SemanticRole.UNDETERMINED:                    # L3
                violations.append(
                    f"action {action_key!r} param {param_key!r}: "
                    "required_role is UNDETERMINED"
                )
            if pspec.required_role not in COMPATIBLE_ROLE_KINDS[pspec.value_kind]:  # L4
                violations.append(
                    f"action {action_key!r} param {param_key!r}: required_role "
                    f"{pspec.required_role.value!r} is not compatible with value_kind "
                    f"{pspec.value_kind.value!r}"
                )

            declared_checks = set(pspec.checks)
            missing_checks = sorted(set(CheckId) - declared_checks, key=lambda c: c.name)
            for check_id in missing_checks:                                         # L2
                violations.append(
                    f"action {action_key!r} param {param_key!r} check {check_id.value!r}: "
                    "check key ABSENT"
                )

            for check_id in sorted(pspec.checks, key=lambda c: c.name):
                requirement = pspec.checks[check_id]

                if requirement.status is CheckStatus.REQUIRED and check_id not in checkers:  # L1
                    violations.append(
                        f"action {action_key!r} param {param_key!r} check {check_id.value!r}: "
                        "references a checker with no implementation"
                    )

                if (
                    requirement.status in (CheckStatus.NOT_REQUIRED, CheckStatus.NOT_IMPLEMENTED)
                    and requirement.rationale.strip() == ""
                ):                                                                  # L6
                    violations.append(
                        f"action {action_key!r} param {param_key!r} check {check_id.value!r}: "
                        "rationale is empty"
                    )

    if violations:
        raise RegistryLintError("\n".join(sorted(violations)))


def lint_deployment(
    registry: ActionRegistry,
    checkers: Mapping[CheckId, "Checker"],
) -> None:
    """The stricter 'refuse to start' profile (ARCHITECTURE section 5). Runs
    lint_registry first, then raises DeploymentLintError if any IRREVERSIBLE action
    carries any CheckRequirement whose status is NOT_IMPLEMENTED.

    Not called by Gate.__post_init__: a Gate that blocks loudly is a valid object.
    An entrypoint that wants 'every irreversible action is fully checked or we do
    not boot' calls this explicitly.
    """
    lint_registry(registry, checkers)

    violations: list[str] = []
    for action_key in sorted(registry.actions):
        spec = registry.actions[action_key]
        if spec.reversibility is not Reversibility.IRREVERSIBLE:
            continue
        for param_key in sorted(spec.params):
            pspec = spec.params[param_key]
            for check_id in sorted(pspec.checks, key=lambda c: c.name):
                requirement = pspec.checks[check_id]
                if requirement.status is CheckStatus.NOT_IMPLEMENTED:
                    violations.append(
                        f"action {action_key!r} param {param_key!r} check {check_id.value!r}: "
                        "NOT_IMPLEMENTED on an irreversible action"
                    )

    if violations:
        raise DeploymentLintError("\n".join(sorted(violations)))
