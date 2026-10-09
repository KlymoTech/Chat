"""Jenkins preflight is isolated and never authorizes production changes."""
from pathlib import Path

JENKINSFILE = Path(__file__).resolve().parents[2] / "Jenkinsfile"


def test_qualification_pipeline_is_explicit_branch_fenced():
    source = JENKINSFILE.read_text(encoding="utf-8")
    assert "feature/northstar-adaptive-architecture-20261008" in source
    assert "error('Qualification preflight is restricted" in source
    assert "uv sync --all-groups --locked" in source
    assert "test_platform_notification_qualification_governance.py" in source
    assert "test_platform_aws_jenkins_evidence_publisher.py" in source
    assert "test_platform_aws_jenkins_attestation_publisher.py" in source
    assert "test_platform_aws_protected_qualification_signer.py" in source
    assert "test_platform_jenkins_test_provenance.py" in source


def test_preflight_has_no_credential_material_or_deploy_calls():
    source = JENKINSFILE.read_text(encoding="utf-8")
    for banned in (
        "withCredentials(", "kubectl apply", "terraform apply",
        "aws secretsmanager", "signing_key=", "activate_notification_route(",
        "change_qualification_status(", "ingest_notification_qualification(",
    ):
        assert banned not in source
