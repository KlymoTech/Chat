variable "name_prefix" {
  description = "Short, globally unique, lowercase prefix for the evidence bucket and publisher IAM role."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase DNS-safe characters, starting with a letter."
  }
}

variable "environment" {
  description = "Isolated qualification environment. Production accounts require independent approval."
  type        = string

  validation {
    condition     = contains(["development", "qualification", "staging", "production"], var.environment)
    error_message = "environment must be development, qualification, staging or production."
  }
}

variable "aws_account_id" {
  description = "Approved AWS account ID for all credentials, S3 and KMS resources."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be exactly 12 digits."
  }
}

variable "aws_region" {
  description = "Pinned AWS region; caller provider must use this region."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a supported regional identifier."
  }
}

variable "trusted_jenkins_agent_role_arn" {
  description = "Exact reviewed Jenkins agent IAM role ARN that may assume the publishing role; never a wildcard principal."
  type        = string

  validation {
    condition     = can(regex("^arn:(aws|aws-us-gov):iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]+$", var.trusted_jenkins_agent_role_arn))
    error_message = "trusted_jenkins_agent_role_arn must be one exact IAM role ARN."
  }
}

variable "permissions_boundary_arn" {
  description = "Mandatory, independently governed permissions boundary for the publisher role."
  type        = string

  validation {
    condition     = can(regex("^arn:(aws|aws-us-gov):iam::[0-9]{12}:policy/[A-Za-z0-9+=,.@_/-]+$", var.permissions_boundary_arn))
    error_message = "permissions_boundary_arn must be one exact IAM policy ARN."
  }
}

variable "retention_days" {
  description = "Minimum S3 Object Lock COMPLIANCE default retention; cannot be shortened once objects are protected."
  type        = number
  default     = 90

  validation {
    condition     = var.retention_days >= 90 && var.retention_days <= 3650 && floor(var.retention_days) == var.retention_days
    error_message = "retention_days must be a whole number between 90 and 3650."
  }
}

variable "tags" {
  description = "Extra organization-approved resource tags; mandatory component and environment tags win."
  type        = map(string)
  default     = {}
}
