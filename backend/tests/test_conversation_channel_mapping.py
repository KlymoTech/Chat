from northstar_api.lead_crm.domain import ChannelProvider
from northstar_api.models import Channel
from northstar_api.workers.channel_event_consumer import _conversation_channel


def test_channel_events_keep_their_messaging_provider_for_conversation_filters() -> None:
    assert _conversation_channel(ChannelProvider.TELEGRAM) is Channel.TELEGRAM
    assert _conversation_channel(ChannelProvider.INSTAGRAM) is Channel.INSTAGRAM
    assert _conversation_channel(ChannelProvider.FACEBOOK_MESSENGER) is Channel.FACEBOOK_MESSENGER
    assert _conversation_channel(ChannelProvider.CUSTOM) is Channel.CUSTOM
