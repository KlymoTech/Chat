"""Chapter 20: immutable form contracts and server-authoritative field checks."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from northstar_api.services.website_form_contracts import SiteFormDocument, validate_answers


def document() -> SiteFormDocument:
    return SiteFormDocument.model_validate({
        "title": "Contact us",
        "submit_label": "Send enquiry",
        "privacy_notice": "We will use your details solely to respond to this enquiry.",
        "fields": [
            {"key":"name", "label":"Your name", "kind":"text", "required":True,
             "purpose":"Respond to the enquiry", "max_length":150},
            {"key":"email", "label":"Email", "kind":"email", "required":True,
             "purpose":"Reply to your enquiry"},
            {"key":"topic", "label":"Topic", "kind":"select", "required":True,
             "choices":["Sales", "Support"], "purpose":"Route the enquiry"},
            {"key":"date", "label":"Preferred date", "kind":"date",
             "purpose":"Suggest a contact time"},
            {"key":"processing_consent", "label":"I consent", "kind":"consent", "required":True,
             "purpose":"Process this enquiry"},
        ],
    })


def test_unicode_names_normalization_and_pinned_choices():
    values, errors = validate_answers(document(), {
        "name": "  山田 花子  ", "email": " Test@Example.org ",
        "topic": "Sales", "date": "2026-11-05", "processing_consent": "on",
    })
    assert errors == {}
    assert values["name"] == "山田 花子"
    assert values["email"].lower() == "test@example.org"
    assert values["processing_consent"] is True
    assert values["date"] == "2026-11-05"


def test_unknown_fields_missing_permission_invalid_phone_and_choices_are_rejected():
    answers, errors = validate_answers(document(), {
        "name": "Jane", "email": "not-email", "topic": "Unknown",
        "unexpected": "<script>", "processing_consent": "",
    })
    assert answers["consent"] is False
    assert "email" in errors
    assert "topic" in errors
    assert "processing_consent" in errors
    assert "unexpected" in errors
    _, date_errors = validate_answers(document(), {
        "name": "Jane", "email": "jane@example.com", "topic": "Sales",
        "date": "2026-W01-1", "processing_consent": "on",
    })
    assert "date" in date_errors


@pytest.mark.parametrize("patch", [
    {"fields":[{"key":"email", "label":"Email", "kind":"email", "required":True,
                "purpose":"Respond"}]},
    {"privacy_notice":"short"},
    {"fields":[
        {"key":"email", "label":"Email", "kind":"email", "required":True,
         "purpose":"Reply to enquiry"},
        {"key":"email", "label":"Consent", "kind":"consent", "required":True,
         "purpose":"Process enquiry"},
    ]},
    {"fields":[
        {"key":"email", "label":"Email", "kind":"email", "required":True,
         "purpose":"Reply to enquiry"},
        {"key":"processing_consent", "label":"Consent", "kind":"consent", "required":False,
         "purpose":"Process enquiry"},
    ]},
])
def test_invalid_form_contracts_are_rejected(patch):
    original = document().model_dump(mode="json")
    original.update(patch)
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(original)


def test_sensitive_and_unbounded_upload_types_are_not_silently_activated():
    base = document().model_dump(mode="json")
    base["fields"][0]["sensitivity"] = "sensitive"
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(base)
    base["fields"][0]["sensitivity"] = "personal"
    base["fields"][0]["kind"] = "file"
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(base)


def test_processing_consent_must_have_dedicated_key():
    form = document().model_dump(mode="json")
    for field in form["fields"]:
        if field["kind"] == "consent":
            field["key"] = "marketing_consent"
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)


def _conditional_document() -> SiteFormDocument:
    form = document().model_dump(mode="json")
    form["steps"] = ["About you", "Request details", "Permission"]
    for item in form["fields"]:
        if item["key"] == "name":
            item["step"] = 1
        elif item["key"] == "email":
            item["step"] = 1
        elif item["key"] == "topic":
            item["step"] = 1
        elif item["key"] == "date":
            item["step"] = 2
            item["required"] = True
            item["condition"] = {"field_key": "topic", "equals": "Support"}
        else:
            item["step"] = 3
    return SiteFormDocument.model_validate(form)


def test_multistep_conditional_controls_only_validate_visible_purpose_fields():
    form = _conditional_document()
    assert form.steps == ("About you", "Request details", "Permission")
    values, errors = validate_answers(form, {
        "name": "Morgan", "email": "morgan@example.com",
        "topic": "Sales", "processing_consent": "on",
    })
    assert not errors
    assert "date" not in values
    assert values["processing_consent"] is True

    _, required_errors = validate_answers(form, {
        "name": "Morgan", "email": "morgan@example.com",
        "topic": "Support", "processing_consent": "on",
    })
    assert required_errors["date"] == "This field is required"

    _, tamper_errors = validate_answers(form, {
        "name": "Morgan", "email": "morgan@example.com",
        "topic": "Sales", "date": "2026-11-05",
        "processing_consent": "on",
    })
    assert tamper_errors["date"] == "This field is not available for the selected choice"


def test_multistep_unsafe_conditions_and_forward_references_are_rejected():
    form = _conditional_document().model_dump(mode="json")
    form["fields"][0]["condition"] = {"field_key": "topic", "equals": "Support"}
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)

    form = _conditional_document().model_dump(mode="json")
    form["fields"][1]["condition"] = {"field_key": "topic", "equals": "Support"}
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)

    form = _conditional_document().model_dump(mode="json")
    form["fields"][3]["condition"]["equals"] = "Not an available choice"
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)

    form = _conditional_document().model_dump(mode="json")
    form["fields"][3]["step"] = 1
    form["fields"][1]["step"] = 3
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)


def test_multistep_schema_rejects_blank_steps_and_undefined_step_numbers():
    form = _conditional_document().model_dump(mode="json")
    form["steps"][1] = " "
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)
    form = _conditional_document().model_dump(mode="json")
    form["fields"][-1]["step"] = 4
    with pytest.raises(ValidationError):
        SiteFormDocument.model_validate(form)
