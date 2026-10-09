variable "name_prefix" {
  description = "IAM-safe, unique prefix for the two distinct qualification signers."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,20}$", var.name_prefix))
    error_message = "name_prefix must begin with a letter and use 3-21 lowercase DNS-safe characters."
  }
}

variable "environment" {
  description = "Isolated qualification environment, not an authorization to deploy."
  type        = string

  validation {
    condition     = contains(["test", "qualification", "staging", "production"], var.environment)
    error_message = "Invalid controlled environment."
  }
}

variable "aws_account_id" {
  description = "Pinned AWS account ID; verified against the actual provider identity."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be 12 digits."
  }
}

variable "aws_region" {
  description = "Pinned AWS region for existing signing secrets and KMS keys."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "Invalid AWS region."
  }
}

variable "publisher_agent_role_arn" {
  description = "Existing reviewed Jenkins evidence publisher agent; MUST NOT assume signer roles."
  type        = string
}

variable "test_signer_agent_role_arn" {
  description = "Existing independent test-runner attestation signing agent IAM role."
  type        = string
}

variable "release_signer_agent_role_arn" {
  description = "Existing independent release-authority signing agent IAM role."
  type        = string
}

variable "signer_permissions_boundary_arn" {
  description = "Mandatory independently governed signer-specific IAM permissions boundary."
  type        = string
}

variable "test_signing_secret_arn" {
  description = "Exact existing Secrets Manager ARN holding test attestation Ed25519 signer material; no secret values in Terraform."
  type        = string
}

variable "release_signing_secret_arn" {
  description = "Exact existing Secrets Manager ARN holding release Ed25519 signer material; no secret values in Terraform."
  type        = string
}

variable "test_signing_kms_key_arn" {
  description = "Exact existing KMS key ARN encrypting only the test signing secret."
  type        = string
}

variable "release_signing_kms_key_arn" {
  description = "Exact existing KMS key ARN encrypting only the release signing secret."
  type        = string
}

variable "tags" {
  description = "Additional organization-approved tags; required tags override these."
  type        = map(string)
  default     = {}
}
