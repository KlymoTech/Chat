output "test_signer_role_arn" {
  description = "Independent test attestation signing service's assumed role."
  value = aws_iam_role.test_signer.arn
}

output "release_signer_role_arn" {
  description = "Independent release-manifest signing service's assumed role."
  value = aws_iam_role.release_signer.arn
}

output "signers_are_distinct" {
  description = "Security invariant: independent parent roles and distinct keys."
  value = local.inputs_are_isolated
}
