output "worker_security_group_id" {
  description = "Dedicated outbound-restricted ECS worker security group (no ingress)."
  value       = aws_security_group.worker.id
}

output "interface_endpoint_security_group_id" {
  description = "Dedicated SG permitting port 443 from the worker only."
  value       = aws_security_group.endpoints.id
}

output "interface_endpoint_ids" {
  description = "Provisioned interface endpoints in the worker VPC."
  value       = { for name, endpoint in aws_vpc_endpoint.interface : name => endpoint.id }
}

output "s3_gateway_endpoint_id" {
  description = "Required S3 gateway endpoint for ECR image-layer downloads."
  value       = aws_vpc_endpoint.s3_gateway.id
}

output "private_subnet_ids" {
  description = "Caller-provided private subnet IDs; must be used with assign_public_ip = false."
  value       = sort(tolist(var.private_subnet_ids))
}

output "public_worker_ingress_enabled" {
  value       = false
  description = "Contract: this module creates no inbound worker security-group rules."
}
