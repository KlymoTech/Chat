variable "name_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "trusted_jenkins_agent_role_arn" {
  description = "Existing protected Jenkins agent role; no new signer principal is created here."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Existing separately governed IAM permissions boundary."
  type        = string
}

variable "retention_days" {
  type    = number
  default = 90
}
