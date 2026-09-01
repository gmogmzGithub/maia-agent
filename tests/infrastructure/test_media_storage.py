"""Contract of the production S3-compatible Listing Media Adapter."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from realestate.domain.catalog.storage import MediaStorageError
from realestate.infrastructure.media_storage import S3MediaStorage


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}
        self.available = True
        self.last_checksum: str | None = None

    def put_object(self, **kwargs: object) -> object:
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        body = kwargs["Body"]
        metadata = kwargs["Metadata"]
        assert isinstance(bucket, str)
        assert isinstance(key, str)
        assert isinstance(body, bytes)
        assert isinstance(metadata, dict)
        self.last_checksum = str(kwargs["ChecksumSHA256"])
        self.objects[(bucket, key)] = (body, metadata)
        return {}

    def delete_object(self, **kwargs: object) -> object:
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        assert isinstance(bucket, str)
        assert isinstance(key, str)
        self.objects.pop((bucket, key), None)
        return {}

    def get_object(self, **kwargs: object) -> Mapping[str, object]:
        bucket = kwargs["Bucket"]
        key = kwargs["Key"]
        assert kwargs["ChecksumMode"] == "ENABLED"
        assert isinstance(bucket, str)
        assert isinstance(key, str)
        body, metadata = self.objects[(bucket, key)]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def head_bucket(self, **kwargs: object) -> object:
        if not self.available:
            raise ConnectionError("offline")
        assert kwargs["Bucket"] in {"originals", "renditions"}
        return {}


def storage(client: FakeS3) -> S3MediaStorage:
    return S3MediaStorage(
        endpoint_url="http://objects.test:9000",
        region="us-east-1",
        originals_bucket="originals",
        cache_bucket="renditions",
        access_key_id="test-access",
        secret_access_key="test-secret",
        client=client,
    )


async def test_s3_storage_writes_integrity_metadata_reads_and_deletes() -> None:
    client = FakeS3()
    adapter = storage(client)

    await adapter.put("org/listing/photo.jpg", b"photograph")

    assert client.last_checksum is not None
    assert await adapter.read("org/listing/photo.jpg") == b"photograph"
    await adapter.delete("org/listing/photo.jpg")
    with pytest.raises(MediaStorageError):
        await adapter.read("org/listing/photo.jpg")


async def test_s3_storage_refuses_invalid_keys_before_calling_provider() -> None:
    adapter = storage(FakeS3())

    with pytest.raises(MediaStorageError):
        await adapter.put("../another-organization/photo.jpg", b"photograph")
    with pytest.raises(MediaStorageError):
        await adapter.purge_cache(("/absolute/thumb.webp",))


async def test_s3_storage_detects_corrupted_bytes() -> None:
    client = FakeS3()
    adapter = storage(client)
    await adapter.put("org/listing/photo.jpg", b"photograph")
    _, metadata = client.objects[("originals", "org/listing/photo.jpg")]
    client.objects[("originals", "org/listing/photo.jpg")] = (b"corrupted", metadata)

    with pytest.raises(MediaStorageError, match="integridad"):
        await adapter.read("org/listing/photo.jpg")


async def test_s3_storage_health_requires_both_private_buckets() -> None:
    client = FakeS3()
    adapter = storage(client)

    assert (await adapter.check_health()).ok is True
    client.available = False
    report = await adapter.check_health()
    assert report.ok is False
    assert "objects.test" in report.detail


def test_s3_storage_refuses_incomplete_configuration() -> None:
    with pytest.raises(MediaStorageError, match="access_key_id"):
        S3MediaStorage(
            endpoint_url="http://objects.test:9000",
            region="us-east-1",
            originals_bucket="originals",
            cache_bucket="renditions",
            access_key_id="",
            secret_access_key="test-secret",
            client=FakeS3(),
        )


def test_sandbox_product_policy_is_bucket_scoped_without_wildcard_resources() -> None:
    policy_path = Path(__file__).parents[2] / "docker/minio-media-policy.json"
    policy = json.loads(policy_path.read_text())
    statements = policy["Statement"]
    resources = {
        resource
        for statement in statements
        for resource in statement["Resource"]
    }
    actions = {
        action
        for statement in statements
        for action in statement["Action"]
    }

    assert "*" not in resources
    assert resources == {
        "arn:aws:s3:::maia-listing-media",
        "arn:aws:s3:::maia-listing-media/*",
        "arn:aws:s3:::maia-listing-renditions",
        "arn:aws:s3:::maia-listing-renditions/*",
    }
    assert actions == {
        "s3:GetBucketLocation",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
    }
