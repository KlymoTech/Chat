from __future__ import annotations

import asyncio
import hashlib
import io
import re
import secrets
import socket
import stat
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from botocore.client import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from northstar_api.config import Settings, get_settings


class ObjectStoreUnavailable(RuntimeError):
    pass


class InvalidUpload(ValueError):
    pass


ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/tiff",
}


@dataclass(frozen=True)
class StagingInventory:
    keys: tuple[str, ...]
    examined: int
    truncated: bool


def validate_docx_archive(data: bytes, *, max_uncompressed_bytes: int) -> None:
    """Check package structure and bounded expansion without extracting members."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > 5_000:
                raise ValueError("DOCX contains too many archive members")
            names = [member.filename for member in members]
            # Open Packaging Convention part names are case-insensitive.
            # Reject ambiguous members before a downstream parser chooses one.
            if len(names) != len({name.casefold() for name in names}):
                raise ValueError("DOCX contains duplicate archive members")
            if sum(member.file_size for member in members) > max_uncompressed_bytes:
                raise ValueError("DOCX exceeds the configured expanded-size limit")
            for member in members:
                name = member.filename
                # Validate POSIX-style OPC member names without extracting
                # archives. Backslashes, dot segments and drive/absolute paths
                # cannot be interpreted differently by downstream tooling.
                parts = name.rstrip("/").split("/")
                if (
                    not name
                    or name.startswith("/")
                    or "\\" in name
                    or ":" in name
                    or any(not part or part in {".", ".."} for part in parts)
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)
                ):
                    raise ValueError("DOCX contains unsafe archive member paths")
                if member.flag_bits & 0x1:
                    raise ValueError("DOCX contains encrypted archive members")
                if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError("DOCX uses an unsupported compression method")
                if member.create_system == 3 and stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("DOCX contains a symbolic link")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(
                set(names)
            ):
                raise ValueError("DOCX is missing required package members")
    except zipfile.BadZipFile as exc:
        raise ValueError("DOCX archive is invalid") from exc


def _matches_upload_signature(content_type: str, data: bytes) -> bool:
    if content_type == "application/pdf":
        return data.startswith(b"%PDF-")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/tiff":
        return data.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"))
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        if not data.startswith(b"PK\x03\x04"):
            return False
        try:
            validate_docx_archive(
                data,
                max_uncompressed_bytes=get_settings().knowledge_max_docx_uncompressed_bytes,
            )
            return True
        except (OSError, ValueError):
            return False
    if content_type in {"text/plain", "text/markdown"}:
        return b"\x00" not in data
    return False



def scan_with_clamav_instream(data: bytes, *, port: int, timeout_seconds: float) -> None:
    """Require a clean ClamAV INSTREAM verdict from the local service sidecar."""
    if not data:
        raise InvalidUpload("Cannot scan an empty upload")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_seconds) as conn:
            conn.settimeout(timeout_seconds)
            conn.sendall(b"zINSTREAM\x00")
            view = memoryview(data)
            for offset in range(0, len(view), 64 * 1024):
                block = view[offset : offset + 64 * 1024]
                conn.sendall(len(block).to_bytes(4, "big"))
                conn.sendall(block)
            conn.sendall(b"\x00\x00\x00\x00")

            response = bytearray()
            terminated = False
            while len(response) < 512:
                chunk = conn.recv(min(128, 512 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if b"\x00" in response or b"\n" in response:
                    terminated = True
                    break
    except (OSError, TimeoutError) as exc:
        raise ObjectStoreUnavailable("Malware scanner is unavailable") from exc
    if not terminated:
        raise ObjectStoreUnavailable("Malware scanner did not return a complete verdict")
    verdict = bytes(response).split(b"\x00", 1)[0].split(b"\n", 1)[0].strip()
    if verdict == b"stream: OK":
        return
    if verdict.startswith(b"stream: ") and verdict.endswith(b" FOUND"):
        raise InvalidUpload("Uploaded file failed malware scan")
    raise ObjectStoreUnavailable("Malware scanner did not approve the upload")


class ObjectStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _require_clean_upload(self, data: bytes) -> None:
        if not self.settings.knowledge_clamav_enabled:
            if self.settings.app_env in {"staging", "production"}:
                raise ObjectStoreUnavailable(
                    "Malware scanner is required for staged upload promotion"
                )
            return
        scan_with_clamav_instream(
            data,
            port=self.settings.knowledge_clamav_port,
            timeout_seconds=self.settings.knowledge_clamav_timeout_seconds,
        )

    def _client(self, *, public: bool = False) -> Any:
        if self.settings.s3_auth_mode == "aws-default":
            # Let the AWS SDK resolve and rotate the workload's credentials.
            # Never attach the MinIO endpoint or application-managed keys here.
            return boto3.client(
                "s3",
                region_name=self.settings.s3_region,
                config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
            )
        access_key = self.settings.s3_access_key_id
        secret_key = self.settings.s3_secret_access_key
        if not self.settings.s3_configured or access_key is None or secret_key is None:
            raise ObjectStoreUnavailable("Object storage is not configured")
        return boto3.client(
            "s3",
            endpoint_url=(self.settings.s3_public_endpoint_url if public else self.settings.s3_endpoint_url),
            region_name=self.settings.s3_region,
            aws_access_key_id=access_key.get_secret_value(),
            aws_secret_access_key=secret_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def new_key(
        self, tenant_id: UUID, filename: str, *, prefix: str = "staging", workspace_id: UUID | None = None
    ) -> str:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePath(filename).name).strip(".-")[:120]
        safe_name = safe_name or "upload"
        today = datetime.now(UTC)
        workspace_part = f"{workspace_id}/" if workspace_id is not None else ""
        return f"{prefix}/{tenant_id}/{workspace_part}{today:%Y/%m}/{secrets.token_urlsafe(18)}-{safe_name}"

    async def presign_post(
        self,
        *,
        tenant_id: UUID,
        filename: str,
        content_type: str,
        size_bytes: int,
        checksum_sha256: str,
        workspace_id: UUID | None = None,
    ) -> tuple[str, str, dict[str, str], datetime]:
        if content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
            raise InvalidUpload("Uploaded file type is not supported")
        if size_bytes <= 0 or size_bytes > self.settings.upload_max_bytes:
            raise InvalidUpload("Uploaded file size is not permitted")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", checksum_sha256):
            raise InvalidUpload("Uploaded file checksum is invalid")
        if self.settings.s3_auth_mode == "aws-default" and workspace_id is None:
            raise InvalidUpload("AWS uploads require an authorized workspace")
        key = self.new_key(
            tenant_id,
            filename,
            workspace_id=workspace_id if self.settings.s3_auth_mode == "aws-default" else None,
        )
        fields = {
            "Content-Type": content_type,
            "x-amz-meta-declared-size": str(size_bytes),
            "x-amz-meta-sha256": checksum_sha256.lower(),
        }
        conditions: list[Any] = [
            {"Content-Type": content_type},
            {"x-amz-meta-declared-size": str(size_bytes)},
            {"x-amz-meta-sha256": checksum_sha256.lower()},
            ["content-length-range", 1, size_bytes],
        ]

        def generate() -> tuple[str, dict[str, str]]:
            try:
                result = self._client(public=True).generate_presigned_post(
                    Bucket=self.settings.s3_bucket,
                    Key=key,
                    Fields=fields,
                    Conditions=conditions,
                    ExpiresIn=self.settings.s3_presign_ttl_seconds,
                )
            except (BotoCoreError, ClientError) as exc:
                raise ObjectStoreUnavailable("Object storage could not sign the upload") from exc
            generated_url = result.get("url")
            generated_fields = result.get("fields")
            if not isinstance(generated_url, str) or not isinstance(generated_fields, dict):
                raise ObjectStoreUnavailable("Object storage returned an invalid upload URL")
            return generated_url, {str(name): str(value) for name, value in generated_fields.items()}

        url, signed_fields = await asyncio.to_thread(generate)
        return (
            key,
            url,
            signed_fields,
            datetime.now(UTC) + timedelta(seconds=self.settings.s3_presign_ttl_seconds),
        )

    async def stale_staging_inventory(
        self,
        tenant_id: UUID,
        *,
        workspace_id: UUID | None = None,
        min_age_seconds: int,
        max_examined: int = 1_000,
    ) -> StagingInventory:
        """Discover old staged keys only; never infer that they are safe to delete."""
        if min_age_seconds <= self.settings.s3_presign_ttl_seconds:
            raise ValueError("Staging inventory age must exceed presigned upload lifetime")
        if max_examined < 1 or max_examined > 10_000:
            raise ValueError("Staging inventory scan limit is invalid")
        if self.settings.s3_auth_mode == "aws-default" and workspace_id is None:
            raise ValueError("AWS staging inventory requires a workspace")
        prefix = f"staging/{tenant_id}/"
        if self.settings.s3_auth_mode == "aws-default":
            prefix += f"{workspace_id}/"
        cutoff = datetime.now(UTC) - timedelta(seconds=min_age_seconds)

        def scan() -> StagingInventory:
            try:
                client = self._client()
                keys: list[str] = []
                examined = 0
                for page in client.get_paginator("list_objects_v2").paginate(
                    Bucket=self.settings.s3_bucket, Prefix=prefix
                ):
                    for item in page.get("Contents", []):
                        if examined >= max_examined:
                            return StagingInventory(tuple(keys), examined, True)
                        key = item.get("Key")
                        modified = item.get("LastModified")
                        if not isinstance(key, str) or not key.startswith(prefix):
                            raise ObjectStoreUnavailable("Object storage returned an invalid staging key")
                        if not isinstance(modified, datetime) or modified.tzinfo is None:
                            raise ObjectStoreUnavailable("Object storage omitted staging modification time")
                        examined += 1
                        if modified.astimezone(UTC) <= cutoff:
                            keys.append(key)
                return StagingInventory(tuple(keys), examined, False)
            except (BotoCoreError, ClientError) as exc:
                raise ObjectStoreUnavailable("Object storage could not inventory staged uploads") from exc

        return await asyncio.to_thread(scan)

    async def promote_staged(
        self, tenant_id: UUID, key: str, *, workspace_id: UUID | None = None
    ) -> tuple[str, str, int, str | None]:
        if self.settings.s3_auth_mode == "aws-default" and workspace_id is None:
            raise InvalidUpload("AWS uploads require an authorized workspace")
        expected_prefix = f"staging/{tenant_id}/"
        if self.settings.s3_auth_mode == "aws-default":
            expected_prefix += f"{workspace_id}/"
        if not key.startswith(expected_prefix):
            raise InvalidUpload("Uploaded object does not belong to this workspace")

        def promote() -> tuple[str, str, int, str | None]:
            try:
                client = self._client()
                head = client.head_object(Bucket=self.settings.s3_bucket, Key=key)
                size = int(head.get("ContentLength", 0))
                metadata = {str(name).lower(): str(value) for name, value in head.get("Metadata", {}).items()}
                declared_size = int(metadata.get("declared-size", "0"))
                content_type = str(head.get("ContentType") or "").split(";", 1)[0].strip().lower()
                version_id = str(head.get("VersionId") or "")
                etag = str(head.get("ETag") or "")
            except ClientError as exc:
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
                if error_code in {"404", "NoSuchKey", "NotFound"}:
                    raise InvalidUpload("Uploaded object was not found or has expired") from exc
                raise ObjectStoreUnavailable("Object storage could not validate the upload") from exc
            except BotoCoreError as exc:
                raise ObjectStoreUnavailable("Object storage could not validate the upload") from exc
            except (TypeError, ValueError) as exc:
                raise InvalidUpload("Uploaded object metadata is invalid") from exc

            if size <= 0 or size > self.settings.upload_max_bytes or declared_size != size:
                raise InvalidUpload("Uploaded object size does not match the signed request")
            if content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
                raise InvalidUpload("Uploaded file type is not supported")
            if not re.fullmatch(r'"[^"\r\n]{1,1024}"', etag):
                raise InvalidUpload("Uploaded object is missing a valid ETag")
            expected_checksum = metadata.get("sha256", "").lower()
            if not re.fullmatch(r"[a-f0-9]{64}", expected_checksum):
                raise InvalidUpload("Uploaded object is missing its signed checksum")
            if self.settings.s3_auth_mode == "aws-default" and (
                not version_id or version_id.lower() == "null"
            ):
                raise ObjectStoreUnavailable("AWS upload bucket must return immutable object versions")

            try:
                source_version = (
                    {"VersionId": version_id} if version_id and version_id.lower() != "null" else {}
                )
                response = client.get_object(
                    Bucket=self.settings.s3_bucket,
                    Key=key,
                    **source_version,
                )
                data = response["Body"].read(self.settings.upload_max_bytes + 1)
            except (BotoCoreError, ClientError, KeyError) as exc:
                raise ObjectStoreUnavailable("Object storage could not read the upload") from exc
            if len(data) != size:
                raise InvalidUpload("Uploaded object changed during validation")
            checksum = hashlib.sha256(data).hexdigest()
            if not secrets.compare_digest(expected_checksum, checksum):
                raise InvalidUpload("Uploaded object checksum does not match")
            if not _matches_upload_signature(content_type, data):
                raise InvalidUpload("Uploaded object bytes do not match the declared file type")
            # The same pinned staged-version bytes validated by SHA-256 must
            # receive a clean scanner verdict before ANY permanent copy.
            self._require_clean_upload(data)
            del data

            permanent_key = key.replace("staging/", "knowledge/", 1)
            copied_version_id: str | None = None
            copy_created = False

            def cleanup_copy() -> None:
                if not copy_created:
                    return
                if self.settings.s3_auth_mode == "aws-default" and (
                    copied_version_id is None or copied_version_id.lower() == "null"
                ):
                    # A plain DELETE could hide a newer writer's version.
                    raise ObjectStoreUnavailable(
                        "AWS promoted copy has no version receipt; cleanup is indeterminate"
                    )
                try:
                    if copied_version_id is not None and copied_version_id.lower() != "null":
                        client.delete_object(
                            Bucket=self.settings.s3_bucket,
                            Key=permanent_key,
                            VersionId=copied_version_id,
                        )
                    else:
                        self._purge_exact_sync(client, permanent_key)
                except (BotoCoreError, ClientError, ObjectStoreUnavailable) as exc:
                    raise ObjectStoreUnavailable(
                        "Object storage could not clean up an invalid promoted upload"
                    ) from exc

            try:
                copy_source = {"Bucket": self.settings.s3_bucket, "Key": key, **source_version}
                copy_result = client.copy_object(
                    Bucket=self.settings.s3_bucket,
                    Key=permanent_key,
                    CopySource=copy_source,
                    CopySourceIfMatch=etag,
                    MetadataDirective="COPY",
                )
                copy_created = True
                version_value = copy_result.get("VersionId")
                if isinstance(version_value, str) and version_value:
                    copied_version_id = version_value
                if self.settings.s3_auth_mode == "aws-default" and (
                    not copied_version_id or copied_version_id.lower() == "null"
                ):
                    raise ObjectStoreUnavailable("AWS upload copy must return an immutable object version")
                copied = client.head_object(
                    Bucket=self.settings.s3_bucket,
                    Key=permanent_key,
                    **(
                        {"VersionId": copied_version_id}
                        if self.settings.s3_auth_mode == "aws-default"
                        else {}
                    ),
                )
            except (BotoCoreError, ClientError, AttributeError, ObjectStoreUnavailable) as exc:
                cleanup_copy()
                raise ObjectStoreUnavailable("Object storage could not promote the upload") from exc
            try:
                copied_size = int(copied.get("ContentLength", -1))
            except (TypeError, ValueError):
                copied_size = -1
            copy_valid = copied_size == size
            if copy_valid and self.settings.s3_auth_mode == "aws-default":
                try:
                    promoted = client.get_object(
                        Bucket=self.settings.s3_bucket,
                        Key=permanent_key,
                        VersionId=copied_version_id,
                    )
                    body = promoted["Body"]
                    copied_digest = hashlib.sha256()
                    copied_bytes = 0
                    while copied_bytes <= size:
                        chunk = body.read(min(1024 * 1024, size - copied_bytes + 1))
                        if not chunk:
                            break
                        copied_bytes += len(chunk)
                        copied_digest.update(chunk)
                    copy_valid = copied_bytes == size and secrets.compare_digest(
                        copied_digest.hexdigest(), checksum
                    )
                except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
                    cleanup_copy()
                    raise ObjectStoreUnavailable(
                        "Object storage could not verify the promoted version"
                    ) from exc
            if not copy_valid:
                cleanup_copy()
                raise ObjectStoreUnavailable("Object storage did not preserve the uploaded file")
            try:
                client.delete_object(Bucket=self.settings.s3_bucket, Key=key, **source_version)
            except (BotoCoreError, ClientError) as exc:
                cleanup_copy()
                raise ObjectStoreUnavailable("Object storage could not remove the staged upload") from exc
            approved_version = copied_version_id if self.settings.s3_auth_mode == "aws-default" else None
            return permanent_key, checksum, size, approved_version

        return await asyncio.to_thread(promote)

    async def delete(self, key: str) -> None:
        def remove() -> None:
            try:
                self._client().delete_object(Bucket=self.settings.s3_bucket, Key=key)
            except (BotoCoreError, ClientError) as exc:
                raise ObjectStoreUnavailable("Object storage could not delete the object") from exc

        await asyncio.to_thread(remove)

    def _require_aws_versioning(self, status: str | None) -> None:
        if self.settings.s3_auth_mode == "aws-default" and status != "Enabled":
            raise ObjectStoreUnavailable("AWS object purge requires enabled bucket versioning")

    def _purge_exact_sync(self, client: Any, key: str) -> int:
        bucket = self.settings.s3_bucket
        try:
            versioning = client.get_bucket_versioning(Bucket=bucket)
            self._require_aws_versioning(versioning.get("Status"))
            if versioning.get("Status") not in {"Enabled", "Suspended"}:
                client.delete_object(Bucket=bucket, Key=key)
                return 1

            versioned_objects: list[dict[str, str]] = []
            paginator = client.get_paginator("list_object_versions")
            for page in paginator.paginate(Bucket=bucket, Prefix=key):
                for collection_name in ("Versions", "DeleteMarkers"):
                    for item in page.get(collection_name, []):
                        if item.get("Key") != key:
                            continue
                        version_id = item.get("VersionId")
                        if not isinstance(version_id, str) or not version_id:
                            raise ObjectStoreUnavailable("Object storage returned an invalid object version")
                        versioned_objects.append({"Key": key, "VersionId": version_id})

            for start in range(0, len(versioned_objects), 1_000):
                batch = versioned_objects[start : start + 1_000]
                response = client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": batch, "Quiet": True},
                )
                errors = response.get("Errors", [])
                if errors:
                    raise ObjectStoreUnavailable("Object storage could not delete every object version")

            # A new version or delete marker can appear after enumeration. Do
            # not acknowledge the cleanup event until the exact key is empty;
            # the caller may retry the idempotent purge on a later delivery.
            for page in paginator.paginate(Bucket=bucket, Prefix=key):
                for collection_name in ("Versions", "DeleteMarkers"):
                    if any(item.get("Key") == key for item in page.get(collection_name, [])):
                        raise ObjectStoreUnavailable("Object storage still contains the purged key")
            return len(versioned_objects)
        except ObjectStoreUnavailable:
            raise
        except (BotoCoreError, ClientError, KeyError, TypeError) as exc:
            raise ObjectStoreUnavailable("Object storage could not purge the object") from exc

    async def purge_exact(self, key: str) -> int:
        """Permanently remove one key, including every version and delete marker."""

        def purge() -> int:
            return self._purge_exact_sync(self._client(), key)

        return await asyncio.to_thread(purge)

    async def rollback_promoted(self, key: str, *, version_id: str | None) -> None:
        """Remove only this request's promoted version after a failed DB commit."""
        if not key.startswith("knowledge/"):
            raise ValueError("Promoted object key is invalid")
        if self.settings.s3_auth_mode != "aws-default":
            await self.purge_exact(key)
            return
        if not version_id or version_id.lower() == "null":
            raise ObjectStoreUnavailable("AWS promoted rollback requires its copied version receipt")

        def remove() -> None:
            try:
                self._client().delete_object(Bucket=self.settings.s3_bucket, Key=key, VersionId=version_id)
            except (BotoCoreError, ClientError) as exc:
                raise ObjectStoreUnavailable(
                    "Object storage could not roll back the promoted version"
                ) from exc

        await asyncio.to_thread(remove)

    async def purge_prefix(self, prefix: str) -> int:
        """Remove all artifacts and versions below one validated source prefix."""
        if not prefix.startswith("extractions/") or not prefix.endswith("/"):
            raise ValueError("Invalid extraction prefix")

        def purge() -> int:
            client = self._client()
            bucket = self.settings.s3_bucket
            versioning = client.get_bucket_versioning(Bucket=bucket)
            self._require_aws_versioning(versioning.get("Status"))
            objects: list[dict[str, str]] = []
            if versioning.get("Status") in {"Enabled", "Suspended"}:
                pages = client.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix)
                for page in pages:
                    for collection in ("Versions", "DeleteMarkers"):
                        for item in page.get(collection, []):
                            key = item.get("Key")
                            version_id = item.get("VersionId")
                            if (
                                isinstance(key, str)
                                and key.startswith(prefix)
                                and isinstance(version_id, str)
                            ):
                                objects.append({"Key": key, "VersionId": version_id})
            else:
                pages = client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
                for page in pages:
                    for item in page.get("Contents", []):
                        key = item.get("Key")
                        if isinstance(key, str) and key.startswith(prefix):
                            objects.append({"Key": key})
            for start in range(0, len(objects), 1_000):
                result = client.delete_objects(
                    Bucket=bucket, Delete={"Objects": objects[start : start + 1_000], "Quiet": True}
                )
                if result.get("Errors"):
                    raise ObjectStoreUnavailable("Object storage could not purge extraction evidence")
            operation = (
                "list_object_versions"
                if versioning.get("Status") in {"Enabled", "Suspended"}
                else "list_objects_v2"
            )
            for page in client.get_paginator(operation).paginate(Bucket=bucket, Prefix=prefix):
                collections = (
                    ("Versions", "DeleteMarkers") if operation == "list_object_versions" else ("Contents",)
                )
                if any(
                    isinstance(item.get("Key"), str) and item["Key"].startswith(prefix)
                    for collection in collections
                    for item in page.get(collection, [])
                ):
                    raise ObjectStoreUnavailable("Object storage still contains extraction evidence")
            return len(objects)

        return await asyncio.to_thread(purge)

    async def download(
        self, key: str, *, limit_bytes: int | None = None, expected_version_id: str | None = None
    ) -> tuple[bytes, dict[str, Any]]:
        limit = limit_bytes or self.settings.upload_max_bytes

        def fetch() -> tuple[bytes, dict[str, Any]]:
            client = self._client()
            if expected_version_id is not None and (
                self.settings.s3_auth_mode != "aws-default"
                or not expected_version_id
                or expected_version_id.lower() == "null"
            ):
                raise ObjectStoreUnavailable("Approved object version is invalid for this storage mode")
            head = client.head_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                **({"VersionId": expected_version_id} if expected_version_id is not None else {}),
            )
            size = int(head.get("ContentLength", 0))
            if size <= 0 or size > limit:
                raise ValueError("Uploaded object is empty or exceeds the configured size limit")
            version_id = str(head.get("VersionId") or "")
            if self.settings.s3_auth_mode == "aws-default" and (
                not version_id or version_id.lower() == "null"
            ):
                raise ObjectStoreUnavailable("AWS object download requires an immutable version")
            if expected_version_id is not None and version_id != expected_version_id:
                raise ObjectStoreUnavailable("Object storage returned a different approved version")
            response = client.get_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                **({"VersionId": version_id} if self.settings.s3_auth_mode == "aws-default" else {}),
            )
            data = response["Body"].read(limit + 1)
            if len(data) != size or len(data) > limit:
                raise ValueError("Uploaded object size changed or exceeds the configured limit")
            return data, {"content_type": head.get("ContentType"), "metadata": head.get("Metadata", {})}

        return await asyncio.to_thread(fetch)

    async def put_extraction(self, tenant_id: UUID, source_id: UUID, data: bytes, *, version: int) -> str:
        if version < 1:
            raise ValueError("Extraction version must be positive")
        key = f"extractions/{tenant_id}/{source_id}/v{version:04d}.zip"

        def put() -> None:
            self._client().put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType="application/zip",
            )

        await asyncio.to_thread(put)
        return key

    async def put_extraction_page(
        self, tenant_id: UUID, source_id: UUID, *, version: int, page_number: int, data: bytes
    ) -> str:
        if version < 1 or page_number < 1 or len(data) > 50 * 1024 * 1024:
            raise ValueError("Extraction page checkpoint exceeds safe limits")
        key = f"extractions/{tenant_id}/{source_id}/v{version:04d}/page_{page_number:04d}.zip"

        def put() -> None:
            self._client().put_object(
                Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType="application/zip"
            )

        await asyncio.to_thread(put)
        return key

    async def load_extraction_pages(
        self, tenant_id: UUID, source_id: UUID, *, version: int
    ) -> dict[int, bytes]:
        prefix = f"extractions/{tenant_id}/{source_id}/v{version:04d}/"

        def load() -> dict[int, bytes]:
            client = self._client()
            entries: list[tuple[int, str, int]] = []
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.settings.s3_bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = str(item.get("Key") or "")
                    match = re.fullmatch(re.escape(prefix) + r"page_(\d{4}).zip", key)
                    if match:
                        size = int(item.get("Size") or 0)
                        if size <= 0 or size > 50 * 1024 * 1024:
                            raise ValueError("Extraction checkpoint exceeds safe limits")
                        entries.append((int(match.group(1)), key, size))
            if (
                len(entries) > self.settings.knowledge_max_pdf_pages
                or sum(entry[2] for entry in entries) > 1024 * 1024 * 1024
            ):
                raise ValueError("Extraction checkpoints exceed configured limits")
            result: dict[int, bytes] = {}
            for number, key, size in entries:
                data = client.get_object(Bucket=self.settings.s3_bucket, Key=key)["Body"].read(size + 1)
                if len(data) != size:
                    raise ValueError("Extraction checkpoint changed during reading")
                result[number] = data
            return result

        return await asyncio.to_thread(load)


object_store = ObjectStore()
