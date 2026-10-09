# Isolated, non-deploying AWS foundation for immutable Jenkins qualification evidence.
# Protected Jenkins runners and independent signing services are NOT created here.
locals {
  partition = startswith(var.aws_region, "us-gov-") ? "aws-us-gov" : "aws"
  bucket_name = "${var.name_prefix}-qual-evidence-${var.aws_account_id}-${var.aws_region}"
  tags = merge(var.tags, {
    Component   = "northstar-jenkins-qualification-evidence"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

data "aws_iam_policy_document" "kms_account_admin" {
  statement {
    sid       = "AllowAccountKeyAdministration"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${var.aws_account_id}:root"]
    }
  }
}

resource "aws_kms_key" "evidence" {
  description             = "Northstar retained Jenkins qualification evidence in ${var.environment}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms_account_admin.json
  tags                    = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket" "evidence" {
  bucket              = local.bucket_name
  object_lock_enabled = true
  force_destroy       = false
  tags                = local.tags

  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        startswith(var.trusted_jenkins_agent_role_arn, "arn:${local.partition}:iam::${var.aws_account_id}:role/") &&
        startswith(var.permissions_boundary_arn, "arn:${local.partition}:iam::${var.aws_account_id}:policy/")
      )
      error_message = "Trusted Jenkins role and boundary must be exact role/policy ARNs in the approved account and AWS partition."
    }
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.evidence]
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence.arn
    }
    # Keep the encryption context object-scoped for IAM kms:ViaService rules.
    bucket_key_enabled = false
  }
}

# Every operation uses explicit encryption and an If-None-Match wildcard.
# These denies also apply if some other account principal acquires S3 access.
data "aws_iam_policy_document" "bucket_guards" {
  statement {
    sid       = "DenyNonTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyObjectDeletion"
    effect    = "Deny"
    actions   = ["s3:DeleteObject", "s3:DeleteObjectVersion", "s3:BypassGovernanceRetention"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }

  statement {
    sid       = "DenyMissingWritePrecondition"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Null"
      variable = "s3:if-none-match"
      values   = ["true"]
    }
  }

  statement {
    sid       = "DenyNonExclusiveWrite"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:if-none-match"
      values   = ["*"]
    }
  }

  statement {
    sid       = "DenyUnencryptedPut"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "DenyWrongKmsKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [aws_kms_key.evidence.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.bucket_guards.json

  depends_on = [aws_s3_bucket_public_access_block.evidence]
}

# Trust one reviewed agent IAM role, not the Jenkins hostname, its UI,
# GitHub Actions, a broad AWS account, or arbitrary self-declared role names.
data "aws_iam_policy_document" "publisher_trust" {
  statement {
    sid     = "OnlyProtectedJenkinsRoleAndNamedSessions"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [var.trusted_jenkins_agent_role_arn]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [var.trusted_jenkins_agent_role_arn]
    }

    condition {
      test     = "StringLike"
      variable = "sts:RoleSessionName"
      values   = ["northstar-evidence-jenkins-*"]
    }
  }
}

resource "aws_iam_role" "publisher" {
  name                 = "${var.name_prefix}-qualification-evidence-publisher"
  assume_role_policy   = data.aws_iam_policy_document.publisher_trust.json
  permissions_boundary = var.permissions_boundary_arn
  max_session_duration = 3600
  tags                 = local.tags
}

data "aws_iam_policy_document" "publisher" {
  statement {
    sid       = "WriteAndReadBackExactEvidenceVersions"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.evidence.arn}/evidence/*"]
  }

  statement {
    sid       = "EncryptAndDecryptOnlyThroughS3ForEvidence"
    effect    = "Allow"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt", "kms:DescribeKey"]
    resources = [aws_kms_key.evidence.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["${aws_s3_bucket.evidence.arn}/evidence/*"]
    }
  }
}

resource "aws_iam_role_policy" "publisher" {
  name   = "${var.name_prefix}-qualification-evidence-only"
  role   = aws_iam_role.publisher.id
  policy = data.aws_iam_policy_document.publisher.json
}
