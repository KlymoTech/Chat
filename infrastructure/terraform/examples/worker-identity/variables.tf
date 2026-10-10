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

variable "ecr_repository_arn" {
  type = string
}

variable "log_group_arn" {
  type = string
}

variable "bootstrap_secret_arns" {
  type    = set(string)
  default = []
}

variable "bootstrap_kms_key_arns" {
  type    = set(string)
  default = []
}

variable "permissions_boundary_arn" {
  type    = string
  default = null
}
