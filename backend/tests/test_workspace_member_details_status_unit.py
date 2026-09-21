"""Global account disablement must be visible without changing lifecycle semantics."""
from __future__ import annotations

import pytest

from northstar_api.modules.workspace.api.member_details import member_detail_status


@pytest.mark.parametrize(
    ("account_active", "suspended", "expected"),
    [
        (True, False, "active"),
        (True, True, "suspended"),
        (False, False, "disabled"),
        (False, True, "disabled"),
    ],
)
def test_member_detail_status_prioritizes_global_account_disablement(
    account_active: bool, suspended: bool, expected: str,
) -> None:
    assert member_detail_status(account_active=account_active, suspended=suspended) == expected
