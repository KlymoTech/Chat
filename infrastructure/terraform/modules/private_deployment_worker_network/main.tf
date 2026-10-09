locals {
  # No NAT/public route is created by this module.
  endpoint_services = toset(concat(
    ["ecr.api", "ecr.dkr", "logs", "secretsmanager", "sts"],
    var.include_kms_endpoint ? ["kms"] : [],
  ))

  tags = merge(var.tags, {
    ManagedBy   = "terraform"
    Environment = var.environment
    Component   = "northstar-private-deployment-worker"
  })
}

data "aws_subnet" "private" {
  for_each = var.private_subnet_ids
  id       = each.value
}

data "aws_security_group" "database" {
  id = var.database_security_group_id
}

resource "aws_security_group" "worker" {
  name_prefix            = "${var.name_prefix}-worker-"
  description            = "Isolated Northstar worker: no inbound and explicitly controlled egress"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true

  # Empty managed inline rules revoke the AWS default allow-all egress.
  ingress = []
  egress  = []

  tags = merge(local.tags, { Name = "${var.name_prefix}-worker" })

  lifecycle {
    precondition {
      condition = alltrue([
        for subnet in data.aws_subnet.private :
        subnet.vpc_id == var.vpc_id && !subnet.map_public_ip_on_launch
      ])
      error_message = "Every worker subnet must be in the approved VPC with public IP autoassignment disabled."
    }

    precondition {
      condition = length(distinct([
        for subnet in data.aws_subnet.private : subnet.availability_zone
      ])) >= 2
      error_message = "Deploy worker tasks in private subnets across two or more AZs."
    }

    precondition {
      condition     = data.aws_security_group.database.vpc_id == var.vpc_id
      error_message = "RDS security group must be in the same approved VPC."
    }
  }
}

resource "aws_security_group" "endpoints" {
  name_prefix            = "${var.name_prefix}-endpoints-"
  description            = "Dedicated interface endpoints accessible only from Northstar worker"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  ingress                = []
  egress                 = []
  tags                   = merge(local.tags, { Name = "${var.name_prefix}-endpoints" })
}

resource "aws_vpc_security_group_ingress_rule" "endpoint_from_worker" {
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS only from dedicated deployment worker"
}

resource "aws_vpc_security_group_egress_rule" "worker_to_endpoints" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = aws_security_group.endpoints.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "HTTPS only to dedicated AWS service endpoints"
}

resource "aws_vpc_security_group_egress_rule" "worker_to_database" {
  security_group_id            = aws_security_group.worker.id
  referenced_security_group_id = var.database_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "PostgreSQL only to the approved RDS security group"
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.endpoint_services
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = sort(tolist(var.private_subnet_ids))
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = merge(local.tags, { Name = "${var.name_prefix}-${replace(each.value, ".", "-")}" })
}

resource "aws_vpc_endpoint" "s3_gateway" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = sort(tolist(var.private_route_table_ids))
  tags              = merge(local.tags, { Name = "${var.name_prefix}-s3-gateway" })
}

resource "aws_vpc_security_group_egress_rule" "worker_to_s3" {
  security_group_id = aws_security_group.worker.id
  prefix_list_id    = aws_vpc_endpoint.s3_gateway.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  description       = "S3 over gateway endpoint for ECR image layers"
}
