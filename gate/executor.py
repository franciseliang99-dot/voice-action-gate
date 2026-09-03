# ============================================================================
# gate/executor.py
# ============================================================================
"""The demo's irreversible action. Every entrypoint here requires an
ExecuteCapability minted by gate.decision.Gate.evaluate; there is no signature
by which an executor in this module can be reached without one."""

from collections.abc import Mapping, MutableMapping

from .decision import ExecuteCapability
from .errors import CapabilityForgeryError
from .normalize import ScalarValue


def require_capability(
    cap: ExecuteCapability, action: str
) -> Mapping[str, ScalarValue]:
    """Returns cap.arguments iff cap.action == action; raises CapabilityForgeryError
    otherwise. Executors MUST take their parameters from this return value and never
    from the proposal, or the capability degrades into a boolean that says 'something
    was approved' without saying what."""
    if cap.action != action:
        raise CapabilityForgeryError(
            f"capability was minted for action {cap.action!r}, cannot be used to "
            f"execute {action!r}"
        )
    return cap.arguments


def execute_transfer(
    cap: ExecuteCapability, ledger: MutableMapping[str, int]
) -> str:
    """The demo's irreversible action. Its only authority-bearing parameter is `cap`;
    there is no signature by which it can be called without one. Reads amount /
    currency / to from require_capability(cap, "transfer"). Returns a receipt id."""
    arguments = require_capability(cap, "transfer")
    amount = arguments["amount"]
    currency = arguments["currency"]
    to = arguments["to"]

    # Defense in depth, not a normal error path: reference_registry() declares
    # "amount" as ValueKind.NUMBER and "currency"/"to" as ValueKind.CURRENCY_CODE /
    # ValueKind.TEXT, and decode_argument always decodes NUMBER to int and the
    # other two kinds to str (never bool -- see decode_argument's
    # `type(raw) is bool` guard, checked first). A capability minted by
    # Gate.evaluate can never violate this; if one somehow does, the capability
    # did not come from the real minting path and this executor refuses to spend
    # it rather than guess.
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise CapabilityForgeryError(
            f"capability for 'transfer' carries a non-int 'amount' {amount!r}; "
            "this violates the decoding invariant Gate.evaluate guarantees"
        )
    if not isinstance(currency, str):
        raise CapabilityForgeryError(
            f"capability for 'transfer' carries a non-str 'currency' {currency!r}; "
            "this violates the decoding invariant Gate.evaluate guarantees"
        )
    if not isinstance(to, str):
        raise CapabilityForgeryError(
            f"capability for 'transfer' carries a non-str 'to' {to!r}; "
            "this violates the decoding invariant Gate.evaluate guarantees"
        )

    ledger[to] = ledger.get(to, 0) + amount
    receipt_id = f"receipt:transfer:{to}:{amount}:{currency}:{len(ledger)}"
    return receipt_id
