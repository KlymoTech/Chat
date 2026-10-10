"""Validate critical production environment settings before starting a deployment.

This is an additional preflight check, not a replacement for application
configuration validation or integration testing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

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
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values



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
            and not PLACEHOLDER.search(parsed.hostname)
            and parsed.netloc == origin.removeprefix("https://")
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
        elif PLACEHOLDER.search(value):
            errors.append(f"{key} contains a development placeholder or local endpoint")
    database_url = values.get("DATABASE_URL", "")
    if database_url and not database_url.startswith(("postgresql://", "postgresql+asyncpg://")):
        errors.append("DATABASE_URL must use PostgreSQL in production")
    jwt = values.get("JWT_SECRET", "")
    mfa = values.get("MFA_ENCRYPTION_KEY", "")
    if jwt and len(jwt) < 32:
        errors.append("JWT_SECRET must have at least 32 characters")
    if mfa and len(mfa) < 32:
        errors.append("MFA_ENCRYPTION_KEY must have at least 32 characters")
    if jwt and mfa and jwt == mfa:
        errors.append("JWT_SECRET and MFA_ENCRYPTION_KEY must be distinct")
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
