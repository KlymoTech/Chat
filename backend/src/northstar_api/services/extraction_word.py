"""OOXML inventory plus a field-frozen, recorded Word rendering derivative."""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree

from northstar_api.services.extraction_checkpoint import read_zip

if TYPE_CHECKING:
    from northstar_api.config import Settings

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
W = "{" + NS["w"] + "}"
M = "{" + NS["m"] + "}"


def xml(data: bytes) -> Any:
    root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, recover=False))
    if root.getroottree().docinfo.doctype:
        raise ValueError("OOXML must not contain a document type declaration")
    return root


def _on(element: Any) -> bool:
    return element is not None and element.get(W + "val", "true").lower() not in {"0", "false", "off", "no"}


def visible_text(element: Any) -> str:
    values: list[str] = []
    for node in element.iter():
        ancestors = list(node.iterancestors())
        if any(parent.tag in {W + "del", W + "moveFrom"} for parent in ancestors):
            continue
        # Text boxes/nested paragraphs are separate logical blocks, not duplicate text in an outer paragraph.
        if element.tag == W + "p" and any(parent.tag == W + "p" and parent is not element for parent in ancestors):
            continue
        run = next((parent for parent in ancestors if parent.tag == W + "r"), None)
        if run is not None and _on(run.find("w:rPr/w:vanish", NS)):
            continue
        if node.tag in {W + "t", M + "t"}:
            values.append(node.text or "")
        elif node.tag == W + "tab":
            values.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            values.append("\n")
    return "".join(values)


def _table_cells(element: Any) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    active: dict[tuple[int, int], dict[str, Any]] = {}
    for row_number, row in enumerate(element.findall("w:tr", NS)):
        before = row.find("w:trPr/w:gridBefore", NS)
        column = int(before.get(W + "val", "0")) if before is not None else 0
        next_active: dict[tuple[int, int], dict[str, Any]] = {}
        for node in row.findall("w:tc", NS):
            span = node.find("w:tcPr/w:gridSpan", NS)
            width = int(span.get(W + "val", "1")) if span is not None else 1
            if not 0 <= column <= 10000 or not 1 <= width <= 1000:
                raise ValueError("Word table grid exceeds safe limits")
            merge = node.find("w:tcPr/w:vMerge", NS)
            merge_value = None if merge is None else merge.get(W + "val", "continue")
            key = (column, width)
            cell: dict[str, Any] = {"row": row_number, "column": column, "column_span": width,
                                    "row_span": 1, "vertical_merge": merge_value, "text": visible_text(node),
                                    "xml": etree.tostring(node, encoding="unicode"), "grid_before": column if not cells else None}
            if merge_value == "continue":
                owner = active.get(key)
                cell["state"] = "COVERED_BY_MERGE" if owner else "STRUCTURE_UNKNOWN"
                if owner:
                    owner["row_span"] += 1
                    cell["covered_by"] = {"row": owner["row"], "column": owner["column"]}
                    next_active[key] = owner
            else:
                cell["state"] = "VALUE" if cell["text"] else "BLANK"
                if merge_value == "restart":
                    next_active[key] = cell
            cells.append(cell)
            column += width
        active = next_active
    return cells


def inspect_word(data: bytes, settings: Settings) -> tuple[dict[str, Any], bytes]:
    content = read_zip(data, max_members=5000, max_expanded_bytes=settings.knowledge_max_docx_uncompressed_bytes,
                       allow_directories=True)
    if "word/document.xml" not in content:
        raise ValueError("DOCX has no main document")
    record: dict[str, Any] = {"parts": [], "blocks": [], "channels": [], "render_blockers": [],
                              "relationships": [], "field_policy": "freeze_cached_values",
                              "revision_view": "current_insertions_without_deletions"}
    for name, payload in sorted(content.items()):
        record["parts"].append({"name": name, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)})
        if "vbaproject" in name.lower() or name.startswith("word/embeddings/"):
            record["render_blockers"].append("Active or embedded document content")
        if name.endswith(".rels"):
            root = xml(payload)
            for relation in root:
                attrs = dict(relation.attrib)
                record["relationships"].append({"part": name, **attrs})
                if attrs.get("TargetMode") == "External" and not attrs.get("Type", "").endswith("/hyperlink"):
                    record["render_blockers"].append("External document dependency")
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        root = xml(payload)
        if name == "word/document.xml" and root.tag != W + "document":
            record["render_blockers"].append("Unsupported native OOXML namespace")
        if any(etree.QName(node).localname in {"altChunk", "OLEObject", "subDoc"} for node in root.iter() if isinstance(node.tag, str)):
            record["render_blockers"].append("External or active imported document content")
        # All logical parts are retained, including numbering/styles, revisions, notes and equations.
        for element in root.iter():
            if element.tag not in {W + "p", W + "tbl", M + "oMath"}:
                continue
            index = len(record["blocks"]) + 1
            if index > 100000:
                raise ValueError("Word source exceeds logical-block limit")
            kind = "table" if element.tag == W + "tbl" else "equation" if element.tag == M + "oMath" else "paragraph"
            ancestors = list(element.iterancestors())
            channel = "deleted" if any(parent.tag in {W + "del", W + "moveFrom"} for parent in ancestors) else "current"
            if name.startswith("word/comments"):
                channel = "comments"
            parent = next((node for node in ancestors if node.tag in {W + "p", W + "tbl"}), None)
            block: dict[str, Any] = {"id": f"W{index:06d}", "part": name, "type": kind, "channel": channel,
                                     "xpath": root.getroottree().getpath(element),
                                     "parent_xpath": root.getroottree().getpath(parent) if parent is not None else None,
                                     "text": visible_text(element), "xml": etree.tostring(element, encoding="unicode"),
                                     "rendered_pages": [], "mapping_status": "unmapped"}
            if kind == "table":
                block["cells"] = _table_cells(element)
            if kind == "paragraph":
                style = element.find("w:pPr/w:pStyle", NS)
                numbering = element.find("w:pPr/w:numPr", NS)
                block["style_id"] = style.get(W + "val") if style is not None else None
                block["numbering_xml"] = etree.tostring(numbering, encoding="unicode") if numbering is not None else None
                block["runs"] = [{"text": visible_text(run), "xml": etree.tostring(run, encoding="unicode"),
                                  "hidden": _on(run.find("w:rPr/w:vanish", NS))}
                                 for run in element.findall("w:r", NS)]
            record["blocks"].append(block)
        for channel, expression in {
            "deleted": ".//w:del", "moved_from": ".//w:moveFrom", "insertions": ".//w:ins",
            "hidden": ".//w:r[w:rPr/w:vanish]", "comments": ".//w:comment",
            "footnotes": ".//w:footnote", "endnotes": ".//w:endnote", "text_boxes": ".//w:txbxContent",
            "content_controls": ".//w:sdt", "native_equations": ".//m:oMath",
        }.items():
            for element in root.xpath(expression, namespaces=NS):
                record["channels"].append({"channel": channel, "part": name, "xpath": root.getroottree().getpath(element),
                                            "xml": etree.tostring(element, encoding="unicode")})
        # Freeze only the derivative. Preserve the original ZIP and XML in the evidence package.
        for tag in ("del", "moveFrom", "instrText", "fldChar"):
            for element in list(root.iter(W + tag)):
                if element.getparent() is not None:
                    element.getparent().remove(element)
        for element in list(root.iter(W + "fldSimple")):
            parent = element.getparent()
            position = parent.index(element)
            for child in list(element):
                parent.insert(position, child)
                position += 1
            parent.remove(element)
        for element in root.iter(W + "updateFields"):
            element.set(W + "val", "false")
        content[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    record["render_blockers"] = sorted(set(record["render_blockers"]))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return record, output.getvalue()


def render_word(derivative: bytes, settings: Settings) -> tuple[bytes, dict[str, Any]]:
    executable = shutil.which(settings.extraction_word_renderer)
    if not executable:
        raise ValueError("WORD_RENDERER_UNAVAILABLE")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="extraction-word-") as directory:
        root = Path(directory)
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>'
            '<item oor:path="/org.openoffice.Office.Writer/Content/Update">'
            '<prop oor:name="Link" oor:op="fuse"><value>2</value></prop></item></oor:items>', encoding="utf-8")
        source = root / "source.docx"
        source.write_bytes(derivative)
        renderer_version = subprocess.run([executable, "--version"], capture_output=True, timeout=15,
                                          check=True, creationflags=flags).stdout.decode(errors="replace").strip()  # noqa: S603
        subprocess.run([executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
                        "--nodefault", "--norestore", "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(root), str(source)],
                       capture_output=True, check=True, timeout=settings.extraction_word_timeout_seconds,
                       creationflags=flags, env={**os.environ, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SAL_DISABLE_OPENCL": "1"})  # noqa: S603
        pdf = root / "source.pdf"
        if not pdf.exists() or pdf.stat().st_size > settings.upload_max_bytes:
            raise ValueError("WORD_RENDER_FAILED")
        font_list = "NOT_AVAILABLE"
        if fonts := shutil.which("fc-list"):
            font_list = subprocess.run([fonts], capture_output=True, check=True, timeout=15,
                                       creationflags=flags).stdout.decode(errors="replace")  # noqa: S603
        return pdf.read_bytes(), {"version": renderer_version, "locale": "C.UTF-8", "fonts": font_list,
                                  "fonts_sha256": hashlib.sha256(font_list.encode()).hexdigest(),
                                  "field_policy": "freeze_cached_values", "revision_view": "current",
                                  "derivative_sha256": hashlib.sha256(derivative).hexdigest()}
