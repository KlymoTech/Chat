# Planned scale-to-zero outbox foundation

This module is non-deploying until explicitly instantiated with approved AWS
account, region, pre-existing relay/recovery/domain-event Lambda ARNs, and an approved
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
  `domain_events_topic_arn` output on the relay Lambda. Set that topic ARN and
  `PLATFORM_DOMAIN_EVENTS_QUEUE_ARN` = `domain_events_queue_arn` on the
  domain-event Lambda. Existing Kafka
  deployments retain `PLATFORM_EVENTS_BACKEND=kafka` by default.

The relay Lambda must package `northstar_api.handlers.outbox_relay:lambda_handler`,
the recovery Lambda `northstar_api.handlers.outbox_recovery:lambda_handler`, and
the domain-event Lambda `northstar_api.handlers.domain_events:lambda_handler`.
Attach `domain_event_consumer_policy_json` to the latter's execution role.
The SNS subscription and event source mapping are absent by default;
`activate_domain_event_subscription=true` creates one filtered FIFO subscription
for precisely the seven existing Kafka consumers' topic set and a batch-size-one
Lambda trigger with partial-batch failure reporting. Other outbox event types
still publish to SNS, but do not enter this queue because they have no legacy
consumer. Keep the legacy polling worker active until queues, permissions,
networking, broker connectivity, retry/DLQ behavior, and SNS-to-SQS delivery
have been verified in the target account. Stop the legacy Kafka consumers and
relay before enabling the SNS publisher/trigger to avoid dual delivery. The
Zoho Flow webhook's existing idempotency-key contract still requires a receiver
that honors that key. Run `terraform test` from this module directory for mocked
topology checks; a live qualification is still required before production
activation. No AWS resources are deployed by this repository change alone.
