# ============================================================================
# gate/__init__.py
# ============================================================================
"""gate: a pure-logic permission boundary that mints an Execute capability
only when every argument of a proposed action is grounded in a witness set
derived from the word-level transcript alone. Anything it cannot decide is a
BLOCK, never a pass.

This module deliberately does not re-export any package symbols. TS-36 and
TS-41 scan import graphs and call sites directly against the submodules
(`gate.transcript`, `gate.normalize`, `gate.decision`, ...); a re-export here
would give every symbol a second, untracked import path into the same name,
which is exactly the kind of ambient surface those structural tests exist to
rule out.
"""
