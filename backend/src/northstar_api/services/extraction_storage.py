"""Verified evidence loading and sparse checkpoint recovery for the existing worker."""
from __future__ import annotations

import hashlib
import zipfile
from typing import Any

from northstar_api.services.extraction_checkpoint import PageCheckpoint, decode_page_checkpoint, read_zip
from northstar_api.services.extraction_package import ExtractionPackage
from northstar_api.services.extraction_schema import strict_json

EXPORTS = {"manifest.json", "extracted.json", "extracted_review.txt", "validation_report.txt", "correction_history.json"}


def load_archive(data: bytes, source_sha256: str, *, revision: int | None = None,
                 max_bytes: int = 1024 * 1024 * 1024) -> ExtractionPackage:
    """Never trust a stored approval bit without re-running the current evidence gates."""
    if len(data) > max_bytes:
        raise ValueError("Evidence archive exceeds its compressed-size limit")
    members = read_zip(data, max_members=200_000, max_expanded_bytes=2 * max_bytes)
    if not EXPORTS <= members.keys():
        raise ValueError("Evidence archive is missing required exports")
    manifest = strict_json(members["manifest.json"].decode("utf-8"))
    record = strict_json(members["extracted.json"].decode("utf-8"))
    if not isinstance(manifest, dict) or not isinstance(record, dict):
        raise ValueError("Evidence metadata must be objects")
    hashes = manifest.get("artifacts")
    if not isinstance(hashes, dict) or set(members) != set(hashes) | {"manifest.json"}:
        raise ValueError("Evidence manifest does not account for all artifacts")
    for name, expected in hashes.items():
        if hashlib.sha256(members[name]).hexdigest() != expected:
            raise ValueError("Evidence artifact checksum failed")
    if (record.get("source_sha256") != source_sha256 or manifest.get("source_sha256") != source_sha256
            or record.get("schema_version") != 2
            or revision is not None and record.get("extraction_revision") != revision):
        raise ValueError("Evidence source or revision identity differs")
    package = ExtractionPackage(record, {name: payload for name, payload in members.items() if name not in EXPORTS})
    package.refresh()
    return package


def recover_checkpoints(raw: dict[int, bytes], *, source_sha256: str, configuration_identity: str,
                        revision: int) -> tuple[dict[int, PageCheckpoint], list[int]]:
    """A failed page must not discard completed later pages; invalid caches are reprocessed."""
    valid: dict[int, PageCheckpoint] = {}
    invalid: list[int] = []
    for number, data in sorted(raw.items()):
        try:
            if type(number) is not int or not 1 <= number <= 5000:
                raise ValueError("Invalid checkpoint source unit")
            valid[number] = decode_page_checkpoint(data, source_sha256=source_sha256,
                                                   model=configuration_identity, version=revision, page_number=number)
        except (ValueError, KeyError, TypeError, UnicodeError, OSError, zipfile.BadZipFile):
            invalid.append(number)
    return valid, invalid


def approved_content(package: ExtractionPackage, filename: str) -> str:
    package.refresh()
    if package.record.get("review_status") != "verified_release" or not package.record.get("release_eligible"):
        raise ValueError("Uploaded files must pass source-based extraction review before indexing")
    pages: list[dict[str, Any]] = package.record["pages"]
    return "\n\n".join(f"===PDF_PAGE:{page['number']}===\n{page['selected_text']}"
                       if filename.lower().endswith(".pdf") else page["selected_text"] for page in pages)
