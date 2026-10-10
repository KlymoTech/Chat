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

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = set(string)
}

variable "private_route_table_ids" {
  type = set(string)
}

variable "database_security_group_id" {
  type = string
}

variable "include_kms_endpoint" {
  type    = bool
  default = false
}
