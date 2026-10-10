# This module wires pre-existing, separately reviewed Lambda functions. It does
# not create application images, IAM roles, VPC connections or production data.
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name = "${var.name_prefix}-${var.environment}-outbox"
  tags = merge(var.tags, {
    Component   = "northstar-scale-to-zero-outbox"
    Environment = var.environment
    ManagedBy   = "terraform"
  })
  lambda_arn_prefix = "arn:${startswith(var.aws_region, "us-gov-") ? "aws-us-gov" : "aws"}:lambda:${var.aws_region}:${var.aws_account_id}:function:"
  kms_arn_prefix    = "arn:${startswith(var.aws_region, "us-gov-") ? "aws-us-gov" : "aws"}:kms:${var.aws_region}:${var.aws_account_id}:key/"
  # Keep in sync with northstar_api.handlers.domain_events.ROUTED_TYPES.
  # Other outbox events have no legacy subscriber and must not fill the DLQ.
  domain_event_types = [
    "channel.event.received.v1",
    "chat.response.completed.v1",
    "conversation.state.changed.v1",
    "crm.connection.backfill.requested.v1",
    "crm.webhook.received.v1",
    "education.conversation.resolution.context_missing.v1",
    "feedback.recorded.v1",
    "knowledge.source.deleted.v1",
    "lead.created.v1",
    "lead.crm.delivery.failed.v1",
    "lead.crm.sync.requested.v1",
    "lead.updated.v1",
  ]
}

resource "aws_sqs_queue" "dead_letter" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags

  lifecycle {
    prevent_destroy = true
    precondition {
      condition = (
        data.aws_caller_identity.current.account_id == var.aws_account_id &&
        data.aws_region.current.name == var.aws_region &&
        startswith(var.relay_lambda_arn, local.lambda_arn_prefix) &&
        startswith(var.recovery_lambda_arn, local.lambda_arn_prefix) &&
        startswith(var.domain_event_lambda_arn, local.lambda_arn_prefix) &&
        startswith(var.sns_kms_key_arn, local.kms_arn_prefix)
      )
      error_message = "Provider and both Lambda ARNs must match the approved AWS account and region."
    }
  }
}

resource "aws_sqs_queue" "nudge" {
  name                       = "${local.name}-nudge"
  visibility_timeout_seconds = var.relay_timeout_seconds * 6
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 5
  })
  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_dynamodb_table" "activity" {
  name         = "${local.name}-activity"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "activity_key"
  attribute {
    name = "activity_key"
    type = "S"
  }
  server_side_encryption {
    enabled = true
  }
  point_in_time_recovery {
    enabled = true
  }
  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sns_topic" "domain_events" {
  name                        = "${local.name}-events.fifo"
  fifo_topic                  = true
  content_based_deduplication = false
  kms_master_key_id           = var.sns_kms_key_arn
  tags                        = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sqs_queue" "domain_event_dead_letter" {
  name                      = "${local.name}-events-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
  tags                      = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_sqs_queue" "domain_events" {
  name                       = "${local.name}-events.fifo"
  fifo_queue                 = true
  visibility_timeout_seconds = var.domain_event_timeout_seconds * 6
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.domain_event_dead_letter.arn
    maxReceiveCount     = 5
  })
  tags = local.tags

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "domain_event_queue_delivery" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.domain_events.arn]
    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.domain_events.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.aws_account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "domain_event_delivery" {
  queue_url = aws_sqs_queue.domain_events.id
  policy    = data.aws_iam_policy_document.domain_event_queue_delivery.json
}

# Subscription and trigger are deliberately absent until an explicit reviewed
# cutover. Applying the foundation alone cannot start a second event path.
resource "aws_sns_topic_subscription" "domain_events" {
  count                = var.activate_domain_event_subscription ? 1 : 0
  topic_arn            = aws_sns_topic.domain_events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.domain_events.arn
  raw_message_delivery = false
  filter_policy        = jsonencode({ eventType = local.domain_event_types })
  depends_on           = [aws_sqs_queue_policy.domain_event_delivery]
}

resource "aws_lambda_event_source_mapping" "domain_events" {
  count                   = var.activate_domain_event_subscription ? 1 : 0
  event_source_arn        = aws_sqs_queue.domain_events.arn
  function_name           = var.domain_event_lambda_arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]
  enabled                 = true
  depends_on              = [aws_sns_topic_subscription.domain_events]
}

resource "aws_lambda_event_source_mapping" "nudge" {
  event_source_arn = aws_sqs_queue.nudge.arn
  function_name    = var.relay_lambda_arn
  batch_size       = 1
  enabled          = true
}

resource "aws_cloudwatch_event_rule" "recovery" {
  name                = "${local.name}-recovery"
  description         = "Activity-gated outbox recovery; handler checks DynamoDB before PostgreSQL"
  schedule_expression = "rate(15 minutes)"
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "recovery" {
  rule = aws_cloudwatch_event_rule.recovery.name
  arn  = var.recovery_lambda_arn
}

resource "aws_lambda_permission" "recovery_schedule" {
  statement_id  = "AllowOutboxRecoverySchedule"
  action        = "lambda:InvokeFunction"
  function_name = var.recovery_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.recovery.arn
}

data "aws_iam_policy_document" "writer" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.nudge.arn]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.activity.arn]
  }
}

data "aws_iam_policy_document" "relay" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.nudge.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.nudge.arn]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.activity.arn]
  }
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.domain_events.arn]
  }
  statement {
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [var.sns_kms_key_arn]
  }
}

data "aws_iam_policy_document" "recovery" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.activity.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.nudge.arn]
  }
}

data "aws_iam_policy_document" "domain_event_consumer" {
  statement {
    actions = [
      "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"
    ]
    resources = [aws_sqs_queue.domain_events.arn]
  }
}
