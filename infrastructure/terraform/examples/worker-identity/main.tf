# Reference integration only. Do NOT terraform apply until the private
# VPC, secrets/bootstrap, worker image and change approval are qualified.
module "private_worker_identity" {
  source = "../../modules/private_deployment_worker_identity"

  name_prefix              = var.name_prefix
  environment              = var.environment
  aws_account_id           = var.aws_account_id
  aws_region               = var.aws_region
  ecr_repository_arn       = var.ecr_repository_arn
  log_group_arn            = var.log_group_arn
  bootstrap_secret_arns    = var.bootstrap_secret_arns
  bootstrap_kms_key_arns   = var.bootstrap_kms_key_arns
  permissions_boundary_arn = var.permissions_boundary_arn
}

output "worker_task_role_arn" {
  value = module.private_worker_identity.worker_task_role_arn
}

output "worker_execution_role_arn" {
  value = module.private_worker_identity.worker_execution_role_arn
}
