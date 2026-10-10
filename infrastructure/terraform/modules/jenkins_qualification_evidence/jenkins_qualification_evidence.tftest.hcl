# Mocked topology checks run without AWS credentials or Terraform apply.
# Live S3 Object Lock, KMS and IAM integration tests remain mandatory.
mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_region.current
  values = {
    name = "us-east-1"
  }
}

# The mock provider does not execute IAM policy document generation.
# Use valid fixture JSON so role/policy schemas can be planned offline.
override_data {
  target = data.aws_iam_policy_document.kms_account_admin
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"kms:*\",\"Resource\":\"*\"}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.bucket_guards
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Deny\",\"Action\":\"s3:DeleteObject\",\"Resource\":\"*\"}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.publisher_trust
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"AWS\":\"arn:aws:iam::123456789012:role/reviewed-jenkins-agent\"}}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.publisher
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"s3:PutObject\",\"Resource\":\"*\"}]}"
  }
}

variables {
  name_prefix                    = "northstarqa"
  environment                    = "qualification"
  aws_account_id                 = "123456789012"
  aws_region                     = "us-east-1"
  trusted_jenkins_agent_role_arn = "arn:aws:iam::123456789012:role/reviewed-jenkins-agent"
  permissions_boundary_arn       = "arn:aws:iam::123456789012:policy/reviewed-boundary"
  retention_days                 = 90
}

run "locked_bucket_is_separate_from_signing_identity" {
  command = plan

  assert {
    condition     = aws_s3_bucket.evidence.object_lock_enabled == true
    error_message = "Evidence bucket must enable S3 Object Lock at creation time."
  }

  assert {
    condition     = aws_s3_bucket.evidence.force_destroy == false
    error_message = "Evidence bucket must never allow force_destroy."
  }

  assert {
    condition     = aws_s3_bucket_versioning.evidence.versioning_configuration[0].status == "Enabled"
    error_message = "Immutable evidence requires object versioning."
  }

  assert {
    condition     = aws_s3_bucket_object_lock_configuration.evidence.rule[0].default_retention[0].mode == "COMPLIANCE"
    error_message = "S3 must default to compliance, not governance, retention."
  }

  assert {
    condition     = aws_s3_bucket_object_lock_configuration.evidence.rule[0].default_retention[0].days >= 90
    error_message = "Evidence retention cannot be shorter than 90 days."
  }

  assert {
    condition     = aws_s3_bucket_public_access_block.evidence.block_public_policy == true
    error_message = "Evidence bucket must block public bucket policies."
  }

  assert {
    condition     = aws_s3_bucket_server_side_encryption_configuration.evidence.rule[0].apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms"
    error_message = "Evidence storage must default to customer-managed SSE-KMS."
  }

  assert {
    condition     = aws_iam_role.publisher.permissions_boundary == var.permissions_boundary_arn
    error_message = "Publisher role must carry the separate governance boundary."
  }

  assert {
    condition     = aws_iam_role.publisher.max_session_duration == 3600
    error_message = "Publisher cannot use long-lived assumed-role sessions."
  }
}

run "reject_wrong_target_account" {
  command = plan
  variables {
    aws_account_id = "999999999999"
  }
  expect_failures = [aws_s3_bucket.evidence]
}

run "reject_wrong_target_region" {
  command = plan
  variables {
    aws_region = "us-west-2"
  }
  expect_failures = [aws_s3_bucket.evidence]
}

run "reject_cross_account_trusted_jenkins_agent" {
  command = plan
  variables {
    trusted_jenkins_agent_role_arn = "arn:aws:iam::999999999999:role/reviewed-jenkins-agent"
  }
  expect_failures = [aws_s3_bucket.evidence]
}

run "reject_cross_account_permissions_boundary" {
  command = plan
  variables {
    permissions_boundary_arn = "arn:aws:iam::999999999999:policy/reviewed-boundary"
  }
  expect_failures = [aws_s3_bucket.evidence]
}

run "reject_short_retention" {
  command = plan
  variables {
    retention_days = 30
  }
  expect_failures = [var.retention_days]
}
