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

variable "publisher_agent_role_arn" {
  type = string
}

variable "test_signer_agent_role_arn" {
  type = string
}

variable "release_signer_agent_role_arn" {
  type = string
}

variable "signer_permissions_boundary_arn" {
  type = string
}

variable "test_signing_secret_arn" {
  type = string
}

variable "release_signing_secret_arn" {
  type = string
}

variable "test_signing_kms_key_arn" {
  type = string
}

variable "release_signing_kms_key_arn" {
  type = string
}
