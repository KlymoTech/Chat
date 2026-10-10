"""Website campaign links are stable, validated, and CRM-independent."""
import pytest
from pydantic import ValidationError
from urllib.parse import parse_qs, urlsplit
from northstar_api.services.website_campaign_links import CampaignLink, build_campaign_url


def test_campaign_link_keeps_existing_nontracking_parameters():
    link = CampaignLink(destination="https://example.org/signup?ref=abc&utm_source=old",
                        source="newsletter", medium="email", campaign="autumn launch")
    result = build_campaign_url(link)
    params = parse_qs(urlsplit(result).query)
    assert params["ref"] == ["abc"]
    assert params["utm_source"] == ["newsletter"]
    assert params["utm_campaign"] == ["autumn launch"]


@pytest.mark.parametrize("destination", [
    "http://example.org", "javascript:alert(1)", "//example.org",
    "https://person:secret@example.org", "/relative", "https://example.org/#fragment",
])
def test_reject_unsafe_destinations(destination):
    with pytest.raises(ValidationError):
        CampaignLink(destination=destination, source="email", medium="owned", campaign="launch")


def test_generated_url_is_deterministic():
    link = CampaignLink(destination="https://example.org/", source="search", medium="cpc",
                        campaign="fall", term="product")
    assert build_campaign_url(link) == build_campaign_url(link)


def test_invalid_utm_value_fails_validation():
    with pytest.raises(ValidationError):
        CampaignLink(destination="https://example.org/", source="\nmalicious",
                     medium="cpc", campaign="test")
