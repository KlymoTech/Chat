mock_provider "aws" {}

override_data {
  target = data.aws_subnet.private["subnet-00000001"]
  values = {
    vpc_id                  = "vpc-00000001"
    availability_zone       = "us-east-1a"
    map_public_ip_on_launch = false
  }
}

override_data {
  target = data.aws_subnet.private["subnet-00000002"]
  values = {
    vpc_id                  = "vpc-00000001"
    availability_zone       = "us-east-1b"
    map_public_ip_on_launch = false
  }
}

override_data {
  target = data.aws_security_group.database
  values = {
    vpc_id = "vpc-00000001"
  }
}

override_resource {
  target = aws_vpc_endpoint.s3_gateway
  values = {
    prefix_list_id = "pl-00000001"
  }
}

variables {
  name_prefix                = "northstar-qa"
  environment                = "test"
  vpc_id                     = "vpc-00000001"
  private_subnet_ids         = ["subnet-00000001", "subnet-00000002"]
  private_route_table_ids    = ["rtb-00000001", "rtb-00000002"]
  database_security_group_id = "sg-00000001"
  aws_region                 = "us-east-1"
}

run "private_network_has_no_public_ingress_or_unrestricted_egress" {
  command = plan

  assert {
    condition     = output.public_worker_ingress_enabled == false
    error_message = "Worker must never have a public ingress route."
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface) == 5
    error_message = "Worker needs ECR API/DKR, logs, Secrets Manager and STS private endpoints."
  }

  assert {
    condition     = aws_vpc_security_group_egress_rule.worker_to_database.from_port == 5432
    error_message = "Worker database traffic must use PostgreSQL port only."
  }

  assert {
    condition     = aws_vpc_security_group_egress_rule.worker_to_endpoints.to_port == 443
    error_message = "Worker service endpoint traffic must use HTTPS only."
  }

  assert {
    condition     = aws_vpc_endpoint.s3_gateway.vpc_endpoint_type == "Gateway"
    error_message = "S3 ECR image traffic needs a gateway endpoint."
  }
}

run "reject_insufficient_private_subnets" {
  command = plan

  variables {
    private_subnet_ids = ["subnet-00000001"]
  }

  expect_failures = [var.private_subnet_ids]
}
