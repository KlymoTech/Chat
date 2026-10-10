# Planned scale-to-zero outbox foundation

This module is non-deploying until explicitly instantiated with approved AWS
account, region, and pre-existing relay/recovery Lambda ARNs. It creates a
standard SQS nudge queue and encrypted DLQ, an on-demand DynamoDB activity
table, an SQS-to-relay event source mapping, and a 15-minute EventBridge recovery
schedule. Destruction of the queue, DLQ, and activity table is guarded.

The caller must attach the output least-privilege IAM policy documents to the
API writer, relay, and recovery execution roles, respectively. The relay role
also needs its broker/database access and the recovery role its database access;
this module does not grant those. Set the following environment variables on
the API writer and on both Lambda functions as appropriate:

- `PLATFORM_OUTBOX_NUDGE_QUEUE_URL` = `nudge_queue_url` output.
- `PLATFORM_ACTIVITY_TABLE` = `activity_table_name` output.
- `PLATFORM_ACTIVITY_KEY` = a stable, environment-specific key shared by all three.

The relay Lambda must package `northstar_api.handlers.outbox_relay:lambda_handler`
and the recovery Lambda must package
`northstar_api.handlers.outbox_recovery:lambda_handler`. Keep the legacy polling
worker active until queues, permissions, networking, broker connectivity, and
retry/DLQ behavior have been verified in the target account. Stop it before
enabling the new event-source mapping to avoid dual delivery. Run `terraform
test` from this module directory for mocked topology checks; a live qualification
is still required before production activation.
