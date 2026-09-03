# ============================================================================
# gate/errors.py
# ============================================================================
"""Exception hierarchy for the gate package.

Every error this package raises derives from GateError, so a caller can
catch the whole family with one except clause while still being able to
discriminate on the specific failure mode by catching a narrower subclass.
"""


class GateError(Exception):
    """Base for every error this package raises."""


class TranscriptFormatError(GateError):
    """Input word/transcript did not match the documented shape."""


class PolicyError(GateError):
    """A policy value handed to Gate() is not usable, or a Verdict invariant broke."""


class RegistryLintError(GateError):
    """Load-time registry lint failed. Raised from Gate.__post_init__."""


class DeploymentLintError(RegistryLintError):
    """Stricter deployment profile failed (see lint_deployment)."""


class CapabilityForgeryError(GateError):
    """An ExecuteCapability was constructed, copied, pickled or subclassed
    outside the single minting site."""
