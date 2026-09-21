"""Owner resolution must not confuse the immutable creator with current ownership."""
from __future__ import annotations

from uuid import uuid4

from northstar_api.modules.workspace.services.ownership import select_owner_id


def test_creator_is_legacy_owner_only_if_still_an_active_administrator() -> None:
    creator, other = uuid4(), uuid4()
    assert select_owner_id(None, creator, (other, creator)) == creator
    assert select_owner_id(None, creator, (other,)) == other


def test_transferred_owner_takes_precedence_over_creator() -> None:
    creator, next_owner = uuid4(), uuid4()
    assert select_owner_id(str(next_owner), creator, (creator, next_owner)) == next_owner


def test_unknown_or_invalid_configured_owner_never_grants_access_to_nonadmin() -> None:
    creator, other = uuid4(), uuid4()
    assert select_owner_id(str(uuid4()), creator, (creator, other)) == creator
    assert select_owner_id("not-a-uuid", creator, (other,)) == other
    assert select_owner_id(None, creator, ()) is None


def test_no_creator_or_configured_owner_uses_first_eligible_administrator() -> None:
    first, second = uuid4(), uuid4()
    assert select_owner_id(None, None, (first, second)) == first
    assert select_owner_id(None, None, (second, first)) == second
