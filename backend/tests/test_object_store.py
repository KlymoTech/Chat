from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from northstar_api.config import Settings, get_settings
from northstar_api.services.object_store import (
    InvalidUpload,
    ObjectStore,
    ObjectStoreUnavailable,
    _matches_upload_signature,
    scan_with_clamav_instream,
    validate_docx_archive,
)


def test_aws_default_s3_client_uses_sdk_identity_without_static_keys_or_custom_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = Mock(return_value=Mock())
    monkeypatch.setattr("northstar_api.services.object_store.boto3.client", create)
    settings = Settings(
        s3_auth_mode="aws-default",
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_endpoint_url=None,
        s3_public_endpoint_url=None,
        s3_region="ap-south-1",
    )
    store = ObjectStore(settings)
    assert store._client(public=True) is create.return_value
    kwargs = create.call_args.kwargs
    assert kwargs["region_name"] == "ap-south-1"
    assert kwargs["config"].signature_version == "s3v4"
    assert kwargs["config"].s3["addressing_style"] == "virtual"
    assert "endpoint_url" not in kwargs
    assert "aws_access_key_id" not in kwargs
    assert "aws_secret_access_key" not in kwargs


def test_existing_static_s3_mode_keeps_minio_endpoint_and_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = Mock(return_value=Mock())
    monkeypatch.setattr("northstar_api.services.object_store.boto3.client", create)
    settings = Settings(
        s3_auth_mode="static",
        s3_access_key_id="minio-user",
        s3_secret_access_key="minio-secret",  # noqa: S106 - test-only fake credential
        s3_endpoint_url="http://minio:9000",
        s3_public_endpoint_url="http://localhost:9000",
    )
    store = ObjectStore(settings)
    store._client(public=True)
    kwargs = create.call_args.kwargs
    assert kwargs["endpoint_url"] == settings.s3_public_endpoint_url
    assert kwargs["aws_access_key_id"] == settings.s3_access_key_id.get_secret_value()
    assert kwargs["aws_secret_access_key"] == settings.s3_secret_access_key.get_secret_value()
    assert kwargs["config"].s3["addressing_style"] == "path"


@pytest.mark.asyncio
async def test_missing_aws_credentials_fails_as_storage_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        s3_auth_mode="aws-default",
        s3_access_key_id=None,
        s3_secret_access_key=None,
        s3_endpoint_url=None,
        s3_public_endpoint_url=None,
    )
    store = ObjectStore(settings)
    client = Mock()
    client.generate_presigned_post.side_effect = NoCredentialsError()
    monkeypatch.setattr(store, "_client", Mock(return_value=client))
    with pytest.raises(ObjectStoreUnavailable, match="could not sign"):
        await store.presign_post(
            tenant_id=uuid4(),
            workspace_id=uuid4(),
            filename="note.txt",
            content_type="text/plain",
            size_bytes=4,
            checksum_sha256=hashlib.sha256(b"note").hexdigest(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("checksum", ["not-a-sha256", "a" * 63, "g" * 64])
async def test_presign_rejects_invalid_checksum_before_storage_io(
    monkeypatch: pytest.MonkeyPatch, checksum: str
) -> None:
    store = ObjectStore(get_settings())
    client = Mock()
    monkeypatch.setattr(store, "_client", client)

    with pytest.raises(InvalidUpload, match="checksum is invalid"):
        await store.presign_post(
            tenant_id=uuid4(),
            filename="note.txt",
            content_type="text/plain",
            size_bytes=4,
            checksum_sha256=checksum,
        )

    client.assert_not_called()


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def read(self, size: int) -> bytes:
        result = self.data[self.position : self.position + size]
        self.position += len(result)
        return result


class _FakeS3:
    def __init__(
        self,
        data: bytes,
        *,
        declared_size: int | None = None,
        etag: str | None = '"object-etag"',
        copied_size: int | None = None,
        copied_version_id: str | None = "copy-version-1",
        source_version_id: str | None = "version-1",
        copied_data: bytes | None = None,
        content_type: str = "text/plain",
    ) -> None:
        self.data = data
        self.declared_size = len(data) if declared_size is None else declared_size
        self.etag = etag
        self.copied_size = copied_size
        self.copied_version_id = copied_version_id
        self.source_version_id = source_version_id
        self.copied_data = copied_data
        self.content_type = content_type
        self.read_arguments: list[dict[str, Any]] = []
        self.head_arguments: list[dict[str, Any]] = []
        self.copied_to: str | None = None
        self.deleted: list[str] = []
        self.delete_arguments: list[dict[str, Any]] = []
        self.post_arguments: dict[str, Any] = {}
        self.checksum = hashlib.sha256(data).hexdigest()

    def generate_presigned_post(self, **kwargs: Any) -> dict[str, Any]:
        self.post_arguments = kwargs
        return {"url": "https://storage.example/upload", "fields": {"key": kwargs["Key"], **kwargs["Fields"]}}

    def head_object(self, *, Bucket: str, Key: str, **kwargs: Any) -> dict[str, Any]:  # noqa: N803
        del Bucket
        self.head_arguments.append({"Key": Key, **kwargs})
        result: dict[str, Any] = {
            "ContentLength": (
                self.copied_size if Key == self.copied_to and self.copied_size is not None else len(self.data)
            ),
            "ContentType": self.content_type,
            "Metadata": {"declared-size": str(self.declared_size), "sha256": self.checksum},
            "VersionId": kwargs.get("VersionId", self.source_version_id),
        }
        if self.etag is not None:
            result["ETag"] = self.etag
        return result

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:  # noqa: N803
        del Bucket
        self.read_arguments.append({"Key": Key, **_})
        data = self.copied_data if Key == self.copied_to and self.copied_data is not None else self.data
        return {"Body": _Body(data)}

    def copy_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, str]:  # noqa: N803
        del Bucket
        self.copied_to = Key
        return {"VersionId": self.copied_version_id} if self.copied_version_id else {}

    def delete_object(self, *, Bucket: str, Key: str, **kwargs: Any) -> None:  # noqa: N803
        del Bucket
        self.deleted.append(Key)
        self.delete_arguments.append({"Key": Key, **kwargs})


class _FakeVersionPaginator:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = pages
        self.arguments: dict[str, Any] = {}
        self.calls = 0

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.arguments = kwargs
        self.calls += 1
        return self.pages


class _FakeVersionedS3:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.paginator = _FakeVersionPaginator(pages)
        self.deleted_batches: list[list[dict[str, str]]] = []
        self.deleted_unversioned: list[str] = []

    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, str]:  # noqa: N803
        del Bucket
        return {"Status": "Enabled"}

    def get_paginator(self, operation: str) -> _FakeVersionPaginator:
        assert operation == "list_object_versions"
        return self.paginator

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        del Bucket
        self.deleted_batches.append(Delete["Objects"])
        removed = {(item["Key"], item["VersionId"]) for item in Delete["Objects"]}
        for page in self.paginator.pages:
            for collection in ("Versions", "DeleteMarkers"):
                page[collection] = [
                    item
                    for item in page.get(collection, [])
                    if (item["Key"], item["VersionId"]) not in removed
                ]
        return {}

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        del Bucket
        self.deleted_unversioned.append(Key)


async def test_presigned_post_is_staged_and_size_constrained(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"verified upload")
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    key, url, fields, _ = await store.presign_post(
        tenant_id=tenant_id,
        filename="policy.txt",
        content_type="text/plain",
        size_bytes=len(client.data),
        checksum_sha256=client.checksum,
    )

    assert key.startswith(f"staging/{tenant_id}/")
    assert url == "https://storage.example/upload"
    assert fields["x-amz-meta-declared-size"] == str(len(client.data))
    assert ["content-length-range", 1, len(client.data)] in client.post_arguments["Conditions"]

    permanent_key, checksum, size, version_id = await store.promote_staged(tenant_id, key)
    assert permanent_key == key.replace("staging/", "knowledge/", 1)
    assert checksum == hashlib.sha256(client.data).hexdigest()
    assert size == len(client.data)
    assert version_id is None
    assert client.copied_to == permanent_key
    assert key in client.deleted


async def test_staging_inventory_is_scoped_aged_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    prefix = f"staging/{tenant_id}/{workspace_id}/"
    paginator = _FakeVersionPaginator(
        [
            {
                "Contents": [
                    {"Key": f"{prefix}old.txt", "LastModified": datetime.now(UTC) - timedelta(hours=2)},
                    {"Key": f"{prefix}new.txt", "LastModified": datetime.now(UTC)},
                ]
            }
        ]
    )
    client = Mock()
    client.get_paginator.return_value = paginator
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    inventory = await store.stale_staging_inventory(
        tenant_id, workspace_id=workspace_id, min_age_seconds=3600
    )
    assert inventory.keys == (f"{prefix}old.txt",)
    assert inventory.examined == 2
    assert not inventory.truncated
    assert paginator.arguments == {"Bucket": store.settings.s3_bucket, "Prefix": prefix}
    client.delete_object.assert_not_called()
    client.delete_objects.assert_not_called()


async def test_staging_inventory_caps_examined_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    prefix = f"staging/{tenant_id}/"
    paginator = _FakeVersionPaginator(
        [
            {
                "Contents": [
                    {"Key": f"{prefix}{index}.txt", "LastModified": datetime.now(UTC) - timedelta(days=2)}
                    for index in range(3)
                ]
            }
        ]
    )
    client = Mock()
    client.get_paginator.return_value = paginator
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    inventory = await store.stale_staging_inventory(tenant_id, min_age_seconds=3600, max_examined=2)
    assert inventory.examined == 2
    assert inventory.truncated
    assert len(inventory.keys) == 2


async def test_aws_staging_inventory_requires_workspace_and_expired_capability() -> None:
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    with pytest.raises(ValueError, match="requires a workspace"):
        await store.stale_staging_inventory(uuid4(), min_age_seconds=3600)
    with pytest.raises(ValueError, match="must exceed presigned upload lifetime"):
        await store.stale_staging_inventory(uuid4(), workspace_id=uuid4(), min_age_seconds=900)


async def test_document_upload_allows_500_mb_and_rejects_one_byte_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3(b"metadata-only size boundary test")
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)
    limit = 500 * 1024 * 1024
    assert store.settings.upload_max_bytes == limit
    await store.presign_post(
        tenant_id=uuid4(),
        filename="large.pdf",
        content_type="application/pdf",
        size_bytes=limit,
        checksum_sha256=client.checksum,
    )
    assert ["content-length-range", 1, limit] in client.post_arguments["Conditions"]
    with pytest.raises(InvalidUpload, match="file size"):
        await store.presign_post(
            tenant_id=uuid4(),
            filename="too-large.pdf",
            content_type="application/pdf",
            size_bytes=limit + 1,
            checksum_sha256=client.checksum,
        )


async def test_promotion_rejects_a_size_different_from_signed_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"payload", declared_size=100)
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(InvalidUpload, match="size does not match"):
        await store.promote_staged(tenant_id, f"staging/{tenant_id}/2026/09/example.txt")

    assert client.copied_to is None


@pytest.mark.parametrize("source_version_id", [None, "", "null"])
async def test_aws_promotion_requires_versioned_staging_object(
    monkeypatch: pytest.MonkeyPatch, source_version_id: str | None
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    client = _FakeS3(b"payload", source_version_id=source_version_id)
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="immutable object versions"):
        await store.promote_staged(
            tenant_id, f"staging/{tenant_id}/{workspace_id}/2026/09/example.txt", workspace_id=workspace_id
        )

    assert client.copied_to is None
    assert client.deleted == []


@pytest.mark.parametrize("copied_data", [None, b"payloax"])
async def test_aws_promotion_verifies_exact_copied_version(
    monkeypatch: pytest.MonkeyPatch, copied_data: bytes | None
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    client = _FakeS3(b"payload", copied_data=copied_data)
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)
    staging_key = f"staging/{tenant_id}/{workspace_id}/2026/09/example.txt"

    if copied_data is None:
        promoted = await store.promote_staged(tenant_id, staging_key, workspace_id=workspace_id)
        assert promoted[1] == client.checksum
        assert promoted[3] == "copy-version-1"
        assert client.deleted == [staging_key]
    else:
        with pytest.raises(ObjectStoreUnavailable, match="did not preserve"):
            await store.promote_staged(tenant_id, staging_key, workspace_id=workspace_id)
        assert client.delete_arguments == [{"Key": client.copied_to, "VersionId": "copy-version-1"}]
    assert {"Key": client.copied_to, "VersionId": "copy-version-1"} in client.head_arguments
    assert {"Key": client.copied_to, "VersionId": "copy-version-1"} in client.read_arguments


async def test_aws_promotion_cleans_exact_copy_when_staging_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    staging_key = f"staging/{tenant_id}/{workspace_id}/2026/09/example.txt"
    client = _FakeS3(b"payload")
    original_delete = client.delete_object

    def delete_or_deny(*, Bucket: str, Key: str, **kwargs: Any) -> None:  # noqa: N803
        if Key == staging_key:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "DeleteObject")
        original_delete(Bucket=Bucket, Key=Key, **kwargs)

    client.delete_object = delete_or_deny  # type: ignore[method-assign]
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="could not remove the staged upload"):
        await store.promote_staged(tenant_id, staging_key, workspace_id=workspace_id)

    assert client.delete_arguments == [{"Key": client.copied_to, "VersionId": "copy-version-1"}]


@pytest.mark.parametrize("copied_version_id", [None, "null"])
async def test_aws_promotion_rejects_unversioned_destination_without_deleting_latest(
    monkeypatch: pytest.MonkeyPatch, copied_version_id: str | None
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    client = _FakeS3(b"payload", copied_version_id=copied_version_id)
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="cleanup is indeterminate"):
        await store.promote_staged(
            tenant_id, f"staging/{tenant_id}/{workspace_id}/2026/09/example.txt", workspace_id=workspace_id
        )

    assert client.deleted == []


@pytest.mark.parametrize(
    ("content_type", "data", "accepted"),
    [
        ("application/pdf", b"%PDF-1.7\nbody", True),
        ("application/pdf", b"not a pdf", False),
        ("image/png", b"\x89PNG\r\n\x1a\nbody", True),
        ("image/png", b"not a png", False),
        ("image/jpeg", b"\xff\xd8\xffbody", True),
        ("image/jpeg", b"\xff\xd8not-jpeg", False),
        ("image/tiff", b"II*\x00body", True),
        ("image/tiff", b"not a tiff", False),
        ("text/plain", b"hello world", True),
        ("text/plain", b"hello\x00world", False),
    ],
)
def test_upload_signature_matches_declared_type(content_type: str, data: bytes, accepted: bool) -> None:
    assert _matches_upload_signature(content_type, data) is accepted


@pytest.mark.parametrize("content_type", ["text/plain", "text/markdown"])
def test_text_upload_rejects_binary_content_after_initial_screen(content_type: str) -> None:
    assert not _matches_upload_signature(content_type, b"a" * 8192 + b"\x00" + b"tail")


def test_docx_signature_requires_package_members() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert _matches_upload_signature(docx_type, stream.getvalue())
    assert not _matches_upload_signature(docx_type, b"PK\x03\x04fake zip")


def test_docx_archive_limits_are_shared_by_promotion_and_ingestion() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "x" * 1_024)
    data = stream.getvalue()
    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    validate_docx_archive(data, max_uncompressed_bytes=2_048)
    with pytest.raises(ValueError, match="expanded-size limit"):
        validate_docx_archive(data, max_uncompressed_bytes=100)

    assert _matches_upload_signature(content_type, data)


def test_docx_archive_rejects_excessive_member_count() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        for index in range(4_999):
            archive.writestr(f"word/media/{index}", b"")

    with pytest.raises(ValueError, match="too many archive members"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=1024)
    assert not _matches_upload_signature(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        stream.getvalue(),
    )


def test_docx_archive_rejects_duplicate_package_members() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("word/document.xml", "second")

    with pytest.raises(ValueError, match="duplicate archive members"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=1024)
    assert not _matches_upload_signature(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        stream.getvalue(),
    )


@pytest.mark.parametrize(
    "bad_member",
    [
        "../outside.xml",
        "word/../outside.xml",
        "/absolute.xml",
        "C:/windows.xml",
        "word\\\\other.xml",
        "word//double.xml",
        "word/./same.xml",
    ],
)
def test_docx_archive_rejects_unsafe_member_paths(bad_member: str) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        archive.writestr(bad_member, "other")

    with pytest.raises(ValueError, match="unsafe archive member paths"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=2_048)


def test_docx_archive_rejects_case_insensitive_duplicate_names() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "first")
        archive.writestr("word/DOCUMENT.xml", "second")

    with pytest.raises(ValueError, match="duplicate archive members"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=2_048)


def test_docx_archive_rejects_unix_symbolic_link() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        member = zipfile.ZipInfo("word/media/link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "outside.xml")

    with pytest.raises(ValueError, match="symbolic link"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=2_048)


def test_docx_archive_rejects_unsupported_zip_compression() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_BZIP2) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")

    with pytest.raises(ValueError, match="unsupported compression"):
        validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=2_048)


def test_docx_archive_rejects_encrypted_member_flag() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
    payload = bytearray(stream.getvalue())
    offset = 0
    while True:
        header = payload.find(b"PK\x01\x02", offset)
        if header < 0:
            break
        payload[header + 8] |= 0x1
        offset = header + 4

    with pytest.raises(ValueError, match="encrypted archive members"):
        validate_docx_archive(bytes(payload), max_uncompressed_bytes=2_048)


def test_docx_archive_accepts_normal_directory_entries() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/", b"")
        archive.writestr("word/document.xml", "document")

    validate_docx_archive(stream.getvalue(), max_uncompressed_bytes=2_048)




class _FakeClamSocket:
    def __init__(self, reply: bytes) -> None:
        self.reply = reply
        self.chunks: list[bytes] = []
        self.timeout: float | None = None

    def __enter__(self) -> _FakeClamSocket:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def sendall(self, chunk: bytes) -> None:
        self.chunks.append(bytes(chunk))

    def recv(self, _: int) -> bytes:
        result, self.reply = self.reply, b""
        return result


def test_clamav_instream_clean_verdict_uses_loopback_and_bounded_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClamSocket(b"stream: OK\x00")
    connect = Mock(return_value=client)
    monkeypatch.setattr("northstar_api.services.object_store.socket.create_connection", connect)
    content = b"a" * (70 * 1024)

    scan_with_clamav_instream(content, port=3310, timeout_seconds=60)

    connect.assert_called_once_with(("127.0.0.1", 3310), timeout=60)
    assert client.timeout == 60
    assert client.chunks[0] == b"zINSTREAM\x00"
    assert client.chunks[-1] == b"\x00" * 4
    assert b"".join(client.chunks[2:-1:2]) == content
    assert len(client.chunks[1]) == 4
    assert int.from_bytes(client.chunks[1], "big") == 64 * 1024


@pytest.mark.parametrize(
    ("reply", "error_type"),
    [
        (b"stream: Eicar-Test-Signature FOUND\x00", InvalidUpload),
        (b"stream: ERROR\x00", ObjectStoreUnavailable),
        (b"", ObjectStoreUnavailable),
        (b"stream: OK", ObjectStoreUnavailable),
    ],
)
def test_clamav_rejects_infected_missing_and_incomplete_verdicts(
    monkeypatch: pytest.MonkeyPatch, reply: bytes, error_type: type[Exception]
) -> None:
    monkeypatch.setattr(
        "northstar_api.services.object_store.socket.create_connection",
        Mock(return_value=_FakeClamSocket(reply)),
    )
    with pytest.raises(error_type):
        scan_with_clamav_instream(b"untrusted bytes", port=3310, timeout_seconds=60)


def test_clamav_connection_failure_is_not_a_clean_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "northstar_api.services.object_store.socket.create_connection",
        Mock(side_effect=ConnectionRefusedError("scanner offline")),
    )
    with pytest.raises(ObjectStoreUnavailable, match="scanner is unavailable"):
        scan_with_clamav_instream(b"untrusted bytes", port=3310, timeout_seconds=60)


@pytest.mark.parametrize("app_env", ["staging", "production"])
async def test_protected_environment_requires_scanner_before_object_copy(
    monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"untrusted file")
    configured = get_settings().model_copy(
        update={"app_env": app_env, "knowledge_clamav_enabled": False}
    )
    store = ObjectStore(configured)
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="Malware scanner is required"):
        await store.promote_staged(tenant_id, f"staging/{tenant_id}/2026/10/note.txt")
    assert client.copied_to is None


async def test_scanner_detection_prevents_copy_without_purging_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"untrusted file")
    configured = get_settings().model_copy(update={"knowledge_clamav_enabled": True})
    store = ObjectStore(configured)
    monkeypatch.setattr(store, "_client", lambda **_: client)
    scan = Mock(side_effect=InvalidUpload("Uploaded file failed malware scan"))
    monkeypatch.setattr(
        "northstar_api.services.object_store.scan_with_clamav_instream", scan
    )
    key = f"staging/{tenant_id}/2026/10/note.txt"

    with pytest.raises(InvalidUpload, match="failed malware scan"):
        await store.promote_staged(tenant_id, key)
    scan.assert_called_once_with(
        client.data,
        port=configured.knowledge_clamav_port,
        timeout_seconds=configured.knowledge_clamav_timeout_seconds,
    )
    assert client.copied_to is None
    assert key not in client.deleted


async def test_promotion_rejects_misdeclared_bytes_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"not a PDF", content_type="application/pdf")
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(InvalidUpload, match="declared file type"):
        await store.promote_staged(tenant_id, f"staging/{tenant_id}/2026/09/example.pdf")

    assert client.copied_to is None


@pytest.mark.parametrize("source_version_id", [None, "", "null", "version-1"])
async def test_aws_download_uses_only_the_head_version(
    monkeypatch: pytest.MonkeyPatch, source_version_id: str | None
) -> None:
    client = _FakeS3(b"verified object", source_version_id=source_version_id)
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    if source_version_id == "version-1":
        data, _ = await store.download("knowledge/example.txt")
        assert data == b"verified object"
        assert client.read_arguments == [{"Key": "knowledge/example.txt", "VersionId": "version-1"}]
    else:
        with pytest.raises(ObjectStoreUnavailable, match="immutable version"):
            await store.download("knowledge/example.txt")
        assert client.read_arguments == []


async def test_aws_download_reads_the_persisted_approved_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3(b"verified object", source_version_id="newer-version")
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    data, _ = await store.download("knowledge/example.txt", expected_version_id="approved-version")
    assert data == b"verified object"
    assert client.head_arguments == [{"Key": "knowledge/example.txt", "VersionId": "approved-version"}]
    assert client.read_arguments == [{"Key": "knowledge/example.txt", "VersionId": "approved-version"}]


async def test_aws_download_rejects_mismatched_approved_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3(b"verified object")
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    def wrong_head(*, Bucket: str, Key: str, **kwargs: Any) -> dict[str, Any]:  # noqa: N803
        result = _FakeS3.head_object(client, Bucket=Bucket, Key=Key, **kwargs)
        result["VersionId"] = "different-version"
        return result

    client.head_object = wrong_head  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreUnavailable, match="different approved version"):
        await store.download("knowledge/example.txt", expected_version_id="approved-version")
    assert client.read_arguments == []


async def test_aws_workspace_upload_keys_cannot_cross_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    workspace_a = uuid4()
    workspace_b = uuid4()
    client = _FakeS3(b"payload")
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)
    key, _, _, _ = await store.presign_post(
        tenant_id=tenant_id,
        workspace_id=workspace_a,
        filename="note.txt",
        content_type="text/plain",
        size_bytes=len(client.data),
        checksum_sha256=client.checksum,
    )
    assert key.startswith(f"staging/{tenant_id}/{workspace_a}/")

    with pytest.raises(InvalidUpload, match="does not belong to this workspace"):
        await store.promote_staged(tenant_id, key, workspace_id=workspace_b)
    assert client.copied_to is None


async def test_aws_workspace_is_required_for_staging_key_creation_and_promotion() -> None:
    tenant_id = uuid4()
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )

    with pytest.raises(InvalidUpload, match="authorized workspace"):
        await store.presign_post(
            tenant_id=tenant_id,
            filename="note.txt",
            content_type="text/plain",
            size_bytes=4,
            checksum_sha256=hashlib.sha256(b"note").hexdigest(),
        )
    with pytest.raises(InvalidUpload, match="authorized workspace"):
        await store.promote_staged(tenant_id, f"staging/{tenant_id}/legacy.txt")


async def test_static_download_keeps_unversioned_get(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeS3(b"local object", source_version_id=None)
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    assert (await store.download("knowledge/local.txt"))[0] == b"local object"
    assert client.read_arguments == [{"Key": "knowledge/local.txt"}]


@pytest.mark.parametrize("etag", [None, "", "unquoted", '"contains\nnewline"'])
async def test_promotion_rejects_a_missing_or_malformed_etag(
    monkeypatch: pytest.MonkeyPatch,
    etag: str | None,
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(b"payload", etag=etag)
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(InvalidUpload, match="valid ETag"):
        await store.promote_staged(tenant_id, f"staging/{tenant_id}/2026/09/example.txt")

    assert client.copied_to is None


async def test_promotion_size_mismatch_deletes_the_exact_copied_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    client = _FakeS3(
        b"payload",
        copied_size=999,
        copied_version_id="copied-version-7",
    )
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)
    staging_key = f"staging/{tenant_id}/2026/09/example.txt"

    with pytest.raises(ObjectStoreUnavailable, match="did not preserve"):
        await store.promote_staged(tenant_id, staging_key)

    assert client.copied_to is not None
    assert client.delete_arguments == [{"Key": client.copied_to, "VersionId": "copied-version-7"}]


async def test_purge_exact_removes_all_versions_and_markers_across_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    key = f"knowledge/{tenant_id}/2026/09/policy.txt"
    neighbour = f"{key}.backup"
    client = _FakeVersionedS3(
        [
            {
                "Versions": [
                    {"Key": key, "VersionId": "v3"},
                    {"Key": neighbour, "VersionId": "other-v1"},
                ],
                "DeleteMarkers": [{"Key": key, "VersionId": "marker-2"}],
            },
            {
                "Versions": [{"Key": key, "VersionId": "v1"}],
                "DeleteMarkers": [
                    {"Key": key, "VersionId": "marker-1"},
                    {"Key": neighbour, "VersionId": "other-marker"},
                ],
            },
        ]
    )
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    deleted = await store.purge_exact(key)

    assert deleted == 4
    assert client.paginator.arguments == {"Bucket": get_settings().s3_bucket, "Prefix": key}
    assert client.deleted_batches == [
        [
            {"Key": key, "VersionId": "v3"},
            {"Key": key, "VersionId": "marker-2"},
            {"Key": key, "VersionId": "v1"},
            {"Key": key, "VersionId": "marker-1"},
        ]
    ]
    assert client.deleted_unversioned == []


async def test_purge_exact_uses_plain_delete_for_unversioned_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"knowledge/{uuid4()}/2026/09/policy.txt"
    client = _FakeVersionedS3([])
    client.get_bucket_versioning = lambda **_: {}
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    deleted = await store.purge_exact(key)

    assert deleted == 1
    assert client.deleted_unversioned == [key]
    assert client.deleted_batches == []


@pytest.mark.parametrize("status", [None, "Suspended"])
async def test_aws_purge_rejects_bucket_without_enabled_versioning(
    monkeypatch: pytest.MonkeyPatch, status: str | None
) -> None:
    key = f"knowledge/{uuid4()}/2026/09/policy.txt"
    client = _FakeVersionedS3([])
    client.get_bucket_versioning = lambda **_: {"Status": status} if status else {}
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="requires enabled bucket versioning"):
        await store.purge_exact(key)
    assert client.deleted_unversioned == []
    assert client.deleted_batches == []


@pytest.mark.parametrize("status", [None, "Suspended"])
async def test_aws_extraction_purge_rejects_bucket_without_enabled_versioning(
    monkeypatch: pytest.MonkeyPatch, status: str | None
) -> None:
    client = _FakeVersionedS3([])
    client.get_bucket_versioning = lambda **_: {"Status": status} if status else {}
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="requires enabled bucket versioning"):
        await store.purge_prefix(f"extractions/{uuid4()}/{uuid4()}/")
    assert client.deleted_batches == []


async def test_aws_rollback_deletes_only_the_promoted_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3(b"payload")
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)
    key = f"knowledge/{uuid4()}/{uuid4()}/2026/10/policy.txt"

    await store.rollback_promoted(key, version_id="copied-version-1")
    assert client.delete_arguments == [{"Key": key, "VersionId": "copied-version-1"}]


async def test_aws_rollback_without_receipt_never_deletes_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeS3(b"payload")
    store = ObjectStore(
        Settings(
            s3_auth_mode="aws-default",
            s3_access_key_id=None,
            s3_secret_access_key=None,
            s3_endpoint_url=None,
            s3_public_endpoint_url=None,
        )
    )
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="requires its copied version receipt"):
        await store.rollback_promoted(f"knowledge/{uuid4()}/file.txt", version_id=None)
    assert client.deleted == []


async def test_static_rollback_keeps_exact_key_purge(monkeypatch: pytest.MonkeyPatch) -> None:
    key = f"knowledge/{uuid4()}/2026/10/policy.txt"
    client = _FakeVersionedS3([{"Versions": [{"Key": key, "VersionId": "v1"}]}])
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    await store.rollback_promoted(key, version_id=None)
    assert client.deleted_batches == [[{"Key": key, "VersionId": "v1"}]]


async def test_extraction_purge_rejects_version_created_after_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"extractions/{uuid4()}/{uuid4()}/"
    key = f"{prefix}v0001.zip"
    client = _FakeVersionedS3([{"Versions": [{"Key": key, "VersionId": "v1"}]}])
    original_delete = client.delete_objects

    def delete_then_add(*, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        result = original_delete(Bucket=Bucket, Delete=Delete)
        client.paginator.pages[0]["Versions"].append({"Key": key, "VersionId": "v2"})
        return result

    client.delete_objects = delete_then_add  # type: ignore[method-assign]
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="still contains extraction evidence"):
        await store.purge_prefix(prefix)
    assert client.deleted_batches == [[{"Key": key, "VersionId": "v1"}]]
    assert client.paginator.calls == 2


async def test_purge_exact_respects_s3_multi_delete_batch_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"knowledge/{uuid4()}/2026/09/policy.txt"
    versions = [{"Key": key, "VersionId": f"v{index}"} for index in range(1_001)]
    client = _FakeVersionedS3([{"Versions": versions}])
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    deleted = await store.purge_exact(key)

    assert deleted == 1_001
    assert [len(batch) for batch in client.deleted_batches] == [1_000, 1]


async def test_purge_exact_rejects_a_version_created_after_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"knowledge/{uuid4()}/2026/09/policy.txt"
    client = _FakeVersionedS3([{"Versions": [{"Key": key, "VersionId": "v1"}]}])
    original_delete = client.delete_objects

    def delete_then_add(*, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        result = original_delete(Bucket=Bucket, Delete=Delete)
        client.paginator.pages[0]["Versions"].append({"Key": key, "VersionId": "v2"})
        return result

    client.delete_objects = delete_then_add  # type: ignore[method-assign]
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="still contains the purged key"):
        await store.purge_exact(key)
    assert client.deleted_batches == [[{"Key": key, "VersionId": "v1"}]]
    assert client.paginator.calls == 2


async def test_purge_exact_surfaces_partial_version_delete_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = f"knowledge/{uuid4()}/2026/09/policy.txt"
    client = _FakeVersionedS3([{"Versions": [{"Key": key, "VersionId": "v1"}]}])
    client.delete_objects = lambda **_: {"Errors": [{"Key": key, "VersionId": "v1"}]}
    store = ObjectStore(get_settings())
    monkeypatch.setattr(store, "_client", lambda **_: client)

    with pytest.raises(ObjectStoreUnavailable, match="every object version"):
        await store.purge_exact(key)
