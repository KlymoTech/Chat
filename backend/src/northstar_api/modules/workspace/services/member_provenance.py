"""Conservative invitation provenance for a current Workspace membership.

No membership -> invitation foreign key exists in the legacy schema. The accepted
invitation therefore cannot prove provenance after a removal and re-add. Treat
widely separated timestamps as unknown instead of attributing an old inviter.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

# Account creation can precede the membership database default timestamp by a
# short period. This window is a conservative compatibility bound, not proof.
_MAX_ACCEPT_JOIN_SKEW = timedelta(minutes=2)


def current_membership_inviter(
    *, joined_at: datetime, accepted_at: datetime | None, inviter_id: UUID | None,
) -> UUID | None:
    """Return a possible inviter only when acceptance coincides with joining.

    Never infer an inviter from a revoked, declined or old accepted invitation.
    Callers must prefilter to a same-tenant, same-workspace accepted invitation.
    """
    if accepted_at is None or inviter_id is None:
        return None
    joined = joined_at if joined_at.tzinfo else joined_at.replace(tzinfo=UTC)
    accepted = accepted_at if accepted_at.tzinfo else accepted_at.replace(tzinfo=UTC)
    return inviter_id if abs(joined - accepted) <= _MAX_ACCEPT_JOIN_SKEW else None
