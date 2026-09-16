"""Bounded source contracts. Valid shape is not proof of faithful transcription."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockKind = Literal[
    "heading", "paragraph", "list", "table", "equation", "question", "answer_key",
    "figure", "caption", "footnote", "header", "footer", "annotation", "unknown",
]


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def strict_json(raw: str | bytes, *, max_bytes: int = 4_000_000) -> Any:
    if len(raw.encode("utf-8") if isinstance(raw, str) else raw) > max_bytes:
        raise ValueError("JSON response exceeds the configured evidence limit")
    def invalid_constant(_: str) -> None:
        raise ValueError("Non-finite JSON numbers are not allowed")
    return json.loads(raw, object_pairs_hook=_unique_keys, parse_constant=invalid_constant)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RegionProposal(StrictModel):
    kind: BlockKind
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid_box(self) -> RegionProposal:
        x0, y0, x1, y1 = self.bbox
        if not all(math.isfinite(v) for v in self.bbox) or not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
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
    unit: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def consistent(self) -> Cell:
        if self.state in {"BLANK", "COVERED_BY_MERGE"} and self.text:
            raise ValueError("Blank and covered positions cannot contain source values")
        if self.state == "COVERED_BY_MERGE" and (self.row_span != 1 or self.column_span != 1 or self.header):
            raise ValueError("A covered position is not another spanning/header cell")
        if self.row_span * self.column_span > 10000:
            raise ValueError("Cell span exceeds safe grid size")
        if len(self.header_refs) != len(set(self.header_refs)):
            raise ValueError("Duplicate header associations")
        return self


class SourceOption(StrictModel):
    label: str = Field(max_length=200)
    text: str = Field(max_length=20000)


class Reading(StrictModel):
    kind: BlockKind
    text: str = Field(max_length=200000)
    complete: bool
    blank: bool = False
    uncertain: bool = False
    cells: list[Cell] = Field(default_factory=list, max_length=1000)
    latex: str | None = Field(default=None, max_length=100000)
    printed_label: str | None = Field(default=None, max_length=2000)
    printed_caption: str | None = Field(default=None, max_length=20000)
    figure_labels: list[str] = Field(default_factory=list, max_length=100)
    handwritten_annotation: str | None = Field(default=None, max_length=20000)
    observed_relationships: list[str] = Field(default_factory=list, max_length=100)
    derived_description: str | None = Field(default=None, max_length=20000)
    option_labels: list[str] = Field(default_factory=list, max_length=100)
    options: list[SourceOption] = Field(default_factory=list, max_length=100)
    subparts: list[SourceOption] = Field(default_factory=list, max_length=100)
    printed_answer: str | None = Field(default=None, max_length=20000)
    instructions: str | None = Field(default=None, max_length=20000)
    marks: str | None = Field(default=None, max_length=1000)
    units: list[str] = Field(default_factory=list, max_length=100)
    source_logical_ids: list[str] = Field(default_factory=list, max_length=100)
    continues_from_previous: bool = False
    continues_on_next: bool = False

    @model_validator(mode="after")
    def meaningful(self) -> Reading:
        if self.blank and (self.text or self.cells or self.figure_labels or self.options or self.printed_answer):
            raise ValueError("Blank regions cannot contain extracted values")
        if not self.blank and not (self.text or self.cells or self.figure_labels or self.kind == "figure"):
            raise ValueError("Nonblank reading needs source content")
        if self.options and self.option_labels != [o.label for o in self.options]:
            raise ValueError("Option labels must preserve the full ordered options")
        if self.kind != "table" and self.cells:
            raise ValueError("Table cells must belong to a table region")
        return self


def parse_response(raw: Any, schema: type[Inventory] | type[Reading]) -> Inventory | Reading:
    if not isinstance(raw, str):
        raise ValueError("Expected a JSON text response")
    value = raw.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    elif value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
    return schema.model_validate(strict_json(value))
