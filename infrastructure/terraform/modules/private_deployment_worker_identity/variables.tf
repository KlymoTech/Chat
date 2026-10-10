variable "name_prefix" {
  description = "DNS/IAM-safe prefix uniquely identifying the platform and AWS environment."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,45}$", var.name_prefix))
    error_message = "name_prefix must contain 3-46 lowercase letters, digits, or hyphens and begin with a letter."
  }
}

variable "environment" {
  description = "Isolated worker environment; deploy production in its separately governed AWS account."
  type        = string

  validation {
    condition     = contains(["development", "test", "staging", "production"], var.environment)
    error_message = "environment must be development, test, staging, or production."
  }
}

variable "aws_account_id" {
  description = "Expected account ID; account ID is never inferred from user-controlled request content."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must contain exactly 12 digits."
  }
}

variable "aws_region" {
  description = "The pre-approved AWS region containing the ECS tasks and required supporting resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be an AWS region identifier."
  }
}

variable "ecr_repository_arn" {
  description = "Existing private ECR repository ARN. Never use a wildcard repository grant."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:ecr:[a-z0-9-]+:[0-9]{12}:repository/[A-Za-z0-9_./-]+$", var.ecr_repository_arn))
    error_message = "ecr_repository_arn must identify one existing ECR repository."
  }
}

variable "log_group_arn" {
  description = "Existing, retention-governed CloudWatch log group ARN, without log-stream suffix."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:logs:[a-z0-9-]+:[0-9]{12}:log-group:[A-Za-z0-9_./#-]+$", var.log_group_arn))
    error_message = "log_group_arn must identify one existing CloudWatch log group."
  }
}

variable "bootstrap_secret_arns" {
  description = "Explicit ARNs for secrets the ECS agent may inject at task creation; worker task role itself has no Secrets Manager grant."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.bootstrap_secret_arns :
      can(regex("^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:[A-Za-z0-9/_+=.@-]+$", arn))
    ])
    error_message = "Every bootstrap_secret_arns entry must be an exact Secrets Manager secret ARN."
  }
}

variable "bootstrap_kms_key_arns" {
  description = "Optional exact customer-managed KMS keys used by bootstrap secrets; decryption is restricted to Secrets Manager."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.bootstrap_kms_key_arns :
      can(regex("^arn:aws[a-z-]*:kms:[a-z0-9-]+:[0-9]{12}:key/[0-9a-fA-F-]{36}$", arn))
    ])
    error_message = "Every bootstrap_kms_key_arns entry must be an exact customer-managed KMS key ARN."
  }
}

variable "permissions_boundary_arn" {
  description = "Optional organizational IAM permissions boundary ARN for both roles."
  type        = string
  default     = null
}

variable "tags" {
  description = "Mandatory environment tags are merged over any caller-supplied values."
  type        = map(string)
  default     = {}
}
