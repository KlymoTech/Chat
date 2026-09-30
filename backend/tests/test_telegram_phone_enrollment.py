from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from northstar_api.database import SessionFactory
from northstar_api.lead_crm.channel_providers import TelegramConnector
from northstar_api.lead_crm.channels import ChannelConnectionContext
from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.services.telegram_enrollment import DENIED, telegram_enrollment_notice


async def test_staff_managed_telegram_identity_authorizes_without_contact_share(client, auth_headers):
    workspace = (await client.get('/api/v1/workspace', headers=auth_headers)).json()
    agent = SimpleNamespace(tenant_id=UUID(workspace['tenantId']), workspace_id=UUID(workspace['id']))
    sender = '9988776655'
    created = await client.post('/api/v1/education/students', headers=auth_headers, json={
        'studentNumber': 'TELEGRAM-ID', 'name': 'Telegram Student',
        'telegramUserId': sender, 'telegramVerified': True,
    })
    assert created.status_code == 201
    event = SimpleNamespace(sender=SimpleNamespace(external_id=sender), conversation_reference=sender, metadata={'chatType': 'private'})
    async with SessionFactory() as session:
        assert await telegram_enrollment_notice(session, event=event, agent=agent) is None
        unknown = SimpleNamespace(sender=SimpleNamespace(external_id='9988776656'), conversation_reference='9988776656', metadata={'chatType': 'private'})
        assert (await telegram_enrollment_notice(session, event=unknown, agent=agent))[0] == DENIED


async def test_telegram_id_is_unique_per_workspace(client, auth_headers):
    first = await client.post('/api/v1/education/students', headers=auth_headers, json={
        'studentNumber': 'TELEGRAM-ONE', 'name': 'First Student', 'telegramUserId': '123456789', 'telegramVerified': True,
    })
    assert first.status_code == 201
    duplicate = await client.post('/api/v1/education/students', headers=auth_headers, json={
        'studentNumber': 'TELEGRAM-TWO', 'name': 'Second Student', 'telegramUserId': '123456789', 'telegramVerified': True,
    })
    assert duplicate.status_code == 409


async def test_normalize_telegram_sender_identity():
    connector = TelegramConnector()
    context = ChannelConnectionContext(tenant_id=UUID('00000000-0000-0000-0000-000000000001'), connection_id=UUID('00000000-0000-0000-0000-000000000002'), provider=ChannelProvider.TELEGRAM, configuration={}, credentials={})
    events = await connector.normalize(context, payload={'update_id': 1, 'message': {'message_id': 2, 'from': {'id': 9988776655}, 'chat': {'id': 9988776655, 'type': 'private'}, 'text': 'Hi'}}, correlation_id='telegram-test', received_at=datetime.now(UTC))
    assert events[0].sender.external_id == '9988776655'
    assert events[0].message.text == 'Hi'
