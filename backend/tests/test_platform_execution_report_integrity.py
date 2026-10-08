"""Execution report idempotency includes all evidence and error metadata."""
from northstar_api.modules.platform_runtime.execution_report_integrity import execution_report_matches
from northstar_api.modules.platform_runtime.executor_contract import DeploymentExecutionReport


def report(*, health=None, error=None):
    return DeploymentExecutionReport(
        reportKey="pipeline-step-42",
        pipeline="qualification-aws",
        phase="verifying",
        sourceDigest="a" * 64,
        targetDigest="b" * 64,
        healthResult=health if health is not None else {"canary": "healthy"},
        error=error,
    )


def matching(value, **changes):
    fields = dict(
        stored_source_digest=value.source_digest,
        stored_target_digest=value.target_digest,
        stored_pipeline=value.pipeline,
        stored_phase=value.phase,
        stored_health=value.health_result,
        stored_error=value.error,
        incoming=value,
    )
    fields.update(changes)
    return execution_report_matches(**fields)


def test_exact_replayed_report_is_idempotent():
    assert matching(report())


def test_health_evidence_cannot_change_on_replay():
    original = report()
    assert not matching(original, stored_health={"canary": "unknown"})
    assert not matching(original, stored_health={})


def test_error_field_cannot_change_on_replay():
    original = report()
    assert not matching(original, stored_error="later failure")


def test_pipeline_phase_and_digest_cannot_change_on_replay():
    original = report()
    assert not matching(original, stored_pipeline="different")
    assert not matching(original, stored_phase="completed")
    assert not matching(original, stored_source_digest="c" * 64)
    assert not matching(original, stored_target_digest="d" * 64)
