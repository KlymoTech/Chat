# No AWS credentials required. Terraform mock_provider verifies the IAM
# module topology before an authorized infrastructure release.
mock_provider "aws" {}

variables {
  name_prefix        = "northstar-qa"
  environment        = "test"
  aws_account_id     = "123456789012"
  aws_region         = "us-east-1"
  ecr_repository_arn = "arn:aws:ecr:us-east-1:123456789012:repository/northstar"
  log_group_arn      = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/ecs/northstar-worker"
}

run "isolated_task_and_execution_identity" {
  command = plan

  assert {
    condition     = aws_iam_role.worker_task.name == "northstar-qa-worker-task"
    error_message = "The deployment worker task must receive a separate dedicated IAM role."
  }

  assert {
    condition     = aws_iam_role.worker_execution.name == "northstar-qa-worker-execution"
    error_message = "Bootstrap ECR/logging must use a separate ECS execution role."
  }

  assert {
    condition     = output.worker_has_cloud_mutation_permissions == false
    error_message = "The worker task must not gain AWS mutation authority."
  }
}
