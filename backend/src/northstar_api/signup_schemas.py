from __future__ import annotations

from typing import Literal

from pydantic import EmailStr, Field, field_validator

from northstar_api.schemas import APIModel


class SignupRequest(APIModel):
    """Public self-service account creation contract.

    Email verification is intentionally a separate feature. This contract creates
    the initial customer account and requires explicit legal acceptance before
    any tenant data is provisioned.
    """

    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    organization_name: str = Field(min_length=2, max_length=160)
    terms_accepted: Literal[True]
    privacy_accepted: Literal[True]

    @field_validator("name", "organization_name")
    @classmethod
    def normalize_display_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("must contain at least two visible characters")
        return normalized
