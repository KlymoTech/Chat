# Offline Terraform signer isolation checks. Mock IAM JSON data sources only.
# These are architecture tests, NOT proof that signer private keys or IAM trust
# are securely deployed in AWS.
mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012" }
}

override_data {
  target = data.aws_region.current
  values = { name = "us-east-1" }
}

override_data {
  target = data.aws_iam_policy_document.test_signer_trust
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"AWS\":\"arn:aws:iam::123456789012:role/reviewed-test-agent\"}}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.release_signer_trust
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"AWS\":\"arn:aws:iam::123456789012:role/reviewed-release-agent\"}}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.test_signing_secret
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar-test-AbCdEf\"}]}"
  }
}

override_data {
  target = data.aws_iam_policy_document.release_signing_secret
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar-release-AbCdEf\"}]}"
  }
}

variables {
  name_prefix                     = "northstarqa"
  environment                     = "qualification"
  aws_account_id                  = "123456789012"
  aws_region                      = "us-east-1"
  publisher_agent_role_arn        = "arn:aws:iam::123456789012:role/reviewed-publisher-agent"
  test_signer_agent_role_arn      = "arn:aws:iam::123456789012:role/reviewed-test-agent"
  release_signer_agent_role_arn   = "arn:aws:iam::123456789012:role/reviewed-release-agent"
  signer_permissions_boundary_arn = "arn:aws:iam::123456789012:policy/reviewed-signer-boundary"
  test_signing_secret_arn         = "arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar-test-AbCdEf"
  release_signing_secret_arn      = "arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar-release-AbCdEf"
  test_signing_kms_key_arn        = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
  release_signing_kms_key_arn     = "arn:aws:kms:us-east-1:123456789012:key/22222222-2222-2222-2222-222222222222"
}

run "separate_signer_roles_and_boundaries" {
  command = plan
  assert {
    condition     = aws_iam_role.test_signer.name != aws_iam_role.release_signer.name
    error_message = "Test and release signing roles must be separate."
  }
  assert {
    condition     = aws_iam_role.test_signer.permissions_boundary == var.signer_permissions_boundary_arn
    error_message = "Test signing role must be subject to an external permissions boundary."
  }
  assert {
    condition     = aws_iam_role.release_signer.permissions_boundary == var.signer_permissions_boundary_arn
    error_message = "Release signing role must be subject to an external permissions boundary."
  }
  assert {
    condition     = aws_iam_role.test_signer.max_session_duration == 3600
    error_message = "Test signer session must be short-lived."
  }
  assert {
    condition     = aws_iam_role.release_signer.max_session_duration == 3600
    error_message = "Release signer session must be short-lived."
  }
  assert {
    condition     = output.signers_are_distinct
    error_message = "Signer identities and signing secrets must remain distinct."
  }
}

run "deny_reusing_publisher_as_test_signer" {
  command = plan
  variables {
    test_signer_agent_role_arn = "arn:aws:iam::123456789012:role/reviewed-publisher-agent"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_reusing_test_agent_as_release_signer" {
  command = plan
  variables {
    release_signer_agent_role_arn = "arn:aws:iam::123456789012:role/reviewed-test-agent"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_same_signing_secret" {
  command = plan
  variables {
    release_signing_secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:northstar-test-AbCdEf"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_same_kms_key" {
  command = plan
  variables {
    release_signing_kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_wrong_account" {
  command = plan
  variables {
    aws_account_id = "999999999999"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_wrong_region" {
  command = plan
  variables {
    aws_region = "us-west-2"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_wrong_signer_secret_account" {
  command = plan
  variables {
    test_signing_secret_arn = "arn:aws:secretsmanager:us-east-1:999999999999:secret:northstar-test-AbCdEf"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_wrong_signer_kms_region" {
  command = plan
  variables {
    release_signing_kms_key_arn = "arn:aws:kms:us-west-2:123456789012:key/22222222-2222-2222-2222-222222222222"
  }
  expect_failures = [aws_iam_role.test_signer, aws_iam_role.release_signer]
}

run "deny_wildcard_agent_arn" {
  command = plan
  variables {
    release_signer_agent_role_arn = "arn:aws:iam::123456789012:role/*"
  }
  expect_failures = [var.release_signer_agent_role_arn]
}
