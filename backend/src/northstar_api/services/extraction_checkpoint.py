"""Bounded archive intake and source/configuration-bound page checkpoints."""
from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from collections.abc import Awaitable, Callable
from typing import Any

from northstar_api.services.extraction_regions import PROMPT_VERSION
from northstar_api.services.extraction_schema import digest, strict_json
from northstar_api.services.extraction_validation import safe_name

PageCheckpoint = tuple[dict[str, Any], bytes, list[dict[str, Any]]]
PageCallback = Callable[[dict[str, Any], bytes, list[dict[str, Any]]], Awaitable[None]]


def read_zip(data: bytes, *, max_members: int, max_expanded_bytes: int, max_member_bytes: int | None = None,
             allow_directories: bool = False) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > max_members or sum(member.file_size for member in members) > max_expanded_bytes:
            raise ValueError("Archive exceeds expanded-size or member limits")
        if len({member.filename for member in members}) != len(members):
            raise ValueError("Archive contains duplicate members")
        result = {}
        for member in members:
            if member.is_dir() and allow_directories:
                if not safe_name(member.filename.rstrip("/")):
                    raise ValueError("Unsafe archive directory")
                continue
            if (not safe_name(member.filename) or member.is_dir() or stat.S_ISLNK(member.external_attr >> 16)
                    or member.flag_bits & 1 or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError("Unsafe or unsupported archive member")
            if max_member_bytes is not None and member.file_size > max_member_bytes:
                raise ValueError("Archive member exceeds its size limit")
            with archive.open(member) as stream:
                payload = stream.read(member.file_size + 1)
            if len(payload) != member.file_size:
                raise ValueError("Archive member size differs from its declaration")
            result[member.filename] = payload
        return result


def resumable(page: dict[str, Any], issues: list[dict[str, Any]]) -> bool:
    return bool(page.get("inventory_complete") and page.get("image")
                and not any(issue.get("technical") for issue in issues)
                and all(block.get("status") == "split" or (block.get("visual") or {}).get("complete") is True
                        for block in page.get("blocks", [])))


def encode_page_checkpoint(page: dict[str, Any], image: bytes, page_issues: list[dict[str, Any]], *,
                           source_sha256: str, model: str, version: int) -> bytes:
    if not resumable(page, page_issues):
        raise ValueError("Only completed source-reading stages may be checkpointed")
    image_hash = hashlib.sha256(image).hexdigest()
    if page.get("image_sha256") != image_hash:
        raise ValueError("Checkpoint image checksum failed")
    metadata = {"checkpoint_schema_version": 2, "source_sha256": source_sha256, "model": model,
                "prompt_version": PROMPT_VERSION, "version": version, "page": page, "issues": page_issues,
                "image_sha256": image_hash, "page_sha256": digest(page)}
    metadata["metadata_sha256"] = digest(metadata)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (("page.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode()), ("image.png", image)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()


def decode_page_checkpoint(data: bytes, *, source_sha256: str, model: str, version: int, page_number: int) -> PageCheckpoint:
    if len(data) > 128 * 1024 * 1024:
        raise ValueError("Checkpoint exceeds compressed-size limit")
    contents = read_zip(data, max_members=2, max_expanded_bytes=128 * 1024 * 1024, max_member_bytes=96 * 1024 * 1024)
    if set(contents) != {"page.json", "image.png"} or len(contents["page.json"]) > 32 * 1024 * 1024:
        raise ValueError("Checkpoint artifact set is invalid")
    metadata = strict_json(contents["page.json"].decode("utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Checkpoint metadata is invalid")
    expected_digest = metadata.pop("metadata_sha256", None)
    page, image, issues = metadata.get("page"), contents["image.png"], metadata.get("issues")
    image_hash = hashlib.sha256(image).hexdigest()
    if (metadata.get("checkpoint_schema_version") != 2 or expected_digest != digest(metadata)
            or metadata.get("source_sha256") != source_sha256 or metadata.get("model") != model
            or metadata.get("prompt_version") != PROMPT_VERSION or metadata.get("version") != version
            or not isinstance(page, dict) or page.get("number") != page_number
            or metadata.get("page_sha256") != digest(page) or metadata.get("image_sha256") != image_hash
            or page.get("image_sha256") != image_hash or not isinstance(issues, list)
            or not all(isinstance(issue, dict) for issue in issues) or not resumable(page, issues)):
        raise ValueError("Checkpoint source identity, completion, or checksum failed")
    return page, image, issues
