"""Validation for Help Center links configured by workspace administrators."""

from __future__ import annotations

import ipaddress
from urllib.parse import unquote, urlsplit


def safe_support_url(value: object) -> str:
    """Return a safe external HTTPS support URL, or an empty string.

    This value becomes a browser link, not a server-side fetch target. Reject
    credential-bearing links, local destinations and ambiguous URL syntax.
    """
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if not candidate or "\\" in candidate or any(character.isspace() for character in candidate):
        return ""
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or not hostname
            or "@" in parsed.netloc
            or parsed.port == 0
            or any(ord(character) < 32 or ord(character) == 127 for character in unquote(candidate))
        ):
            return ""
        hostname = hostname.lower()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            return ""
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            if "." not in hostname or hostname.startswith(".") or hostname.endswith("."):
                return ""
        else:
            if not address.is_global:
                return ""
        return candidate
    except ValueError:
        return ""
