from __future__ import annotations

from northstar_api.lead_crm.connectors import crm_registry
from northstar_api.lead_crm.providers.generic import GenericRESTConnector, GenericWebhookConnector
from northstar_api.lead_crm.providers.native_v2 import (
    Dynamics365Connector,
    FreshsalesConnector,
    HubSpotConnector,
    PipedriveConnector,
    SalesforceConnector,
)
from northstar_api.lead_crm.providers.zoho import ZohoCRMConnector


def register_default_connectors() -> None:
    connectors = (
        ZohoCRMConnector(),
        SalesforceConnector(),
        HubSpotConnector(),
        Dynamics365Connector(),
        PipedriveConnector(),
        FreshsalesConnector(),
        GenericRESTConnector(),
        GenericWebhookConnector(),
    )
    registered = set(crm_registry.providers()) if crm_registry._defaults_loaded else set()  # noqa: SLF001
    for connector in connectors:
        if connector.provider not in registered:
            crm_registry.register(connector)
            registered.add(connector.provider)


__all__ = ["register_default_connectors"]
