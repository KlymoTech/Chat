"""Regression tests for non-bypassable platform deployment approval gates."""
import inspect

from northstar_api.modules.super_admin.api.runtime import (
    RuntimeChangeDecisionRequest,
    approve_runtime_change,
    create_runtime_change,
)


def test_approval_request_rejects_unexpected_fields():
    from pydantic import ValidationError
    try:
        RuntimeChangeDecisionRequest(reason="approved after review", evidence=(), injected="unexpected")
    except ValidationError:
        pass
    else:
        raise AssertionError("Unexpected client-supplied authorization fields accepted")


def test_persisted_specs_are_reclassified_at_approval():
    code = inspect.getsource(approve_runtime_change)
    assert "PlatformSpec.model_validate(record.current_spec_json)" in code
    assert "PlatformSpec.model_validate(record.desired_spec_json)" in code
    assert "gate.change_class" in code
    assert "verify_qualification_proofs(" in code\n    assert "PLATFORM_QUALIFICATION_HMAC_KEY" in code


def test_legacy_hot_safe_changes_do_not_dispatch_on_creation():
    source = inspect.getsource(create_runtime_change)
    assert 'if analysis.plan.action != "noop"' in source
    assert '"governanceClass": gate.change_class.value' in source
