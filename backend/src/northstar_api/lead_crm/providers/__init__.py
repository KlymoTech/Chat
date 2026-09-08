from __future__ import annotations

from northstar_api.lead_crm.connectors import CRMError, crm_registry
from northstar_api.lead_crm.domain import CRMProvider
from northstar_api.lead_crm.providers.generic import GenericRESTConnector, GenericWebhookConnector
from northstar_api.lead_crm.providers.zoho import ZohoCRMConnector


def register_default_connectors() -> None:
    connectors = (ZohoCRMConnector(), GenericRESTConnector(), GenericWebhookConnector())
    registered = set(crm_registry.providers())
    for connector in connectors:
        if connector.provider not in registered:
            crm_registry.register(connector)
            registered.add(connector.provider)


__all__ = ["register_default_connectors"]
