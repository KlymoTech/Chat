"""Workspace input contracts and non-destructive legacy display fallbacks."""
from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator, model_validator

from northstar_api.branding_validation import decode_raster
from northstar_api.onboarding_contract import SetupContract


class BusinessDay(SetupContract):
    enabled: bool = False
    opens: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    closes: str = Field(default="17:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def valid_opening_window(self) -> BusinessDay:
        if self.enabled and self.opens == self.closes:
            raise ValueError("Business opening and closing times must differ")
        return self


class BusinessHours(SetupContract):
    monday: BusinessDay = Field(default_factory=lambda: BusinessDay(enabled=True))
    tuesday: BusinessDay = Field(default_factory=lambda: BusinessDay(enabled=True))
    wednesday: BusinessDay = Field(default_factory=lambda: BusinessDay(enabled=True))
    thursday: BusinessDay = Field(default_factory=lambda: BusinessDay(enabled=True))
    friday: BusinessDay = Field(default_factory=lambda: BusinessDay(enabled=True))
    saturday: BusinessDay = Field(default_factory=BusinessDay)
    sunday: BusinessDay = Field(default_factory=BusinessDay)


class WorkspacePreferences(SetupContract):
    timezone: str = Field(default="Asia/Calcutta", min_length=2, max_length=80)
    default_language: str = Field(default="English", min_length=2, max_length=60)
    date_format: Literal["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "DD/MM/YYYY"
    industry: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    time_format: Literal["12h", "24h"] = "24h"
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    week_start: Literal["monday", "saturday", "sunday"] = "monday"
    workspace_icon: str = Field(default="", max_length=8)
    business_hours: BusinessHours = Field(default_factory=BusinessHours)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value

    @field_validator("industry", "country", "description")
    @classmethod
    def strip_profile_text(cls, value: str) -> str:
        return value.strip()


class WorkspaceSecurityPolicy(SetupContract):
    sensitive_data_masking: bool = True
    security_contact: EmailStr | None = None


class WhiteLabelWrite(SetupContract):
    company_name: str = Field(default="Northstar AI", min_length=2, max_length=160)
    logo_data_url: str = Field(default="", max_length=500_000)
    favicon_data_url: str = Field(default="", max_length=500_000)
    app_icon_data_url: str = Field(default="", max_length=500_000)
    primary_color: str = "#0c0b0b"
    secondary_color: str = "#6b6b70"
    support_email: EmailStr | None = None
    support_url: str = Field(default="", max_length=2000)
    browser_title: str = Field(default="Northstar AI", min_length=1, max_length=120)
    branded_login: bool = False
    branded_dashboard: bool = True
    branded_widget: bool = False
    branded_emails: bool = False
    remove_platform_branding: bool = False

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError("must be a six-digit hex color")
        return value.lower()

    @field_validator("logo_data_url", "favicon_data_url", "app_icon_data_url")
    @classmethod
    def safe_image(cls, value: str) -> str:
        if value:
            decode_raster(value)
        return value

    @field_validator("support_url")
    @classmethod
    def safe_support_url(cls, value: str) -> str:
        if value:
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Support links must be HTTPS URLs without embedded credentials")
        return value


class WhiteLabelSettings(WhiteLabelWrite):
    custom_domain: str = Field(default="", max_length=253)
    dns_status: Literal["not-configured"] = "not-configured"


def safe_legacy_read[ModelT: BaseModel](model: type[ModelT], raw: dict[str, Any], warnings: list[str]) -> ModelT:
    """Return safe values without changing the database or accepting invalid writes."""
    aliases = {field.alias or name: name for name, field in model.model_fields.items()}
    values = {key: value for key, value in raw.items() if key in aliases or key in model.model_fields}
    for _ in range(len(values) + 1):
        try:
            return model.model_validate(values)
        except ValidationError as exc:
            removed = False
            for error in exc.errors():
                key = str(error["loc"][0])
                name = aliases.get(key, key)
                alias = model.model_fields[name].alias if name in model.model_fields else key
                for candidate in {key, name, alias}:
                    if candidate is not None and candidate in values:
                        values.pop(candidate)
                        removed = True
                warnings.append(f"Stored {name} is invalid; using its safe default. Re-save to replace it.")
            if not removed:
                break
    return model.model_validate({})
