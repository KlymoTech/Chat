output "nudge_queue_url" {
  value = aws_sqs_queue.nudge.url
}

output "nudge_queue_arn" {
  value = aws_sqs_queue.nudge.arn
}

output "dead_letter_queue_arn" {
  value = aws_sqs_queue.dead_letter.arn
}

output "activity_table_name" {
  value = aws_dynamodb_table.activity.name
}

output "activity_table_arn" {
  value = aws_dynamodb_table.activity.arn
}

output "domain_events_topic_arn" {
  value = aws_sns_topic.domain_events.arn
}

output "domain_events_queue_arn" {
  value = aws_sqs_queue.domain_events.arn
}

output "domain_events_queue_url" {
  value = aws_sqs_queue.domain_events.url
}

output "domain_events_dead_letter_queue_arn" {
  value = aws_sqs_queue.domain_event_dead_letter.arn
}

output "dead_letter_alarm_arns" {
  value = { for name, alarm in aws_cloudwatch_metric_alarm.dead_letter_nonempty : name => alarm.arn }
}

output "writer_iam_policy_json" {
  value = data.aws_iam_policy_document.writer.json
}

output "relay_iam_policy_json" {
  value = data.aws_iam_policy_document.relay.json
}

output "recovery_iam_policy_json" {
  value = data.aws_iam_policy_document.recovery.json
}

output "domain_event_consumer_iam_policy_json" {
  value = data.aws_iam_policy_document.domain_event_consumer.json
}
