"""Product-intelligence domain (Phase C).

Owns the entities the PO works with between cycles:

- ``Proposal`` — draft story or opportunity awaiting human triage.
- ``OKR`` — outcome framing for a project.
- ``Policy`` — hard product rules applied as a filter on generated stories.
- ``Signal`` — observed market / customer / competitor event with classification.
- ``InsightDigest`` — the weekly digest output.
"""

from theswarm.domain.product.value_objects import (
    InsightKind,
    PolicyDecision,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)
from theswarm.domain.product.entities import (
    InsightDigest,
    OKR,
    Policy,
    Proposal,
    Signal,
)

__all__ = [
    "InsightDigest",
    "InsightKind",
    "OKR",
    "Policy",
    "PolicyDecision",
    "Proposal",
    "ProposalStatus",
    "Signal",
    "SignalKind",
    "SignalSeverity",
]
