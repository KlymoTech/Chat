# Additive reference only. Requires independently provisioned agent roles,
# two private signing secrets and TWO separate KMS keys before plan/apply.
module "protected_signers" {
  source = "../../modules/protected_qualification_signers"

  name_prefix = var.name_prefix
  environment = var.environment
  aws_account_id = var.aws_account_id
  aws_region = var.aws_region
  publisher_agent_role_arn = var.publisher_agent_role_arn
  test_signer_agent_role_arn = var.test_signer_agent_role_arn
  release_signer_agent_role_arn = var.release_signer_agent_role_arn
  signer_permissions_boundary_arn = var.signer_permissions_boundary_arn
  test_signing_secret_arn = var.test_signing_secret_arn
  release_signing_secret_arn = var.release_signing_secret_arn
  test_signing_kms_key_arn = var.test_signing_kms_key_arn
  release_signing_kms_key_arn = var.release_signing_kms_key_arn
}

output "test_signer_role_arn" {
  value = module.protected_signers.test_signer_role_arn
}
output "release_signer_role_arn" {
  value = module.protected_signers.release_signer_role_arn
}
