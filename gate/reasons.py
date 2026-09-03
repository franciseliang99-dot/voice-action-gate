# ============================================================================
# gate/reasons.py            (leaf module: imports nothing from this package)
# ============================================================================
"""Closed vocabularies for gate outcomes and block reasons.

Leaf module: imports nothing from the rest of this package, so every other
module in gate/ can depend on it without risk of an import cycle.
"""

from enum import Enum


class Outcome(Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class BlockReason(Enum):
    """🔴 This vocabulary is BLOCK-only by construction. There is deliberately no
    member that means "reason to allow": a check can veto, never grant."""
    NO_FINAL_WORDS = "no_final_words"
    TRANSCRIPT_TOO_LONG = "transcript_too_long"
    TRANSCRIPT_PROVENANCE_UNKNOWN = "transcript_provenance_unknown"
    ACTION_NOT_REGISTERED = "action_not_registered"
    MISSING_ARGUMENT = "missing_argument"
    UNDECLARED_ARGUMENT = "undeclared_argument"
    ARGUMENT_UNDECODABLE = "argument_undecodable"
    NO_WITNESS = "no_witness"
    ROLE_MISMATCH = "role_mismatch"
    CONFIDENCE_BELOW_FLOOR = "confidence_below_floor"
    CHECK_NOT_IMPLEMENTED = "check_not_implemented"
    CHECK_ABSENT = "check_absent"
    CHECKER_MISSING = "checker_missing"
    CHECKER_RAISED = "checker_raised"
