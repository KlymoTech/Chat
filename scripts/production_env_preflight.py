"""Validate critical production environment settings before starting a deployment.

This is an additional preflight check, not a replacement for application
configuration validation or integration testing.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

REQUIRED = ("JWT_SECRET", "MFA_ENCRYPTION_KEY", "DATABASE_URL", "APP_CORS_ORIGINS")
PLACEHOLDER = re.compile(r"replace|change.me|example|localhost|127\.0\.0\.1", re.I)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid environment entry at line {number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid environment key at line {number}")
        if key in values:
            raise ValueError(f"Duplicate environment key {key} at line {number}")
        value = value.strip()
        if value.startswith(('"', "'")):
            quote = value[0]
            if len(value) < 2 or not value.endswith(quote):
                raise ValueError(f"Unterminated quoted value at line {number}")
            value = value[1:-1]
        values[key] = value
    return values




def public_hostname(hostname: str) -> bool:
    """Reject local, loopback and private IP literals as public CORS origins."""
    if (
        PLACEHOLDER.search(hostname)
        or hostname.endswith((".local", ".localhost", ".internal"))
        or hostname in {"localhost", "local"}
        or any(character.isspace() for character in hostname)
    ):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.split(".")
        return (
            len(labels) >= 2
            and len(hostname) <= 253
            and not labels[-1].isdigit()
            and not all(label.isdigit() for label in labels)
            and all(
                label
                and len(label) <= 63
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in labels
            )
        )
    return address.is_global


def valid_https_origin(origin: object) -> bool:
    """Require a canonical HTTPS origin without credentials, paths or fragments."""
    if not isinstance(origin, str) or not origin or origin != origin.strip():
        return False
    try:
        parsed = urlparse(origin)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
            and public_hostname(parsed.hostname)
            and parsed.netloc == origin.removeprefix("https://")
            and parsed.hostname == parsed.hostname.lower()
            and parsed.hostname not in {"0.0.0.0", "::1"}
        )
    except ValueError:
        return False



def valid_postgres_url(value: str) -> bool:
    """Require a usable PostgreSQL URL without embedded placeholder credentials."""
    try:
        parsed = urlparse(value)
        options = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        allowed_options = {"sslmode", "ssl"}
        if not options:
            return False
        if len({key for key, _ in options}) != len(options):
            return False
        if {key for key, _ in options} == {"ssl", "sslmode"}:
            return False
        if any(key not in allowed_options or not option for key, option in options):
            return False
        if any(key == "sslmode" and option not in {"require", "verify-ca", "verify-full"} for key, option in options):
            return False
        if any(key == "ssl" and option.lower() not in {"true", "1"} for key, option in options):
            return False
        if parsed.scheme == "postgresql+asyncpg" and any(key == "sslmode" for key, _ in options):
            return False
        if parsed.scheme == "postgresql" and any(key == "ssl" for key, _ in options):
            return False
        return (
            parsed.scheme in {"postgresql", "postgresql+asyncpg"}
            and bool(parsed.hostname)
            and bool(parsed.username)
            and bool(parsed.password)
            and bool(parsed.path.strip("/"))
            and parsed.port != 0
            and not parsed.fragment
            and not PLACEHOLDER.search(parsed.hostname)
            and not PLACEHOLDER.search(unquote(parsed.username))
            and not PLACEHOLDER.search(unquote(parsed.password))
            and bool(unquote(parsed.password).strip())
        )
    except ValueError:
        return False


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    if values.get("APP_ENV", "").lower() != "production":
        errors.append("APP_ENV must be production")
    for key in REQUIRED:
        value = values.get(key, "")
        if not value:
            errors.append(f"{key} is required")
        elif key in {"JWT_SECRET", "MFA_ENCRYPTION_KEY"} and PLACEHOLDER.search(value):
            errors.append(f"{key} contains a development placeholder")
    database_url = values.get("DATABASE_URL", "")
    if database_url and not valid_postgres_url(database_url):
        errors.append("DATABASE_URL must be a valid PostgreSQL URL with non-placeholder credentials")
    jwt = values.get("JWT_SECRET", "")
    mfa = values.get("MFA_ENCRYPTION_KEY", "")
    if jwt and len(jwt) < 32:
        errors.append("JWT_SECRET must have at least 32 characters")
    if mfa and len(mfa) < 32:
        errors.append("MFA_ENCRYPTION_KEY must have at least 32 characters")
    if jwt and mfa and jwt == mfa:
        errors.append("JWT_SECRET and MFA_ENCRYPTION_KEY must be distinct")
    if jwt and len(set(jwt)) < 8:
        errors.append("JWT_SECRET must not be a repeated or low-diversity value")
    if mfa and len(set(mfa)) < 8:
        errors.append("MFA_ENCRYPTION_KEY must not be a repeated or low-diversity value")
    if values.get("APP_AUTO_CREATE_SCHEMA", "false").lower() != "false":
        errors.append("APP_AUTO_CREATE_SCHEMA must be false")
    if values.get("ALLOW_PRODUCTION_SEED", "false").lower() != "false":
        errors.append("ALLOW_PRODUCTION_SEED must be false")
    if values.get("SEED_DEMO_AGENT", "false").lower() != "false":
        errors.append("SEED_DEMO_AGENT must be false")
    try:
        origins = json.loads(values.get("APP_CORS_ORIGINS", "[]"))
        if not isinstance(origins, list) or not origins:
            errors.append("APP_CORS_ORIGINS must be a nonempty JSON array")
        elif any(not valid_https_origin(origin) for origin in origins):
            errors.append("APP_CORS_ORIGINS must contain only valid HTTPS origins")
    except json.JSONDecodeError:
        errors.append("APP_CORS_ORIGINS must be valid JSON")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        errors = validate(load_env(args.env_file))
    except (OSError, ValueError) as exc:
        print(f"Production preflight failed: {exc}")
        return 1
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("Production environment preflight passed (critical settings only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
