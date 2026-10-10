# Example wiring only. NEVER apply without isolated account and change approval.
# This module does not provision Jenkins controllers, agents or private signers.
module "qualification_evidence" {
  source = "../../modules/jenkins_qualification_evidence"

  name_prefix                    = var.name_prefix
  environment                    = var.environment
  aws_account_id                 = var.aws_account_id
  aws_region                     = var.aws_region
  trusted_jenkins_agent_role_arn = var.trusted_jenkins_agent_role_arn
  permissions_boundary_arn       = var.permissions_boundary_arn
  retention_days                 = var.retention_days
}

output "evidence_bucket_name" {
  value = module.qualification_evidence.evidence_bucket_name
}

output "evidence_kms_key_arn" {
  value = module.qualification_evidence.evidence_kms_key_arn
}

output "publisher_role_arn" {
  value = module.qualification_evidence.publisher_role_arn
}
