mock_provider "aws" {}

override_data {
  target = data.aws_caller_identity.current
  values = {
    account_id = "123456789012"
  }
}

override_data {
  target = data.aws_region.current
  values = {
    name = "us-east-1"
  }
}

variables {
  name_prefix           = "northstar"
  environment           = "qualification"
  aws_account_id        = "123456789012"
  aws_region            = "us-east-1"
  relay_lambda_arn      = "arn:aws:lambda:us-east-1:123456789012:function:northstar-outbox-relay"
  recovery_lambda_arn   = "arn:aws:lambda:us-east-1:123456789012:function:northstar-outbox-recovery"
  sns_kms_key_arn       = "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
  relay_timeout_seconds = 60
}

run "queue_and_gate_are_low_idle_cost" {
  command = plan

  assert {
    condition     = aws_sqs_queue.nudge.visibility_timeout_seconds >= 6 * var.relay_timeout_seconds
    error_message = "Queue visibility must cover six Lambda timeouts."
  }

  assert {
    condition     = aws_sqs_queue.nudge.sqs_managed_sse_enabled && aws_sqs_queue.dead_letter.sqs_managed_sse_enabled
    error_message = "Both queues must encrypt messages."
  }

  assert {
    condition     = aws_dynamodb_table.activity.billing_mode == "PAY_PER_REQUEST"
    error_message = "The activity marker must not provision idle capacity."
  }

  assert {
    condition     = aws_cloudwatch_event_rule.recovery.schedule_expression == "rate(15 minutes)"
    error_message = "Recovery must run on the planned bounded cadence."
  }

  assert {
    condition     = aws_lambda_event_source_mapping.nudge.batch_size == 1
    error_message = "Each SQS nudge must trigger one bounded relay invocation."
  }

  assert {
    condition     = aws_sns_topic.domain_events.fifo_topic && !aws_sns_topic.domain_events.content_based_deduplication
    error_message = "Domain events require an explicit-ID SNS FIFO topic."
  }
}
