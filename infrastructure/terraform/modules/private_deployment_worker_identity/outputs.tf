output "worker_task_role_arn" {
  description = "Zero-grant task role for the private worker application (not a deployment executor)."
  value       = aws_iam_role.worker_task.arn
}

output "worker_execution_role_arn" {
  description = "Narrowly scoped ECR/logging/optional secret-bootstrap role for the ECS agent."
  value       = aws_iam_role.worker_execution.arn
}

output "worker_has_cloud_mutation_permissions" {
  description = "Contract flag: this module deliberately creates no AWS mutation authority for the worker."
  value       = false
}
