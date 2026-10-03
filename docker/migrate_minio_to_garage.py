"""Copy Maia's legacy MinIO media buckets into the local Garage S3 service."""

from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from collections.abc import Iterator
from typing import Any

import boto3
from botocore.config import Config


BUCKETS = ("maia-listing-media", "maia-listing-renditions")
METADATA_HEADERS = (
    "CacheControl",
    "ContentDisposition",
    "ContentEncoding",
    "ContentLanguage",
    "ContentType",
    "Expires",
)


def client(prefix: str) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ[f"{prefix}_S3_ENDPOINT_URL"],
        region_name="us-east-1",
        aws_access_key_id=os.environ[f"{prefix}_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ[f"{prefix}_S3_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def keys(s3: Any, bucket: str) -> Iterator[dict[str, Any]]:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        yield from page.get("Contents", [])


def copy_object(source: Any, destination: Any, bucket: str, key: str) -> int:
    response = source.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as content:
            while chunk := body.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                content.write(chunk)
            checksum = digest.digest()
            metadata = dict(response.get("Metadata") or {})
            metadata["maia-sha256"] = checksum.hex()
            content.seek(0)
            put: dict[str, Any] = {
                "Bucket": bucket,
                "Key": key,
                "Body": content,
                "ContentLength": size,
                "ChecksumSHA256": base64.b64encode(checksum).decode("ascii"),
                "Metadata": metadata,
            }
            for header in METADATA_HEADERS:
                if response.get(header) is not None:
                    put[header] = response[header]
            destination.put_object(**put)
    finally:
        body.close()

    verified = destination.head_object(Bucket=bucket, Key=key)
    if verified["ContentLength"] != size:
        raise RuntimeError(f"Length mismatch after copying {bucket}/{key}")
    copied_checksum = (verified.get("Metadata") or {}).get("maia-sha256")
    if copied_checksum != checksum.hex():
        raise RuntimeError(f"SHA-256 mismatch after copying {bucket}/{key}")
    return size


def main() -> None:
    source = client("SOURCE")
    destination = client("DESTINATION")
    total_objects = 0
    total_bytes = 0
    for bucket in BUCKETS:
        count = 0
        size = 0
        for item in keys(source, bucket):
            object_size = copy_object(source, destination, bucket, item["Key"])
            count += 1
            size += object_size
        total_objects += count
        total_bytes += size
        print(f"Copied {count} objects from {bucket} ({size} bytes).")
    print(f"Verified {total_objects} objects ({total_bytes} bytes) across both buckets.")


if __name__ == "__main__":
    main()
