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
    region = "us-east-1"
  }
}

override_resource {
  target          = aws_sqs_queue.domain_event_subscription_dead_letter
  override_during = plan
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:northstar-qualification-outbox-subscription-dlq.fifo"
  }
}

variables {
  name_prefix             = "northstar"
  environment             = "qualification"
  aws_account_id          = "123456789012"
  aws_region              = "us-east-1"
  relay_lambda_arn        = "arn:aws:lambda:us-east-1:123456789012:function:northstar-outbox-relay"
  recovery_lambda_arn     = "arn:aws:lambda:us-east-1:123456789012:function:northstar-outbox-recovery"
  domain_event_lambda_arn = "arn:aws:lambda:us-east-1:123456789012:function:northstar-domain-events"
  sns_kms_key_arn         = "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab"
  alarm_topic_arn         = "arn:aws:sns:us-east-1:123456789012:northstar-operations-alerts"
  relay_timeout_seconds   = 60
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

  assert {
    condition     = length(aws_sns_topic_subscription.domain_events) == 0 && length(aws_lambda_event_source_mapping.domain_events) == 0
    error_message = "Domain event delivery must be off until explicit cutover approval."
  }

  assert {
    condition     = output.domain_events_subscription_arn == null
    error_message = "Default-off plan must not expose a publishable subscription ARN."
  }

  assert {
    condition     = aws_sqs_queue.domain_events.visibility_timeout_seconds >= 6 * var.domain_event_timeout_seconds
    error_message = "Domain event queue visibility must cover six Lambda timeouts."
  }

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.dead_letter_nonempty) == 3
    error_message = "All three DLQs must have alarms."
  }
  assert {
    condition     = alltrue([for alarm in values(aws_cloudwatch_metric_alarm.dead_letter_nonempty) : alarm.namespace == "AWS/SQS" && alarm.metric_name == "ApproximateNumberOfMessagesVisible" && alarm.threshold == 1])
    error_message = "All alarms must detect visible DLQ messages."
  }
  assert {
    condition     = alltrue([for alarm in values(aws_cloudwatch_metric_alarm.dead_letter_nonempty) : length(alarm.alarm_actions) == 1 && contains(alarm.alarm_actions, var.alarm_topic_arn)])
    error_message = "All alarms must notify the approved topic."
  }
  assert {
    condition     = aws_sqs_queue.domain_event_subscription_dead_letter.fifo_queue && aws_sqs_queue.domain_event_subscription_dead_letter.kms_master_key_id == var.sns_kms_key_arn
    error_message = "The SNS subscription DLQ must be FIFO and use the approved customer-managed KMS key."
  }
}

run "explicit_cutover_filters_to_legacy_consumer_topics" {
  command = plan

  variables {
    activate_domain_event_subscription = true
  }

  assert {
    condition     = length(aws_sns_topic_subscription.domain_events) == 1 && length(aws_lambda_event_source_mapping.domain_events) == 1
    error_message = "Explicit activation must create one subscription and one consumer trigger."
  }

  assert {
    condition     = jsondecode(aws_sns_topic_subscription.domain_events[0].filter_policy).eventType == local.domain_event_types
    error_message = "Subscription must filter out events without an existing consumer."
  }

  assert {
    condition     = jsondecode(aws_sns_topic_subscription.domain_events[0].redrive_policy).deadLetterTargetArn == aws_sqs_queue.domain_event_subscription_dead_letter.arn
    error_message = "Subscription delivery failures must redrive to their own DLQ."
  }

  assert {
    condition     = aws_lambda_event_source_mapping.domain_events[0].batch_size == 1 && contains(aws_lambda_event_source_mapping.domain_events[0].function_response_types, "ReportBatchItemFailures")
    error_message = "Consumer must use one-message batches with partial failure reporting."
  }
}
