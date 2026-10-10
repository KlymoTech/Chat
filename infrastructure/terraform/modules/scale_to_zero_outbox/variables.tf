variable "name_prefix" {
  type        = string
  description = "Short DNS-safe name prefix for the outbox resources."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase DNS-safe characters."
  }
}

variable "environment" {
  type        = string
  description = "Isolated environment name."
  validation {
    condition     = contains(["development", "qualification", "staging", "production"], var.environment)
    error_message = "environment must be development, qualification, staging or production."
  }
}

variable "aws_account_id" {
  type        = string
  description = "Approved target AWS account ID."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be exactly 12 digits."
  }
}

variable "aws_region" {
  type        = string
  description = "Approved target AWS region."
  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid AWS region identifier."
  }
}

variable "relay_lambda_arn" {
  type        = string
  description = "Already-approved Lambda function ARN for the bounded outbox relay."
}

variable "recovery_lambda_arn" {
  type        = string
  description = "Already-approved Lambda function ARN for the gated recovery handler."
}

variable "sns_kms_key_arn" {
  type        = string
  description = "Approved regional KMS key ARN used for SNS FIFO encryption."
}

variable "relay_timeout_seconds" {
  type        = number
  description = "Configured relay Lambda timeout; queue visibility is at least six times this value."
  default     = 60
  validation {
    condition     = var.relay_timeout_seconds >= 1 && var.relay_timeout_seconds <= 900 && floor(var.relay_timeout_seconds) == var.relay_timeout_seconds
    error_message = "relay_timeout_seconds must be a whole number from 1 to 900."
  }
}

variable "tags" {
  type    = map(string)
  default = {}
}
