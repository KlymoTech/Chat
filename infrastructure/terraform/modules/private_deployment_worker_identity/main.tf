locals {
  tags = merge(var.tags, {
    Component   = "northstar-private-deployment-worker"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
}

data "aws_iam_policy_document" "ecs_task_trust" {
  statement {
    sid     = "OnlyEcsTasksInApprovedAccount"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${var.aws_region}:${var.aws_account_id}:*"]
    }
  }
}

# Application task role: zero AWS API grants by design. Cloud-change execution
# MUST use a different, independently approved runner role in a later phase.
resource "aws_iam_role" "worker_task" {
  name                 = "${var.name_prefix}-worker-task"
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permissions_boundary_arn
  max_session_duration = 3600
  tags                 = local.tags
}

resource "aws_iam_role" "worker_execution" {
  name                 = "${var.name_prefix}-worker-execution"
  assume_role_policy   = data.aws_iam_policy_document.ecs_task_trust.json
  permissions_boundary = var.permissions_boundary_arn
  max_session_duration = 3600
  tags                 = local.tags

  lifecycle {
    precondition {
      condition = alltrue(concat(
        [
          strcontains(var.ecr_repository_arn, ":${var.aws_region}:${var.aws_account_id}:"),
          strcontains(var.log_group_arn, ":${var.aws_region}:${var.aws_account_id}:"),
        ],
        [for arn in var.bootstrap_secret_arns : strcontains(arn, ":${var.aws_region}:${var.aws_account_id}:")],
        [for arn in var.bootstrap_kms_key_arns : strcontains(arn, ":${var.aws_region}:${var.aws_account_id}:")],
      ))
      error_message = "ECR, logging, secret and KMS ARNs must match the approved AWS account and region."
    }

    precondition {
      condition     = length(var.bootstrap_kms_key_arns) == 0 || length(var.bootstrap_secret_arns) > 0
      error_message = "KMS grants cannot exist without explicit bootstrap secrets."
    }
  }
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid       = "AuthenticateToEcr"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # ECR requires '*' only for this authentication action.
  }

  statement {
    sid    = "PullFromSingleApprovedEcrRepository"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid       = "WriteOnlyWorkerLogStream"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${trimsuffix(var.log_group_arn, ":*")}:log-stream:*"]
  }

  dynamic "statement" {
    for_each = length(var.bootstrap_secret_arns) > 0 ? [1] : []
    content {
      sid       = "ReadExplicitBootstrapSecrets"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = sort(tolist(var.bootstrap_secret_arns))
    }
  }

  dynamic "statement" {
    for_each = length(var.bootstrap_kms_key_arns) > 0 ? [1] : []
    content {
      sid       = "DecryptOnlyThroughSecretsManager"
      effect    = "Allow"
      actions   = ["kms:Decrypt"]
      resources = sort(tolist(var.bootstrap_kms_key_arns))

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["secretsmanager.${var.aws_region}.amazonaws.com"]
      }

      condition {
        test     = "ForAnyValue:StringEquals"
        variable = "kms:EncryptionContext:SecretARN"
        values   = sort(tolist(var.bootstrap_secret_arns))
      }
    }
  }
}

resource "aws_iam_role_policy" "worker_execution" {
  name   = "${var.name_prefix}-worker-bootstrap-only"
  role   = aws_iam_role.worker_execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# No aws_iam_role_policy and no policy attachments on worker_task intentionally.
# Worker operations are scoped by the application's machine JWT + DB role.
