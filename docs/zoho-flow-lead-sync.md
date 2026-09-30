# Zoho Flow lead sync

This optional worker mirrors ordinary CRM lead-created and lead-updated events to a
Zoho Flow webhook. It does not replace the existing Zoho CRM connection or change
the normal delivery path:

`Lead -> PostgreSQL outbox -> Kafka -> Zoho Flow lead-delivery worker -> Zoho Flow webhook`

Education leads are deliberately excluded. The worker is disabled unless both of
these server-side settings are configured in `.env`:

```dotenv
ZOHO_FLOW_LEAD_WEBHOOK_URL=https://flow.zoho.com/...
ZOHO_FLOW_LEAD_WORKSPACE_ID=<Northstar workspace UUID>
ZOHO_FLOW_WEBHOOK_TIMEOUT_SECONDS=10
```

The webhook receives `lead_id`, `workspace_id`, first and last name, email, phone,
status, source, and `event_id`. `event_id` is also sent as the `Idempotency-Key`
header so retries do not create duplicate Flow actions.

For the existing platform-managed Zoho CRM consent flow, set `ZOHO_CLIENT_ID`,
`ZOHO_CLIENT_SECRET`, the matching Zoho region URLs, and the exact registered
`ZOHO_OAUTH_REDIRECT_URI`. These values are server-side secrets; do not put them in
frontend configuration.

After adding or changing settings, rebuild and start only the affected services:

```powershell
docker compose build api
docker compose up -d --no-deps --force-recreate api zoho-flow-lead-delivery
```

To test, create or update a non-Education lead in the configured workspace, then
inspect the Zoho Flow trigger and the `zoho-flow-lead-delivery` logs. Existing CRM
providers, course workflows, WhatsApp, and Telegram continue unchanged.
