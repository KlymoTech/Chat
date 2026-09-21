"""Member invitation attribution must not reuse a previous membership's inviter."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from northstar_api.modules.workspace.services.member_provenance import current_membership_inviter


def test_current_accepted_invitation_can_identify_inviter() -> None:
    inviter = uuid4()
    accepted = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    assert current_membership_inviter(
        joined_at=accepted + timedelta(seconds=2), accepted_at=accepted, inviter_id=inviter,
    ) == inviter


def test_old_invitation_cannot_claim_newly_readded_membership() -> None:
    accepted = datetime(2026, 1, 1, tzinfo=UTC)
    assert current_membership_inviter(
        joined_at=accepted + timedelta(days=30), accepted_at=accepted, inviter_id=uuid4(),
    ) is None


def test_no_accepted_time_or_inviter_stays_unknown() -> None:
    joined = datetime.now(UTC)
    assert current_membership_inviter(joined_at=joined, accepted_at=None, inviter_id=uuid4()) is None
    assert current_membership_inviter(joined_at=joined, accepted_at=joined, inviter_id=None) is None


def test_naive_and_offset_aware_timestamps_normalize_to_utc() -> None:
    inviter = uuid4()
    accepted = datetime(2026, 9, 21, 12, 0)  # legacy UTC-naive DB timestamp
    joined = datetime(2026, 9, 21, 17, 30, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert current_membership_inviter(
        joined_at=joined, accepted_at=accepted, inviter_id=inviter,
    ) == inviter
