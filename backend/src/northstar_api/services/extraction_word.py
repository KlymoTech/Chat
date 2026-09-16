"""Source-preserving OOXML traversal and a frozen, recorded rendering derivative."""
from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlsplit

from lxml import etree

from northstar_api.services.extraction_evidence import deterministic_zip, read_zip, sha256

if TYPE_CHECKING:
    from northstar_api.config import Settings

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
W, M = "{" + NS["w"] + "}", "{" + NS["m"] + "}"


def xml(data: bytes) -> Any:
    root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False))
    if root.getroottree().docinfo.doctype:
        raise ValueError("OOXML must not contain a document type declaration")
    return root


def _on(element: Any) -> bool:
    return element is not None and element.get(W + "val", "true").lower() not in {"false", "0", "off"}


def _excluded(node: Any) -> bool:
    for ancestor in (node, *node.iterancestors()):
        if ancestor.tag in {W + "del", W + "moveFrom"}:
            return True
        if ancestor.tag == W + "r" and _on(ancestor.find("w:rPr/w:vanish", NS)):
            return True
    return False


def visible_text(element: Any) -> str:
    values: list[str] = []
    for node in element.iter():
        if _excluded(node):
            continue
        if node.tag in {W + "t", M + "t"}:
            values.append(node.text or "")
        elif node.tag == W + "tab":
            values.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            values.append("\n")
        elif node.tag == W + "noBreakHyphen":
            values.append("\u2011")
        elif node.tag == W + "softHyphen":
            values.append("\u00ad")
    return "".join(values)


def _table(element: Any) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    active_merges: dict[tuple[int, int], dict[str, Any]] = {}
    errors: list[str] = []
    for row_index, row in enumerate(element.findall("w:tr", NS)):
        before = row.find("w:trPr/w:gridBefore", NS)
        column = int(before.get(W + "val", "0")) if before is not None else 0
        next_merges: dict[tuple[int, int], dict[str, Any]] = {}
        for cell in row.findall("w:tc", NS):
            span = cell.find("w:tcPr/w:gridSpan", NS)
            count = int(span.get(W + "val", "1")) if span is not None else 1
            if count < 1 or count > 1000 or column + count > 1000:
                raise ValueError("DOCX table span exceeds safe limits")
            merge = cell.find("w:tcPr/w:vMerge", NS)
            merge_value = merge.get(W + "val", "continue") if merge is not None else None
            value = visible_text(cell)
            item = {"row": row_index, "column": column, "row_span": 1, "column_span": count,
                    "text": value, "state": "VALUE" if value else "BLANK",
                    "vertical_merge": merge_value, "source_xpath": cell.getroottree().getpath(cell),
                    "nested_table_xpaths": [c.getroottree().getpath(c) for c in cell.findall("w:tbl", NS)]}
            key = column, count
            if merge_value == "continue":
                anchor = active_merges.get(key)
                if anchor is None:
                    item["state"] = "STRUCTURE_UNKNOWN"
                    errors.append("Vertical merge continuation has no anchor")
                else:
                    anchor["row_span"] += 1
                    item.update(state="COVERED_BY_MERGE", anchor=[anchor["row"], anchor["column"]], raw_text=value, text="")
                    if value:
                        errors.append("Merged continuation contains separately visible candidate text")
                    next_merges[key] = anchor
            elif merge_value == "restart":
                next_merges[key] = item
            cells.append(item)
            column += count
        active_merges = next_merges
    return {"cells": cells, "grid_columns": len(element.findall("w:tblGrid/w:gridCol", NS)), "structure_issues": errors}


def inspect_word(data: bytes, settings: Settings) -> tuple[dict[str, Any], bytes]:
    content = read_zip(data, max_bytes=settings.knowledge_max_docx_uncompressed_bytes)
    if "word/document.xml" not in content or "[Content_Types].xml" not in content:
        raise ValueError("DOCX has no valid main document/content-type inventory")
    record: dict[str, Any] = {"parts": [], "blocks": [], "channels": [], "render_blockers": [],
        "relationships": [], "field_policy": "freeze_cached_values",
        "revision_view": "current_insertions_without_deletions", "original_sha256": sha256(data)}
    for name, payload in sorted(content.items()):
        record["parts"].append({"name": name, "sha256": sha256(payload), "size": len(payload)})
        if "vbaproject" in name.lower() or name.startswith("word/embeddings/") or name.startswith("word/activeX/"):
            record["render_blockers"].append("ACTIVE_OR_EMBEDDED_DOCUMENT_CONTENT")
        if not name.endswith((".xml", ".rels")):
            continue
        root = xml(payload)
        if name.endswith(".rels"):
            base = name.rsplit("/_rels/", 1)[0] if "/_rels/" in name else ""
            for relation in root:
                attrs = dict(relation.attrib)
                record["relationships"].append({"part": name, **attrs})
                target = unquote(attrs.get("Target", ""))
                if attrs.get("TargetMode") == "External":
                    if not attrs.get("Type", "").endswith("/hyperlink"):
                        record["render_blockers"].append("EXTERNAL_DOCUMENT_DEPENDENCY")
                else:
                    parsed = urlsplit(target)
                    resolved = posixpath.normpath(posixpath.join(base, parsed.path))
                    if parsed.scheme or parsed.netloc or resolved.startswith(("/", "../")) or "\\" in target or "\x00" in target:
                        raise ValueError("Unsafe internal OOXML relationship")
                    if resolved not in content:
                        record["render_blockers"].append("MISSING_INTERNAL_DOCUMENT_DEPENDENCY")
            continue
        if not name.startswith("word/"):
            continue
        if root.findall(".//w:altChunk", NS):
            record["render_blockers"].append("UNSUPPORTED_EMBEDDED_ALTCHUNK")
        by_xpath: dict[str, str] = {}
        for element in root.iter():
            if element.tag not in {W + "p", W + "tbl", M + "oMath"}:
                continue
            kind = "table" if element.tag == W + "tbl" else "equation" if element.tag == M + "oMath" else "paragraph"
            xpath = root.getroottree().getpath(element)
            parent_id = next((by_xpath.get(root.getroottree().getpath(parent)) for parent in element.iterancestors()
                              if root.getroottree().getpath(parent) in by_xpath), None)
            identity = "W" + sha256((name + ":" + xpath).encode())[:16]
            by_xpath[xpath] = identity
            block: dict[str, Any] = {"id": identity, "part": name, "type": kind,
                "parent_id": parent_id, "xpath": xpath, "text": visible_text(element),
                "xml": etree.tostring(element, encoding="unicode"), "rendered_pages": [], "mapping_status": "unmapped",
                "channel": "excluded_revision_or_hidden" if _excluded(element) else "visible_candidate"}
            if kind == "table":
                block.update(_table(element))
            elif kind == "paragraph":
                block["runs"] = [{"text": visible_text(run), "excluded": _excluded(run),
                                  "properties_xml": etree.tostring(run.find("w:rPr", NS), encoding="unicode") if run.find("w:rPr", NS) is not None else None,
                                  "xml": etree.tostring(run, encoding="unicode")}
                                 for run in element.iter(W + "r")]
                properties = element.find("w:pPr", NS)
                block["paragraph_properties_xml"] = etree.tostring(properties, encoding="unicode") if properties is not None else None
                style = element.find("w:pPr/w:pStyle", NS)
                block["style_id"] = style.get(W + "val") if style is not None else None
                number = element.find("w:pPr/w:numPr", NS)
                block["numbering_xml"] = etree.tostring(number, encoding="unicode") if number is not None else None
            record["blocks"].append(block)
        channels = {"deleted": ".//w:del", "moved_from": ".//w:moveFrom", "inserted": ".//w:ins",
                    "hidden": ".//w:r[w:rPr/w:vanish]", "comments": ".//w:comment",
                    "footnotes": ".//w:footnote", "endnotes": ".//w:endnote",
                    "text_boxes": ".//w:txbxContent", "content_controls": ".//w:sdt",
                    "symbols": ".//w:sym", "floating_drawings": ".//w:drawing"}
        for channel, expression in channels.items():
            for element in root.xpath(expression, namespaces=NS):
                if channel == "hidden" and not _on(element.find("w:rPr/w:vanish", NS)):
                    continue
                record["channels"].append({"channel": channel, "part": name,
                    "xpath": root.getroottree().getpath(element), "xml": etree.tostring(element, encoding="unicode")})
        # Transform only the rendering derivative. The untouched package is kept
        # as source/original.docx and every original part has its own checksum.
        for tag in ("del", "moveFrom", "instrText", "fldChar"):
            for element in list(root.iter(W + tag)):
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)
        for element in list(root.iter(W + "fldSimple")):
            parent = element.getparent()
            index = parent.index(element)
            for child in list(element):
                parent.insert(index, child)
                index += 1
            parent.remove(element)
        for element in root.iter(W + "updateFields"):
            element.set(W + "val", "false")
        content[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    record["render_blockers"] = sorted(set(record["render_blockers"]))
    return record, deterministic_zip(content)


def render_word(derivative: bytes, settings: Settings) -> tuple[bytes, dict[str, Any]]:
    executable = shutil.which(settings.extraction_word_renderer)
    if not executable:
        raise ValueError("WORD_RENDERER_UNAVAILABLE")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    allowed = {"PATH", "HOME", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "FONTCONFIG_PATH", "FONTCONFIG_FILE"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(LANG="C.UTF-8", LC_ALL="C.UTF-8")
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
        version = subprocess.run([executable, "--version"], capture_output=True, timeout=15,
                                 check=True, creationflags=flags, env=environment).stdout.decode(errors="replace").strip()  # noqa: S603
        subprocess.run([executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
                        "--nodefault", "--norestore", "--convert-to", "pdf:writer_pdf_Export",
                        "--outdir", str(root), str(source)], capture_output=True, check=True,
                       timeout=settings.extraction_word_timeout_seconds, creationflags=flags,
                       env=environment)  # noqa: S603
        pdf = root / "source.pdf"
        if not pdf.exists() or pdf.stat().st_size > settings.upload_max_bytes:
            raise ValueError("WORD_RENDER_FAILED")
        font_list = "NOT_AVAILABLE"
        if fonts := shutil.which("fc-list"):
            font_list = subprocess.run([fonts], capture_output=True, check=True, timeout=15,
                                       creationflags=flags, env=environment).stdout.decode(errors="replace")  # noqa: S603
        pdf_bytes = pdf.read_bytes()
        return pdf_bytes, {"version": version, "locale": "C.UTF-8", "fonts": font_list,
                           "field_policy": "freeze_cached_values", "revision_view": "current",
                           "input_derivative_sha256": sha256(derivative), "derivative_sha256": sha256(pdf_bytes)}
