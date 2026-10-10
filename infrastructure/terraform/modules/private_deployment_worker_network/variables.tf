variable "name_prefix" {
  description = "Unique, lower-case prefix for worker-only network resources."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,36}$", var.name_prefix))
    error_message = "name_prefix must start with a lowercase letter and contain 3-37 safe characters."
  }
}

variable "environment" {
  type        = string
  description = "Approved AWS environment."

  validation {
    condition     = contains(["development", "test", "staging", "production"], var.environment)
    error_message = "Unknown environment."
  }
}

variable "vpc_id" {
  description = "Existing approved, isolated worker VPC."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]{8}([0-9a-f]{9})?$", var.vpc_id))
    error_message = "Expected a valid VPC ID."
  }
}

variable "private_subnet_ids" {
  description = "Existing private subnets in at least two availability zones; route tables require independent review."
  type        = set(string)

  validation {
    condition = length(var.private_subnet_ids) >= 2 && alltrue([
      for id in var.private_subnet_ids : can(regex("^subnet-[0-9a-f]{8}([0-9a-f]{9})?$", id))
    ])
    error_message = "Supply at least two distinct subnet IDs."
  }
}

variable "private_route_table_ids" {
  description = "Existing private subnet route tables for the required S3 gateway endpoint."
  type        = set(string)

  validation {
    condition = length(var.private_route_table_ids) >= 2 && alltrue([
      for id in var.private_route_table_ids : can(regex("^rtb-[0-9a-f]{8}([0-9a-f]{9})?$", id))
    ])
    error_message = "Supply at least two private route table IDs."
  }
}

variable "database_security_group_id" {
  description = "Existing RDS security group; operator must separately allow inbound 5432 from the worker SG."
  type        = string

  validation {
    condition     = can(regex("^sg-[0-9a-f]{8}([0-9a-f]{9})?$", var.database_security_group_id))
    error_message = "Expected an existing database security group ID."
  }
}

variable "aws_region" {
  description = "Region of the approved VPC, subnets and private AWS endpoints."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "Expected an AWS region identifier."
  }
}

variable "include_kms_endpoint" {
  description = "Create a dedicated private KMS endpoint when required by the worker bootstrap design."
  type        = bool
  default     = false
}

variable "tags" {
  type        = map(string)
  description = "Additional resource tags. Environment and ownership tags cannot be overridden."
  default     = {}
}
