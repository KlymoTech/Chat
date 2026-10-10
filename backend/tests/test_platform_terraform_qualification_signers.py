"""Static audit of authored signer IAM policy; mocks alone cannot prove it."""
import re
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "infrastructure/terraform/modules/protected_qualification_signers"
)


def _read(name: str) -> str:
    source = (ROOT / name).read_text(encoding="utf-8")
    # Terraform fmt right-aligns equals within neighboring assignment groups.
    # Normalize spacing for text assertions without weakening policy checks.
    return re.sub(r"(?<=\w)[ \t]+=[ \t]+", " = ", source)


def _block(source: str, marker: str) -> str:
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for idx in range(opening, len(source)):
        if source[idx] == "{":
            depth += 1
        elif source[idx] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : idx + 1]
    raise AssertionError(f"unterminated Terraform block: {marker}")


def test_distinct_signers_have_independent_trust_and_session_prefixes():
    source = _read("main.tf")
    attestation = _block(source, 'data "aws_iam_policy_document" "test_signer_trust"')
    release = _block(source, 'data "aws_iam_policy_document" "release_signer_trust"')
    assert "identifiers = [var.test_signer_agent_role_arn]" in attestation
    assert "identifiers = [var.release_signer_agent_role_arn]" in release
    assert 'variable = "aws:PrincipalArn"' in attestation
    assert 'variable = "aws:PrincipalArn"' in release
    assert 'values = ["northstar-test-jenkins-*"]' in attestation
    assert 'values = ["northstar-release-jenkins-*"]' in release
    assert "var.publisher_agent_role_arn" not in attestation + release
    assert "local.inputs_are_isolated" in source


def test_signer_roles_have_mandatory_external_boundary_and_short_lived_sessions():
    source = _read("main.tf")
    for signer in ("test_signer", "release_signer"):
        block = _block(source, f'resource "aws_iam_role" "{signer}"')
        assert "permissions_boundary = var.signer_permissions_boundary_arn" in block
        assert "max_session_duration = 3600" in block
        assert "condition = local.inputs_are_isolated" in block
        assert "assume_role_policy = data.aws_iam_policy_document." in block


def test_secret_and_kms_permissions_are_exact_and_mutually_disjoint():
    source = _read("main.tf")
    expected = {
        "test_signing_secret": (
            "var.test_signing_secret_arn", "var.test_signing_kms_key_arn"
        ),
        "release_signing_secret": (
            "var.release_signing_secret_arn", "var.release_signing_kms_key_arn"
        ),
    }
    for label, (secret, kms) in expected.items():
        policy = _block(source, f'data "aws_iam_policy_document" "{label}"')
        assert 'actions = ["secretsmanager:GetSecretValue"]' in policy
        assert f"resources = [{secret}]" in policy
        assert 'actions = ["kms:Decrypt"]' in policy
        assert f"resources = [{kms}]" in policy
        assert 'variable = "kms:ViaService"' in policy
        assert 'variable = "kms:EncryptionContext:SecretARN"' in policy
        other = "release" if label.startswith("test") else "test"
        assert f"var.{other}_signing_secret_arn" not in policy
        assert f"var.{other}_signing_kms_key_arn" not in policy
        for forbidden in (
            "s3:PutObject", "s3:DeleteObject", "iam:PassRole",
            "kms:Sign", "kms:GenerateDataKey", "sts:AssumeRole",
            "ec2:", "ecs:", "eks:", "lambda:",
        ):
            assert forbidden not in policy


def test_input_invariants_reject_shared_identity_keys_and_wrong_account():
    source = _read("main.tf")
    values = [
        "data.aws_caller_identity.current.account_id == var.aws_account_id",
        "data.aws_region.current.name == var.aws_region",
        "var.publisher_agent_role_arn",
        "var.test_signer_agent_role_arn",
        "var.release_signer_agent_role_arn",
        "var.test_signing_secret_arn != var.release_signing_secret_arn",
        "var.test_signing_kms_key_arn != var.release_signing_kms_key_arn",
    ]
    assert all(item in source for item in values)
    assert "length(distinct([" in source
    variables = _read("variables.tf")
    for varname in (
        "publisher_agent_role_arn", "test_signer_agent_role_arn",
        "release_signer_agent_role_arn", "test_signing_secret_arn",
        "release_signing_secret_arn", "test_signing_kms_key_arn",
        "release_signing_kms_key_arn", "signer_permissions_boundary_arn",
    ):
        assert f'variable "{varname}"' in variables
    assert "^[a-z]" in variables


def test_no_signing_private_key_or_automatic_deployment_in_terraform():
    source = _read("main.tf")
    forbidden = [
        "aws_secretsmanager_secret_version",
        "aws_secretsmanager_secret",
        "aws_kms_key",
        "aws_iam_user",
        "aws_iam_access_key",
        "aws_iam_role_policy_attachment",
        "aws_ecs_service", "aws_eks_cluster", "aws_instance",
    ]
    assert all(value not in source for value in forbidden)
    policy = _read("main.tf")
    assert "aws_iam_role_policy" in policy


def test_signer_workflow_never_gets_aws_credentials_or_applies():
    source = (
        ROOT.parents[3] / ".github/workflows/northstar-terraform-qualification-signers.yml"
    ).read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in source
    assert "terraform -chdir=infrastructure/terraform/modules/protected_qualification_signers test" in source
    assert "terraform apply" not in source
    assert "terraform destroy" not in source
    assert "aws-actions/configure-aws-credentials" not in source
