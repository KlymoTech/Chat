"""One-use, exact-match patch for the reviewed CRM acceptance fixes.

Only used on the implementation branch. The accompanying job validates the
result with locked dependencies before committing; no checks are suppressed.
"""
from pathlib import Path
import re

root = Path.cwd()

def edit(path, old, new, count=1):
    target = root / path
    text = target.read_text()
    if old not in text:
        raise RuntimeError(f"Source changed; inspect before patching {path}")
    target.write_text(text.replace(old, new, count))

edit('backend/src/northstar_api/lead_crm/models.py',
    '    mapping_version: Mapped[int] = mapped_column(Integer, default=1)\n',
    '''    retry_cycle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    verification_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_cycle_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_error_code: Mapped[str | None] = mapped_column(String(80))
    verification_error_message: Mapped[str | None] = mapped_column(String(1000))
    verification_evidence_json: Mapped[dict[str, Any]] = mapped_column(MutableJSON, default=dict)
    mapping_version: Mapped[int] = mapped_column(Integer, default=1)
''')
edit('backend/src/northstar_api/lead_crm/models.py',
    '        Index("ix_crm_delivery_dispatch", "status", "next_retry_at", "created_at"),',
    '        Index("ix_crm_delivery_dispatch", "status", "next_retry_at", "created_at"),\n        Index("ix_crm_delivery_verification_dispatch", "verification_status", "next_verification_at"),')
edit('backend/src/northstar_api/lead_crm/mapping.py', '"createdAt": lead.created_at,',
    '"createdAt": lead.created_at.isoformat() if lead.created_at else None,')
edit('backend/src/northstar_api/lead_crm/mapping.py', '"updatedAt": lead.updated_at,',
    '"updatedAt": lead.updated_at.isoformat() if lead.updated_at else None,')
edit('backend/src/northstar_api/lead_crm/mapping.py', '    elif not output:\n', '    elif mapping is None:\n')
edit('backend/src/northstar_api/lead_crm/services.py', '                    verified=identity_type in {"email", "phone"},',
    '                    verified=False,')
edit('backend/src/northstar_api/lead_crm/services.py', '    CRMDelivery,\n', '    CRMDelivery,\n    CRMFieldMapping,\n')
edit('backend/src/northstar_api/lead_crm/services.py', 'from northstar_api.lead_crm.normalization import normalize_identity',
    'from northstar_api.lead_crm.mapping import canonical_lead\nfrom northstar_api.lead_crm.normalization import normalize_identity')
edit('backend/src/northstar_api/lead_crm/services.py',
    '            idempotency_key = f"{tenant_id}:{lead_id}:{connection.id}:upsert:v1"',
    '''            mapping = await session.scalar(select(CRMFieldMapping).where(
                CRMFieldMapping.tenant_id == tenant_id, CRMFieldMapping.connection_id == connection.id,
                CRMFieldMapping.object_name == "Leads"))
            payload_basis = canonical_lead(lead, profile)
            payload_basis.pop("createdAt", None)
            payload_basis.pop("updatedAt", None)
            payload_basis["mappingVersion"] = mapping.version if mapping else 0
            digest = _payload_hash(payload_basis)
            idempotency_key = f"{tenant_id}:{lead_id}:{connection.id}:upsert:{digest}"''')
edit('backend/src/northstar_api/lead_crm/services.py', '''            payload_basis = {
                "leadId": str(lead.id),
                "name": lead.name,
                "email": lead.email,
                "phone": lead.phone,
                "profile": profile.custom_fields_json,
            }
''', '')
edit('backend/src/northstar_api/lead_crm/services.py', '                payload_hash=_payload_hash(payload_basis),',
    '                payload_hash=digest,\n                mapping_version=mapping.version if mapping else 0,')

path = root / 'backend/src/northstar_api/workers/crm_delivery_worker.py'
text = path.read_text().replace('import asyncio\n', 'import asyncio\nimport json\n', 1)
text = text.replace('from northstar_api.lead_crm.credentials import CredentialStoreError, credential_store',
    'from northstar_api.lead_crm.connection_context import load_connection_context\nfrom northstar_api.lead_crm.verification import as_utc, verification_failed, verify_delivery')
start = text.index('    connection = await session.scalar(', text.index('async def _context('))
end = text.index('\n\nasync def _mark_failure(', start)
text = text[:start] + '''    return await load_connection_context(
        session, tenant_id=delivery.tenant_id, connection_id=delivery.connection_id
    )
''' + text[end:]
text = text.replace('    delivery.last_error_code = error.code.value\n', '''    if delivery.acknowledged_at is not None:
        await verification_failed(session, delivery, connection, error)
        return
    delivery.last_error_code = error.code.value
''', 1)
text = text.replace('delivery.attempt_count >= (_max_attempts(connection)', 'delivery.retry_cycle_attempts >= (_max_attempts(connection)')
text = text.replace('delivery.next_retry_at > datetime.now(UTC)', 'as_utc(delivery.next_retry_at) > datetime.now(UTC)')
text = text.replace('    if not delivery or delivery.status not in {', '''    if delivery is not None and delivery.acknowledged_at is not None:
        if delivery.status != CRMDeliveryStatus.VERIFIED.value:
            delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
            await verify_delivery(session, delivery)
            await session.commit()
        return
    if not delivery or delivery.status not in {''', 1)
text = text.replace('    delivery.attempt_count += 1\n', '    delivery.attempt_count += 1\n    delivery.retry_cycle_attempts += 1\n', 1)
text = text.replace('    connection = None\n    started = time.monotonic()',
    '    connection = None\n    provider_accepted = False\n    started = time.monotonic()', 1)
start = text.index('        payload = build_mapped_payload(')
end = text.index('        if delivery.operation == CRMOperation.CREATE.value:', start)
text = text[:start] + '''        if mapping is not None and mapping.status != "active":
            raise CRMError(NormalizedCRMErrorCode.MAPPING_ERROR, "CRM mapping must be validated against the current schema before delivery")
        payload = dict(delivery.payload_json or {})
        if not payload:
            payload = build_mapped_payload(
                lead, profile, mapping.mapping_json if mapping else None,
                provider=delivery.provider, configuration=connection.configuration_json,
            )
            if not payload:
                raise CRMError(NormalizedCRMErrorCode.MAPPING_ERROR, "CRM mapping produced an empty payload")
            delivery.payload_json = json.loads(json.dumps(payload))
            delivery.mapping_version = mapping.version if mapping else 0
        connector = crm_registry.get(CRMProvider(delivery.provider))
        reference = await session.scalar(select(CRMExternalReference).where(
            CRMExternalReference.tenant_id == delivery.tenant_id,
            CRMExternalReference.lead_id == delivery.lead_id,
            CRMExternalReference.connection_id == delivery.connection_id,
            CRMExternalReference.object_name == "Leads",
        ))
        if reference and delivery.operation == CRMOperation.UPSERT.value and connector.capabilities.update:
            delivery.operation = CRMOperation.UPDATE.value
            delivery.external_record_id = reference.external_id
        await session.commit()
        delivery = await session.scalar(select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update())
        if delivery is None or delivery.status != CRMDeliveryStatus.PROCESSING.value:
            return
        connection, context = await _context(session, delivery)
''' + text[end:]
text = text.replace('        now = datetime.now(UTC)\n        delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value',
    '        provider_accepted = True\n        now = datetime.now(UTC)\n        delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value', 1)
text = text.replace('        delivery.acknowledged_at = now\n',
    '        delivery.acknowledged_at = now\n        delivery.verification_status = "pending"\n', 1)
start = text.index('        if connector.capabilities.read_back and delivery.external_record_id:')
end = text.index('    except CRMError as exc:', start)
text = text[:start] + '''        delivery = await session.scalar(select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update())
        if delivery is not None:
            await verify_delivery(session, delivery)
            await session.commit()
''' + text[end:]
start = text.index('        if attempt:\n', text.index('    except CRMError as exc:', text.index('async def process_delivery')))
end = text.index('        await _mark_failure(', start)
text = text[:start] + text[start:end].replace('if attempt:', 'if stored_attempt and delivery.acknowledged_at is None:').replace('            attempt.', '            stored_attempt.') + text[end:]
start = text.index('    except Exception as exc:', text.index('async def process_delivery'))
end = text.index('\n\nasync def run_forever()', start)
text = text[:start] + '''    except Exception as exc:
        logger.error("crm_delivery_unexpected_failure", delivery_id=str(delivery_id), error=type(exc).__name__)
        await session.rollback()
        delivery = await session.scalar(select(CRMDelivery).where(CRMDelivery.id == delivery_id).with_for_update())
        if delivery is not None:
            connection = await session.scalar(select(CRMConnection).where(
                CRMConnection.id == delivery.connection_id, CRMConnection.tenant_id == delivery.tenant_id))
            if provider_accepted and delivery.acknowledged_at is None:
                delivery.status = CRMDeliveryStatus.FAILED.value
                delivery.last_error_code = "ambiguous_provider_ack"
                delivery.last_error_message = "Provider accepted before local commit failed; reconcile the remote record before retrying"
                delivery.next_retry_at = None
            else:
                await _mark_failure(session, delivery, connection, CRMError(
                    NormalizedCRMErrorCode.UNKNOWN_ERROR, "Unexpected CRM delivery failure", retryable=True))
            await session.commit()
''' + text[end:]
path.write_text(text)

path = root / 'backend/src/northstar_api/workers/crm_reconciliation.py'
text = path.read_text()
start = text.index('async def _context(')
end = text.index('async def recover_stale_processing(', start)
text = text[:start] + text[end:]
start = text.index('    for delivery in rows:', text.index('async def recover_stale_processing'))
end = text.index('    return len(rows)', start)
text = text[:start] + '''    for delivery in rows:
        if delivery.acknowledged_at is not None:
            delivery.status = CRMDeliveryStatus.ACKNOWLEDGED.value
            delivery.verification_status = "pending"
            delivery.next_verification_at = now
        else:
            connection = await session.scalar(select(CRMConnection).where(
                CRMConnection.id == delivery.connection_id, CRMConnection.tenant_id == delivery.tenant_id))
            await _mark_failure(session, delivery, connection, CRMError(
                NormalizedCRMErrorCode.TIMEOUT, "Delivery worker stopped before processing completed", retryable=True))
            attempt = await session.scalar(select(CRMDeliveryAttempt).where(
                CRMDeliveryAttempt.tenant_id == delivery.tenant_id, CRMDeliveryAttempt.delivery_id == delivery.id,
                CRMDeliveryAttempt.attempt_number == delivery.attempt_count))
            if attempt is not None and attempt.finished_at is None:
                attempt.finished_at = now
                attempt.result_status = "worker_interrupted"
                attempt.normalized_error_code = "worker_interrupted"
        session.add(LeadActivityEvent(tenant_id=delivery.tenant_id, lead_id=delivery.lead_id,
            event_type="lead.crm.delivery.recovered.v1", correlation_id=delivery.correlation_id,
            details_json={"deliveryId": str(delivery.id), "status": delivery.status}))
''' + text[end:]
start = text.index('async def reconcile_verified_records(')
end = text.index('\n\nasync def run_once(', start)
text = text[:start] + '''async def reconcile_verified_records(session: AsyncSession) -> tuple[int, int]:
    now = datetime.now(UTC)
    rows = list(await session.scalars(select(CRMDelivery).where(
        CRMDelivery.status.in_((CRMDeliveryStatus.ACKNOWLEDGED.value, CRMDeliveryStatus.VERIFYING.value)),
        CRMDelivery.acknowledged_at.is_not(None),
        CRMDelivery.verification_status.in_(("pending", "retrying")),
        or_(CRMDelivery.next_verification_at.is_(None), CRMDelivery.next_verification_at <= now),
    ).order_by(CRMDelivery.acknowledged_at).with_for_update(skip_locked=True).limit(RECONCILE_BATCH)))
    verified = 0
    deferred = 0
    for delivery in rows:
        if await verify_delivery(session, delivery):
            verified += 1
        elif delivery.verification_status == "retrying":
            deferred += 1
    return verified, deferred
''' + text[end:]
text = text.replace('from sqlalchemy import select', 'from sqlalchemy import or_, select')
text = text.replace('from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, LeadActivityEvent',
    'from northstar_api.lead_crm.models import CRMConnection, CRMDelivery, CRMDeliveryAttempt, LeadActivityEvent\nfrom northstar_api.lead_crm.verification import verify_delivery\nfrom northstar_api.workers.crm_delivery_worker import _mark_failure')
path.write_text(text)

path = root / 'backend/src/northstar_api/lead_crm/circuit.py'
text = path.read_text().replace('from northstar_api.database import Base',
    'from northstar_api.database import Base\nfrom northstar_api.lead_crm.models import CRMConnection\nfrom northstar_api.lead_crm.verification import as_utc')
text = text.replace('    circuit = await session.scalar(\n', '''    connection = await session.scalar(select(CRMConnection.id).where(
        CRMConnection.id == connection_id, CRMConnection.tenant_id == tenant_id).with_for_update())
    if connection is None:
        raise ValueError("CRM circuit connection does not exist in tenant scope")
    circuit = await session.scalar(
''', 1)
start = text.index('    if circuit.state == CircuitState.OPEN.value:')
end = text.index('\n\nasync def record_success(', start)
text = text[:start] + '''    if circuit.open_until is None or as_utc(circuit.open_until) > now:
        return False
    # Persist a lease so another worker cannot probe the same half-open circuit.
    circuit.state = CircuitState.HALF_OPEN.value
    circuit.open_until = now + timedelta(seconds=120)
    return True
''' + text[end:]
path.write_text(text)

for name in ['crm_router_consumer', 'crm_webhook_consumer', 'channel_event_consumer']:
    edit(f'backend/src/northstar_api/workers/{name}.py',
        '                        except TimeoutError:\n                            pass\n    finally:',
        '                        except TimeoutError:\n                            pass\n                        break  # Do not advance past a failed partition offset.\n    finally:')
path = root / 'backend/src/northstar_api/lead_crm/domain.py'
text = path.read_text()
start = text.index('    CRMDeliveryStatus.ACKNOWLEDGED: frozenset(')
end = text.index('    CRMDeliveryStatus.RETRYING:', start)
text = text[:start] + '''    CRMDeliveryStatus.ACKNOWLEDGED: frozenset({CRMDeliveryStatus.VERIFYING}),
    CRMDeliveryStatus.VERIFYING: frozenset({CRMDeliveryStatus.VERIFIED, CRMDeliveryStatus.ACKNOWLEDGED}),
''' + text[end:]
path.write_text(text)

edit('backend/src/northstar_api/routers/__init__.py', '    integrations,\n', '    integration_audit,\n    integrations,\n')
edit('backend/src/northstar_api/routers/__init__.py', 'api_router.include_router(integrations.router)',
    'api_router.include_router(integration_audit.router)\napi_router.include_router(integrations.router)')

# Publish verification evidence, but never the transmitted customer payload.
edit('backend/src/northstar_api/lead_crm/api_schemas.py', '    attempt_count: int\n', '''    attempt_count: int
    verification_status: str
    verification_attempt_count: int
    next_verification_at: datetime | None
    verification_error_code: str | None
    verification_error_message: str | None
    verification_evidence: dict[str, Any]
''')
edit('backend/src/northstar_api/routers/crm.py', '        attempt_count=value.attempt_count,\n', '''        attempt_count=value.attempt_count,
        verification_status=value.verification_status,
        verification_attempt_count=value.verification_attempt_count,
        next_verification_at=value.next_verification_at,
        verification_error_code=value.verification_error_code,
        verification_error_message=value.verification_error_message,
        verification_evidence=value.verification_evidence_json,
''')
edit('backend/src/northstar_api/routers/crm.py',
    '        select(CRMDelivery).where(CRMDelivery.id == delivery_id, CRMDelivery.tenant_id == principal.tenant_id)\n',
    '        select(CRMDelivery).where(CRMDelivery.id == delivery_id, CRMDelivery.tenant_id == principal.tenant_id).with_for_update()\n', 2)
edit('backend/src/northstar_api/routers/crm.py', '''    if value.status not in {"failed", "dead_letter", "mapping_error", "auth_required", "rate_limited"}:
        raise HTTPException(status_code=409, detail="CRM delivery is not retryable from its current state")
    value.status = CRMDeliveryStatus.RETRYING.value
    value.next_retry_at = datetime.now(UTC)
    value.last_error_message = None
''', '''    if value.acknowledged_at is not None:
        if value.verification_status not in {"failed", "auth_required", "retrying"}:
            raise HTTPException(status_code=409, detail="CRM verification is not retryable")
        value.status = CRMDeliveryStatus.ACKNOWLEDGED.value
        value.verification_status = "pending"
        value.verification_cycle_attempts = 0
        value.next_verification_at = datetime.now(UTC)
        value.verification_error_code = None
        value.verification_error_message = None
        phase = "verification"
    else:
        if value.status not in {"failed", "dead_letter", "mapping_error", "auth_required", "rate_limited"}:
            raise HTTPException(status_code=409, detail="CRM delivery is not retryable from its current state")
        if value.last_error_code == "ambiguous_provider_ack":
            raise HTTPException(status_code=409, detail="Reconcile the provider record before retrying an ambiguous acknowledgement")
        value.status = CRMDeliveryStatus.RETRYING.value
        value.retry_cycle_attempts = 0
        value.next_retry_at = datetime.now(UTC)
        value.last_error_message = None
        phase = "delivery"
    session.add(LeadActivityEvent(tenant_id=principal.tenant_id, lead_id=value.lead_id,
        event_type="lead.crm.retry.requested.v1", actor_type="user", actor_id=str(principal.user_id),
        correlation_id=request_id_ctx.get(), details_json={"deliveryId": str(value.id), "phase": phase}))
''')
edit('backend/src/northstar_api/routers/crm.py', '    if value.status in {"verified", "cancelled"}:',
    '    if value.acknowledged_at is not None or value.status in {"processing", "sent", "verifying", "verified", "cancelled"}:')

# Reuse the proven non-public event consumer topology for inbound CRM sync.
path = root / 'compose.yaml'
text = path.read_text()
start = text.index('  channel-event-consumer:\n')
next_service = re.search(r'(?m)^(?:  [A-Za-z0-9_-]+:|[A-Za-z0-9_-]+:)', text[start + len('  channel-event-consumer:\n'):])
assert next_service is not None
end = start + len('  channel-event-consumer:\n') + next_service.start()
block = text[start:end]
clone = block.replace('channel-event-consumer', 'crm-webhook-consumer').replace('channel_event_consumer', 'crm_webhook_consumer')
path.write_text(text[:end] + clone + text[end:])
source = root / 'kubernetes/base/channel-event-consumer.yaml'
target = root / 'kubernetes/base/crm-webhook-consumer.yaml'
assert not target.exists()
target.write_text(source.read_text().replace('channel-event-consumer', 'crm-webhook-consumer').replace('channel_event_consumer', 'crm_webhook_consumer'))
edit('kubernetes/base/kustomization.yaml', '  - channel-event-consumer.yaml\n',
    '  - channel-event-consumer.yaml\n  - crm-webhook-consumer.yaml\n')
edit('kubernetes/base/kustomization.yaml', 'crm-router|channel-event-consumer)', 'crm-router|channel-event-consumer|crm-webhook-consumer)')
print('Reviewed CRM acceptance patches applied; validation follows.')
