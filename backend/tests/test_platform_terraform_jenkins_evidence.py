"""Static, non-cloud contracts for the isolated Terraform evidence module.

Terraform mock_provider separately tests provider schema and module topology.
These tests inspect the authored IAM/bucket policy documents so mock data-source
fixtures cannot accidentally make a weaker production policy appear tested.
"""
from pathlib import Path

ROOT = (
    Path(__file__).resolve().parents[2]
    / "infrastructure/terraform/modules/jenkins_qualification_evidence"
)


def _text():
    return (ROOT / "main.tf").read_text(encoding="utf-8")


def _block(source: str, declaration: str) -> str:
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for pos in range(opening, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[opening : pos + 1]
    raise AssertionError(f"unterminated Terraform block {declaration}")


def test_bucket_is_locked_versioned_private_and_undeletable_by_default():
    source = _text()
    bucket = _block(source, 'resource "aws_s3_bucket" "evidence"')
    assert "object_lock_enabled = true" in bucket
    assert "force_destroy       = false" in bucket
    assert "prevent_destroy = true" in bucket

    version = _block(source, 'resource "aws_s3_bucket_versioning" "evidence"')
    assert 'status = "Enabled"' in version

    lock = _block(source, 'resource "aws_s3_bucket_object_lock_configuration" "evidence"')
    assert 'mode = "COMPLIANCE"' in lock
    assert "days = var.retention_days" in lock

    public = _block(source, 'resource "aws_s3_bucket_public_access_block" "evidence"')
    assert "block_public_acls       = true" in public
    assert "block_public_policy     = true" in public
    assert "ignore_public_acls      = true" in public
    assert "restrict_public_buckets = true" in public


def test_only_correct_writer_gets_iam_trust_and_short_sessions():
    source = _text()
    trust = _block(source, 'data "aws_iam_policy_document" "publisher_trust"')
    assert "identifiers = [var.trusted_jenkins_agent_role_arn]" in trust
    assert 'variable = "aws:PrincipalArn"' in trust
    assert 'variable = "sts:RoleSessionName"' in trust
    assert 'values   = ["northstar-evidence-jenkins-*"]' in trust
    assert 'actions = ["sts:AssumeRole"]' in trust

    role = _block(source, 'resource "aws_iam_role" "publisher"')
    assert "permissions_boundary = var.permissions_boundary_arn" in role
    assert "max_session_duration = 3600" in role


def test_publisher_policy_is_exactly_s3_evidence_and_kms_via_s3():
    source = _text()
    policy = _block(source, 'data "aws_iam_policy_document" "publisher"')
    assert 'actions   = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObjectVersion"]' in policy
    assert '"${aws_s3_bucket.evidence.arn}/evidence/*"' in policy
    assert 'actions   = ["kms:GenerateDataKey", "kms:Decrypt"]' in policy
    assert 'variable = "kms:ViaService"' in policy
    assert 'variable = "kms:EncryptionContext:aws:s3:arn"' in policy
    for forbidden in ("iam:PassRole", "secretsmanager:GetSecretValue", "kms:ScheduleKeyDeletion",
                      "s3:DeleteObject", "ec2:", "eks:", "ecs:", "terraform apply"):
        assert forbidden not in policy


def test_bucket_policy_denies_unsafe_tls_deletion_nonexclusive_and_wrong_kms():
    guards = _block(_text(), 'data "aws_iam_policy_document" "bucket_guards"')
    for statement in (
        "DenyNonTLS", "DenyObjectDeletion",
        "DenyMissingWritePrecondition", "DenyNonExclusiveWrite",
        "DenyUnencryptedPut", "DenyWrongKmsKey",
        "DenyMissingObjectLockMode", "DenyNonComplianceObjectLockMode",
        "DenyShortObjectRetention",
    ):
        assert f'sid       = "{statement}"' in guards
    assert 'variable = "aws:SecureTransport"' in guards
    assert 'variable = "s3:if-none-match"' in guards
    assert 'variable = "s3:x-amz-server-side-encryption"' in guards
    assert 'variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"' in guards
    assert '"s3:DeleteObjectVersion"' in guards
    assert 'variable = "s3:object-lock-mode"' in guards
    assert 'variable = "s3:object-lock-remaining-retention-days"' in guards
    assert 'values   = [tostring(var.retention_days)]' in guards


def test_provider_account_and_region_must_match_explicit_configuration():
    bucket = _block(_text(), 'resource "aws_s3_bucket" "evidence"')
    assert "data.aws_caller_identity.current.account_id == var.aws_account_id" in bucket
    assert "data.aws_region.current.name == var.aws_region" in bucket
    assert "length(local.bucket_name) <= 63" in bucket
    assert 'var.permissions_boundary_arn, "arn:${local.partition}:iam::${var.aws_account_id}:policy/"' in bucket


def test_isolated_module_has_no_signature_or_workload_activation():
    main = _text()
    for forbidden in (
        "aws_secretsmanager_secret", "aws_eks_cluster", "aws_ecs_service",
        "aws_iam_access_key", "aws_instance", "aws_lambda_function",
        "aws_sqs_queue", "aws_iam_role_policy_attachment",
    ):
        assert forbidden not in main
    assert "aws_kms_key" in main
    assert "aws_s3_bucket" in main


def test_no_auto_apply_or_aws_secrets_in_offline_ci():
    workflow = (
        ROOT.parents[3] / ".github/workflows/northstar-terraform-qualification-evidence.yml"
    ).read_text(encoding="utf-8")
    assert "terraform -chdir=infrastructure/terraform/modules/jenkins_qualification_evidence test" in workflow
    assert "terraform apply" not in workflow
    assert "terraform destroy" not in workflow
    assert "aws-actions/configure-aws-credentials" not in workflow
    assert "permissions:\n  contents: read" in workflow
