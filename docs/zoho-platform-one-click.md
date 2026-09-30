# Platform-managed Zoho connection

Customers use **Integrations → Zoho CRM → Connect Zoho** and authorize access.
They do not create OAuth applications or enter developer credentials. The platform
stores application credentials and customer grants server-side.

Set the following in `.env`; never expose them as `VITE_*` values:

```dotenv
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_ACCOUNTS_URL=https://accounts.zoho.com
ZOHO_API_DOMAIN=https://www.zohoapis.com
ZOHO_API_VERSION=v8
ZOHO_OAUTH_SCOPES=ZohoCRM.modules.ALL,ZohoCRM.settings.ALL,ZohoCRM.org.READ
ZOHO_OAUTH_FRONTEND_URL=http://localhost:3100/integrations
ZOHO_OAUTH_REDIRECT_URI=http://localhost:8100/api/v1/crm/zoho/one-click/callback
ZOHO_LIVE_CERTIFICATION_ENABLED=true
```

The redirect URI must exactly match the URI registered in the Zoho server-based
application. Use the appropriate Zoho regional account and API domains for the
customer's data center. Optional `ZOHO_CLIENT_SECRET_US`, `_IN`, `_EU`, `_AU`,
`_JP`, `_CA`, and `_CN` values support regional secrets.

After setting the values, rebuild and restart the API:

```powershell
docker compose build api
docker compose up -d --no-deps --force-recreate api
```

Normal CRM lead delivery remains the existing provider-based route. The optional
Zoho Flow mirror is documented separately in `zoho-flow-lead-sync.md`.
