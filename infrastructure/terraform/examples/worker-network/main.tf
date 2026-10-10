# Reference integration, not an approved deployment.
# Existing VPC, approved private subnets and routes are intentionally inputs.
module "worker_network" {
  source = "../../modules/private_deployment_worker_network"

  name_prefix                = var.name_prefix
  environment                = var.environment
  aws_region                 = var.aws_region
  vpc_id                     = var.vpc_id
  private_subnet_ids         = var.private_subnet_ids
  private_route_table_ids    = var.private_route_table_ids
  database_security_group_id = var.database_security_group_id
  include_kms_endpoint       = var.include_kms_endpoint
}

output "worker_security_group_id" {
  value = module.worker_network.worker_security_group_id
}

output "worker_private_subnet_ids" {
  value = module.worker_network.private_subnet_ids
}
