# ============================================================================
# gate/proposal.py           (leaf; nothing in the witness pipeline may import it)
# ============================================================================
"""The model-authored proposal shape. Deliberately isolated: witness.py,
roles.py and normalize.py must never import this module (D1, TS-36)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import final

from .errors import TranscriptFormatError


@final
@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    arguments: Mapping[str, object]


def parse_proposal(raw: Mapping[str, object]) -> Proposal:
    """Raises TranscriptFormatError if `action` is missing/not str/empty after strip,
    or `arguments` is missing/not a Mapping, or any argument key is not a str."""
    if "action" not in raw:
        raise TranscriptFormatError("proposal is missing required key: action")
    action = raw["action"]
    if not isinstance(action, str):
        raise TranscriptFormatError(
            f"proposal.action must be str, got {type(action).__name__}"
        )
    if action.strip() == "":
        raise TranscriptFormatError("proposal.action must not be empty after strip")

    if "arguments" not in raw:
        raise TranscriptFormatError("proposal is missing required key: arguments")
    arguments = raw["arguments"]
    if not isinstance(arguments, Mapping):
        raise TranscriptFormatError(
            f"proposal.arguments must be a Mapping, got {type(arguments).__name__}"
        )
    for key in arguments:
        if not isinstance(key, str):
            raise TranscriptFormatError(
                f"proposal.arguments key must be str, got {type(key).__name__}"
            )

    return Proposal(action=action, arguments=arguments)
