# Planned scale-to-zero outbox foundation

This module is non-deploying until explicitly instantiated with approved AWS
account, region, pre-existing relay/recovery Lambda ARNs, and an approved
regional SNS KMS key ARN. It creates a standard SQS nudge queue and encrypted
DLQ, an on-demand DynamoDB activity table, an encrypted SNS FIFO domain-event
topic, an SQS-to-relay event source mapping, and a 15-minute EventBridge
recovery schedule. Destruction of the queue, DLQ, topic, and activity table is
guarded.

The caller must ensure the KMS key policy permits the relay publisher; the
module's relay policy output grants the exact key ARN. Attach the output
least-privilege IAM policy documents to the API writer, relay, and recovery
execution roles, respectively. The relay role
also needs its broker/database access and the recovery role its database access;
this module does not grant those. Set the following environment variables on
the API writer and on both Lambda functions as appropriate:

- `PLATFORM_OUTBOX_NUDGE_QUEUE_URL` = `nudge_queue_url` output.
- `PLATFORM_ACTIVITY_TABLE` = `activity_table_name` output.
- `PLATFORM_ACTIVITY_KEY` = a stable, environment-specific key shared by all three.
- `PLATFORM_EVENTS_BACKEND=sns` and `PLATFORM_DOMAIN_EVENTS_TOPIC_ARN` =
  `domain_events_topic_arn` output on the relay Lambda only. Existing Kafka
  deployments retain `PLATFORM_EVENTS_BACKEND=kafka` by default.

The relay Lambda must package `northstar_api.handlers.outbox_relay:lambda_handler`
and the recovery Lambda must package
`northstar_api.handlers.outbox_recovery:lambda_handler`. Keep the legacy polling
worker active until queues, permissions, networking, broker connectivity, and
retry/DLQ behavior and actual SNS-to-SQS subscriptions/consumers have been
verified in the target account. This module does not create event subscriptions
or migrate the seven existing Kafka consumers. Stop the legacy relay before
enabling the new event-source mapping to avoid dual delivery. Run `terraform
test` from this module directory for mocked topology checks; a live qualification
is still required before production activation.
