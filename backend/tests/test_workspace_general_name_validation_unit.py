"""Whitespace-safe Workspace name normalization regressions."""
from __future__ import annotations

import pytest

from northstar_api.modules.workspace.services.general_settings import normalize_workspace_name


@pytest.mark.parametrize("invalid", ["  ", "\t\n ", " a ", "\u2003x\u2003"])
def test_blank_and_single_character_names_are_rejected_after_trimming(invalid: str) -> None:
    with pytest.raises(ValueError, match="at least two visible characters"):
        normalize_workspace_name(invalid)


def test_valid_name_is_trimmed_without_changing_internal_spaces() -> None:
    assert normalize_workspace_name("  Student  Support  ") == "Student  Support"
    assert normalize_workspace_name("Valid") == "Valid"


def test_optional_patch_name_remains_optional() -> None:
    assert normalize_workspace_name(None) is None
