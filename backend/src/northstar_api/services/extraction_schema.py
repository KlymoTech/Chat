"""Parser-independent records and bounded, non-coercing vision contracts."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockKind = Literal[
    "heading", "paragraph", "list", "table", "equation", "question", "answer_key",
    "figure", "caption", "footnote", "header", "footer", "annotation", "unknown",
]
POLICY_VERSION = "source-fidelity-2026-09-17"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def strict_json(raw: str) -> Any:
    """Reject duplicate keys and non-JSON constants instead of choosing a value."""
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> Any:
        raise ValueError("Non-finite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class RegionProposal(StrictModel):
    kind: BlockKind
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid_box(self) -> RegionProposal:
        x0, y0, x1, y1 = self.bbox
        if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
            raise ValueError("Region coordinates must be ordered within 0..1000")
        return self


class Inventory(StrictModel):
    regions: list[RegionProposal] = Field(max_length=64)
    complete: bool
    blank: bool = False
    printed_page_label: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def nonempty(self) -> Inventory:
        if self.blank == bool(self.regions):
            raise ValueError("A nonblank page needs regions; a blank page cannot have regions")
        return self


class Cell(StrictModel):
    row: int = Field(ge=0, le=1000)
    column: int = Field(ge=0, le=1000)
    row_span: int = Field(default=1, ge=1, le=1000)
    column_span: int = Field(default=1, ge=1, le=1000)
    text: str = Field(max_length=20000)
    state: Literal["VALUE", "BLANK", "UNREADABLE", "AMBIGUOUS", "COVERED_BY_MERGE", "STRUCTURE_UNKNOWN"] = "VALUE"
    header: bool = False
    header_refs: list[str] = Field(default_factory=list, max_length=100)
    unit: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_state(self) -> Cell:
        if self.state == "VALUE" and self.text == "":
            raise ValueError("Empty cells require an explicit BLANK or uncertainty state")
        if self.state in {"BLANK", "COVERED_BY_MERGE"} and self.text:
            raise ValueError("Blank or covered positions cannot contain values")
        if self.state == "COVERED_BY_MERGE" and (
            self.row_span != 1 or self.column_span != 1 or self.header or self.header_refs or self.unit
        ):
            raise ValueError("Covered positions cannot define another span, header or unit")
        return self


class QuestionOption(StrictModel):
    label: str = Field(max_length=200)
    text: str = Field(max_length=20000)


class Reading(StrictModel):
    kind: BlockKind
    text: str = Field(max_length=200000)
    complete: bool
    blank: bool = False
    uncertain: bool = False
    cells: list[Cell] = Field(default_factory=list, max_length=1000)
    table_row_count: int | None = Field(default=None, ge=1, le=1001)
    table_column_count: int | None = Field(default=None, ge=1, le=1001)
    latex: str | None = Field(default=None, max_length=200000)
    heading_level: int | None = Field(default=None, ge=1, le=9)
    printed_label: str | None = Field(default=None, max_length=1000)
    printed_caption: str | None = Field(default=None, max_length=20000)
    figure_labels: list[str] = Field(default_factory=list, max_length=100)
    handwritten_annotation: str | None = Field(default=None, max_length=20000)
    observed_relationships: list[str] = Field(default_factory=list, max_length=100)
    derived_description: str | None = Field(default=None, max_length=20000)
    option_labels: list[str] = Field(default_factory=list, max_length=100)
    options: list[QuestionOption] = Field(default_factory=list, max_length=100)
    printed_answer: str | None = Field(default=None, max_length=20000)
    continues_from_previous: bool = False
    continues_on_next: bool = False

    @model_validator(mode="after")
    def meaningful(self) -> Reading:
        if self.blank and (self.text or self.cells or self.figure_labels or self.latex or self.options):
            raise ValueError("Blank regions cannot contain extracted values")
        if not self.blank and not (self.text or self.cells or self.figure_labels or self.kind == "figure" or self.latex):
            raise ValueError("Nonblank reading needs source content")
        if self.kind != "table" and (self.cells or self.table_row_count or self.table_column_count):
            raise ValueError("Table content cannot be relabelled as an ordinary paragraph")
        if self.options and [option.label for option in self.options] != self.option_labels:
            raise ValueError("Option labels must preserve the exact supplied option sequence")
        return self


ResponseModel = TypeVar("ResponseModel", Inventory, Reading)


def parse_response(raw: Any, schema: type[ResponseModel]) -> ResponseModel:
    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise ValueError("Expected a bounded JSON text response")
    value = raw.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    # JSON-mode validation allows a JSON array for a tuple without coercing booleans/numbers.
    strict_json(value)
    return schema.model_validate_json(value)
