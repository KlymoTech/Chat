"""Generated gold documents with exact ground truth.

Every document is drawn here, so its text, block positions and table cells are known exactly.
Nothing binary is stored in the repository, and the set covers the layouts that break
extraction: signs and units, ruled / striped / whitespace tables, white-on-dark headers, two
columns, a raster chart, a callout box, multiple pages, and scanned (image-only) copies.
"""

from __future__ import annotations

import io
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import fitz  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 595.0, 842.0  # A4 in points
MARGIN = 50.0
DARK = (0.19, 0.37, 0.28)
STRIPE = (0.95, 0.96, 0.96)


@dataclass
class GoldPage:
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GoldDocument:
    name: str
    description: str
    pdf: bytes
    pages: list[GoldPage]
    scanned: bool = False

    def truth(self) -> dict[str, Any]:
        return {"name": self.name, "pages": [{"number": i + 1, "blocks": p.blocks} for i, p in enumerate(self.pages)]}


class _Writer:
    """Draws on a page and records each block's ground truth as it goes."""

    def __init__(self, page: fitz.Page, truth: GoldPage) -> None:
        self.page, self.truth, self.y = page, truth, MARGIN

    def text(self, text: str, *, size: float = 10.5, bold: bool = False, kind: str = "paragraph",
             left: float = MARGIN, right: float = WIDTH - MARGIN, gap: float = 10.0,
             color: tuple[float, float, float] = (0.1, 0.1, 0.1)) -> None:
        font = "hebo" if bold else "helv"
        lines = self._wrap(text, font, size, right - left)
        height = len(lines) * size * 1.3
        for index, line in enumerate(lines):
            self.page.insert_text((left, self.y + size + index * size * 1.3), line, fontsize=size, fontname=font, color=color)
        self.truth.blocks.append({"kind": kind, "text": text, "bbox_pt": [left, self.y, right, self.y + height]})
        self.y += height + gap

    @staticmethod
    def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
        lines, current = [], ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            if current and fitz.get_text_length(candidate, fontname=font, fontsize=size) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        return [*lines, current] if current else lines

    def table(self, rows: list[list[str]], *, style: str, numeric: set[int] | None = None, size: float = 9.5,
              widths: list[float] | None = None, left_headers: bool = False) -> None:
        numeric = numeric or set()
        left, right = MARGIN, WIDTH - MARGIN
        if widths is None:
            widths = [max(fitz.get_text_length(r[c], fontname="hebo", fontsize=size) for r in rows) + 24 for c in range(len(rows[0]))]
        scale = (right - left) / sum(widths)
        widths = [w * scale for w in widths]
        row_height = size * 2.4
        top = self.y
        for r, row in enumerate(rows):
            y0 = top + r * row_height
            rect = fitz.Rect(left, y0, right, y0 + row_height)
            header = r == 0
            if style == "striped":
                if header:
                    self.page.draw_rect(rect, color=None, fill=DARK)
                elif r % 2 == 1:
                    self.page.draw_rect(rect, color=None, fill=STRIPE)
            x = left
            for c, value in enumerate(row):
                font = "hebo" if header else "helv"
                color = (1, 1, 1) if header and style == "striped" else (0.1, 0.1, 0.1)
                length = fitz.get_text_length(value, fontname=font, fontsize=size)
                right_aligned = c in numeric and not (header and left_headers)
                tx = x + widths[c] - 10 - length if right_aligned else x + 8
                self.page.insert_text((tx, y0 + row_height * 0.65), value, fontsize=size, fontname=font, color=color)
                x += widths[c]
        bottom = top + len(rows) * row_height
        if style == "ruled":
            for r in range(len(rows) + 1):
                self.page.draw_line((left, top + r * row_height), (right, top + r * row_height), color=(0.4, 0.4, 0.4), width=0.6)
            x = left
            for w in [0.0, *widths]:
                x += w
                self.page.draw_line((x, top), (x, bottom), color=(0.4, 0.4, 0.4), width=0.6)
        self.truth.blocks.append({
            "kind": "table",
            "text": "\n".join(" | ".join(row) for row in rows),
            "bbox_pt": [left, top, right, bottom],
            "rows": rows,
        })
        self.y = bottom + 14

    def callout(self, title: str, body: str) -> None:
        top = self.y
        lines = self._wrap(body, "helv", 9.5, WIDTH - 2 * MARGIN - 28)
        height = 22 + len(lines) * 9.5 * 1.3 + 12
        self.page.draw_rect(fitz.Rect(MARGIN, top, WIDTH - MARGIN, top + height), color=None, fill=(0.92, 0.95, 0.92))
        self.page.draw_rect(fitz.Rect(MARGIN, top, MARGIN + 4, top + height), color=None, fill=DARK)
        self.y = top + 8
        self.text(title, size=10.5, bold=True, left=MARGIN + 14, right=WIDTH - MARGIN - 14, gap=2)
        self.text(body, size=9.5, left=MARGIN + 14, right=WIDTH - MARGIN - 14, gap=0)
        self.y = top + height + 14

    def chart(self, title: str, values: dict[str, int], caption: str) -> None:
        """A raster bar chart: its labels exist only as pixels (no text layer)."""
        width_px, height_px = 900, 420
        image = Image.new("RGB", (width_px, height_px), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=26)
        draw.text((30, 12), title, fill="black", font=font)
        top = max(values.values())
        for i, (label, value) in enumerate(values.items()):
            x0 = 90 + i * 200
            bar_top = 380 - int(290 * value / top)
            draw.rectangle((x0, bar_top, x0 + 110, 380), fill=(70, 130, 180))
            draw.text((x0 + 30, bar_top - 34), str(value), fill="black", font=font)
            draw.text((x0 + 10, 385), label, fill="black", font=font)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        rect = fitz.Rect(MARGIN, self.y, WIDTH - MARGIN, self.y + (WIDTH - 2 * MARGIN) * height_px / width_px)
        self.page.insert_image(rect, stream=buffer.getvalue())
        labels = " ".join([title, *[f"{v} {k}" for k, v in values.items()]])
        self.truth.blocks.append({"kind": "figure", "text": labels, "bbox_pt": [rect.x0, rect.y0, rect.x1, rect.y1]})
        self.y = rect.y1 + 6
        self.text(caption, size=8.5, kind="caption")


def _document(name: str, description: str, draw: Callable[[fitz.Document, list[GoldPage]], None]) -> GoldDocument:
    pdf = fitz.open()
    pages: list[GoldPage] = []
    draw(pdf, pages)
    data = pdf.tobytes(deflate=True)
    pdf.close()
    return GoldDocument(name, description, data, pages)


def _new_page(pdf: fitz.Document, pages: list[GoldPage]) -> _Writer:
    truth = GoldPage()
    pages.append(truth)
    return _Writer(pdf.new_page(width=WIDTH, height=HEIGHT), truth)


def _report(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Quarterly water balance", size=20, bold=True, kind="heading", color=DARK)
    w.text("Site RIV-07 recorded an inflow of 12,480.5 m³ and an outflow of 12,993.25 m³, a net change of "
           "-512.75 m³ (-4.1%). Pump efficiency fell from 81.2% to 78.9% while ambient temperature averaged 23.4 °C.")
    w.text("1. Method", size=13, bold=True, kind="heading")
    w.text("Flows are measured at the inlet weir and the outlet flume every 15 minutes. A reading is rejected when the "
           "sensor reports a value NOT between 0 and 950 L/s, or when two consecutive readings differ by more than 35%.")
    w.text("Losses are estimated as evaporation (2.6 mm/day × 1,850 m²) plus seepage (0.4 L/s). Neither estimate "
           "includes rainfall, which is recorded separately.")
    w = _new_page(pdf, pages)
    w.text("2. Results", size=13, bold=True, kind="heading")
    w.text("Week 3 had the largest deficit (-221.0 m³). Weeks 1, 2 and 4 were within the ±5% tolerance, so only "
           "week 3 is escalated. The total remains below the 600 m³ alert level.")
    w.text("Prepared for internal testing only. Values are synthetic.", size=8.5, kind="footer")


def _ruled_table(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Laboratory results", size=18, bold=True, kind="heading")
    w.text("Each sample was measured twice; the mean is reported to two decimals.")
    w.table([
        ["Sample", "pH", "Nitrate (mg/L)", "Phosphate (mg/L)", "Status"],
        ["S-101", "7.12", "3.40", "0.08", "PASS"],
        ["S-102", "6.85", "11.25", "0.31", "REVIEW"],
        ["S-103", "7.40", "0.95", "0.02", "PASS"],
        ["S-104", "5.98", "14.70", "0.44", "FAIL"],
        ["Mean", "6.84", "7.58", "0.21", "-"],
    ], style="ruled", numeric={1, 2, 3})
    w.text("REVIEW means one limit was exceeded by less than 10%; FAIL means any limit was exceeded by 10% or more.")


def _striped_table(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Crop allocation", size=18, bold=True, kind="heading", color=DARK)
    w.text("Daily allocations are fixed for the case; every zone receives its volume on each of seven days.")
    w.table([
        ["Zone", "Crop", "Area (m²)", "Plants", "Water (L/day)"],
        ["A1", "Tomato", "240", "480", "960"],
        ["A2", "Cucumber", "200", "400", "800"],
        ["A3", "Lettuce", "160", "800", "480"],
        ["Total", "All crops", "600", "1,680", "2,240"],
    ], style="striped", numeric={2, 3, 4})
    w.text("Week 4 water supplied: 2,240 L/day × 7 days = 15,680 L.")


def _wide_table(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    """Wide columns: headers left-aligned at the column start, numbers right-aligned at its end, so a
    header never overlaps its own values (the layout of the real agriculture test file)."""
    w = _new_page(pdf, pages)
    w.text("Crop allocation and daily water record", size=13, bold=True, kind="heading", color=DARK)
    w.table([
        ["Zone", "Crop", "Area (m²)", "Plants", "Water (L/day)"],
        ["A1", "Tomato", "240", "480", "960"],
        ["A2", "Cucumber", "200", "400", "800"],
        ["A3", "Lettuce", "160", "800", "480"],
        ["Total", "All crops", "600", "1,680", "2,240"],
    ], style="striped", numeric={2, 3, 4}, widths=[1.0, 2.2, 3.0, 3.2, 3.4], left_headers=True)
    w.text("Each zone receives its listed volume on each of the seven days in week 4.")


def _whitespace_table(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Shift roster", size=18, bold=True, kind="heading")
    w.text("Columns are aligned with spacing only; there are no lines or shading.")
    w.table([
        ["Name", "Role", "Start", "End", "Hours"],
        ["Asha Rao", "Operator", "06:00", "14:00", "8.0"],
        ["Ben Ortiz", "Technician", "14:00", "22:30", "8.5"],
        ["Chen Wei", "Supervisor", "22:00", "06:00", "8.0"],
    ], style="plain", numeric={4})


def _two_column(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Field notes: north and south plots", size=18, bold=True, kind="heading")
    top = w.y
    middle = WIDTH / 2
    w.text("North plot. Soil moisture stayed between 21% and 27% for the whole week. Two irrigation cycles were "
           "skipped after 14 mm of rain on Tuesday. Leaf samples showed no sign of blight.", right=middle - 12)
    w.text("Action: keep the current schedule and re-test on day 10.", right=middle - 12)
    w.y = top
    w.text("South plot. Moisture dropped to 16% on Thursday because a valve stuck closed for 9 hours. The valve was "
           "replaced and moisture recovered to 22% by Saturday.", left=middle + 12)
    w.text("Action: inspect the remaining 6 valves before the next cycle.", left=middle + 12)


def _mixed(pdf: fitz.Document, pages: list[GoldPage]) -> None:
    w = _new_page(pdf, pages)
    w.text("Harvest summary", size=18, bold=True, kind="heading", color=DARK)
    w.text("Saleable harvest grew in three of four weeks. The chart below is an embedded image, so its labels are "
           "readable only from pixels.")
    w.chart("Saleable harvest (kg)", {"Week 1": 220, "Week 2": 245, "Week 3": 238, "Week 4": 270},
            "Figure 1. Weekly saleable harvest across all zones.")
    w.callout("Record boundary", "Figures exclude produce rejected at grading (15 kg in week 4). Do not infer prices "
                                 "or yields per plant from this chart.")
    w.text("Saleable share in week 4: 270 / 285 × 100 = 94.74%.")


def _scanned(source: GoldDocument, dpi: int = 200, seed: int = 7) -> GoldDocument:
    """An image-only copy with light noise and blur, as a scanner would produce: no text layer."""
    rng = random.Random(seed)  # noqa: S311 - deterministic test noise, not security
    original = fitz.open(stream=source.pdf, filetype="pdf")
    scanned = fitz.open()
    for page in original:
        pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)
        noisy = image.point(lambda v: max(0, min(255, v + rng.randint(-18, 18)))).filter(ImageFilter.GaussianBlur(0.6))
        buffer = io.BytesIO()
        noisy.save(buffer, format="PNG")
        target = scanned.new_page(width=page.rect.width, height=page.rect.height)
        target.insert_image(target.rect, stream=buffer.getvalue())
    data = scanned.tobytes(deflate=True)
    original.close()
    scanned.close()
    return GoldDocument(f"{source.name}-scanned", f"Image-only scan of {source.name}", data, source.pages, scanned=True)


def gold_documents(include_scanned: bool = True) -> list[GoldDocument]:
    documents = [
        _document("report-multipage", "Two-page report with signs, decimals, units and ±/×/°", _report),
        _document("table-ruled", "Table with full grid lines and right-aligned numbers", _ruled_table),
        _document("table-striped", "Striped table, white-on-dark header, no grid lines", _striped_table),
        _document("table-whitespace", "Table aligned by spacing only", _whitespace_table),
        _document("table-wide-columns", "Wide columns: left-aligned headers over right-aligned numbers", _wide_table),
        _document("two-column", "Heading over two text columns", _two_column),
        _document("mixed-figure", "Raster chart, caption and a shaded callout box", _mixed),
    ]
    if include_scanned:
        documents += [_scanned(documents[0]), _scanned(documents[2])]
    return documents
