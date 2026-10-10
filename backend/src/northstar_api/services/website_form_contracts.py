"""Versioned, strictly validated website form contracts (Blueprint §20).

These objects contain no executable HTML, SQL, custom scripts, or user-defined
regex. File handling and conditional rules are deliberately not activated until
quarantine/consent evidence is available.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

FormKind = Literal["text", "email", "phone", "select", "radio", "checkbox", "date", "consent"]
FieldSensitivity = Literal["normal", "personal", "sensitive"]


class SiteFormField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=120)
    kind: FormKind
    required: bool = False
    purpose: str = Field(min_length=3, max_length=180)
    sensitivity: FieldSensitivity = "personal"
    retention_days: int = Field(default=365, ge=1, le=3650)
    max_length: int = Field(default=300, ge=1, le=2000)
    choices: tuple[str, ...] = Field(default=(), max_length=30)

    @field_validator("label", "purpose")
    @classmethod
    def no_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Labels and purposes may not be blank")
        return value.strip()

    @model_validator(mode="after")
    def field_rules(self) -> "SiteFormField":
        if self.key.startswith("_"):
            raise ValueError("Reserved field name")
        if self.sensitivity == "sensitive":
            raise ValueError("Sensitive fields need an explicit approved activation")
        if self.kind in {"select", "radio"}:
            if not self.choices or len(self.choices) != len(set(self.choices)):
                raise ValueError("Choice fields require distinct choices")
            if any(not choice.strip() or len(choice) > 120 for choice in self.choices):
                raise ValueError("Choices must be meaningful and short")
        elif self.choices:
            raise ValueError("Only choice controls may have choices")
        if self.kind == "consent" and not self.required:
            raise ValueError("The processing consent field must be required")
        return self


class SiteFormDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title: str = Field(min_length=1, max_length=180)
    submit_label: str = Field(default="Send enquiry", min_length=1, max_length=80)
    description: str = Field(default="", max_length=1000)
    privacy_notice: str = Field(min_length=10, max_length=1000)
    fields: tuple[SiteFormField, ...] = Field(min_length=2, max_length=30)

    @model_validator(mode="after")
    def shape(self) -> "SiteFormDocument":
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique")
        if not any(field.kind == "consent" for field in self.fields):
            raise ValueError("An explicit processing consent control is required")
        if not any(field.kind in {"email", "phone"} and field.required for field in self.fields):
            raise ValueError("Require at least one contact method")
        if any(field.key in {"_submission_key", "_version", "_website"} for field in self.fields):
            raise ValueError("Reserved transport field")
        return self


class FormCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    agent_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    document: SiteFormDocument


class FormUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    document: SiteFormDocument


class FormVersionGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


def validate_answers(
    document: SiteFormDocument,
    submitted: dict[str, str],
) -> tuple[dict[str, object], dict[str, str]]:
    """Server-authoritative field validation; never accept undeclared values."""
    allowed = {field.key for field in document.fields}
    errors: dict[str, str] = {}
    answers: dict[str, object] = {}
    for unexpected in submitted.keys() - allowed:
        errors[unexpected] = "Unknown form field"
    for field in document.fields:
        raw = submitted.get(field.key, "")
        if not isinstance(raw, str):
            errors[field.key] = "Invalid input"
            continue
        value = raw.strip()
        if field.kind in {"checkbox", "consent"}:
            checked = value.lower() in {"on", "yes", "true", "1"}
            if field.required and not checked:
                errors[field.key] = "This choice is required"
            answers[field.key] = checked
            continue
        if field.required and not value:
            errors[field.key] = "This field is required"
            continue
        if not value:
            answers[field.key] = ""
            continue
        if len(value) > field.max_length:
            errors[field.key] = "Value exceeds the allowed length"
            continue
        if field.kind == "email":
            try:
                value = str(EmailStr._validate(value))
            except (ValueError, TypeError):
                errors[field.key] = "Enter a valid email address"
                continue
        elif field.kind == "phone":
            import re

            if not re.fullmatch(r"\+?[0-9(). -]{7,32}", value) or sum(c.isdigit() for c in value) < 7:
                errors[field.key] = "Enter a valid international phone number"
                continue
        elif field.kind in {"select", "radio"} and value not in field.choices:
            errors[field.key] = "Choose an available option"
            continue
        elif field.kind == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors[field.key] = "Enter a valid date"
                continue
        answers[field.key] = value
    return answers, errors
