"""S3-compatible Listing Media storage and the legacy migration adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Protocol, cast

import boto3
from botocore.config import Config

from realestate.config import Settings
from realestate.domain.catalog.storage import (
    MediaStorage,
    MediaStorageError,
    MediaStorageHealth,
)


class _S3Client(Protocol):
    def put_object(self, **kwargs: object) -> object: ...

    def delete_object(self, **kwargs: object) -> object: ...

    def get_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def head_bucket(self, **kwargs: object) -> object: ...


def _key(value: str) -> str:
    """Refuse ambiguous keys before either Adapter sees them."""
    path = PurePosixPath(value)
    if not value or value.startswith("/") or ".." in path.parts or "." in path.parts:
        raise MediaStorageError("La clave de almacenamiento no es válida.")
    return value


class S3MediaStorage:
    """Private S3 objects with integrity metadata and a separate cache bucket."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        originals_bucket: str,
        cache_bucket: str,
        access_key_id: str,
        secret_access_key: str,
        client: _S3Client | None = None,
    ) -> None:
        required = {
            "endpoint_url": endpoint_url,
            "region": region,
            "originals_bucket": originals_bucket,
            "cache_bucket": cache_bucket,
            "access_key_id": access_key_id,
            "secret_access_key": secret_access_key,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise MediaStorageError(
                "Falta configuración obligatoria del almacenamiento de medios: "
                + ", ".join(sorted(missing))
                + "."
            )
        self._endpoint_url = endpoint_url.rstrip("/")
        self._originals_bucket = originals_bucket
        self._cache_bucket = cache_bucket
        self._client = client or cast(
            _S3Client,
            boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                ),
            ),
        )

    async def put(self, key: str, content: bytes) -> None:
        checked = _key(key)
        checksum = hashlib.sha256(content).digest()
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._originals_bucket,
                Key=checked,
                Body=content,
                ChecksumSHA256=base64.b64encode(checksum).decode("ascii"),
                Metadata={"maia-sha256": checksum.hex()},
            )
        except Exception as exc:
            raise MediaStorageError(
                "No se pudo guardar la fotografía en object storage."
            ) from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._originals_bucket,
                Key=_key(key),
            )
        except Exception as exc:
            raise MediaStorageError(
                "No se pudo eliminar la fotografía de object storage."
            ) from exc

    async def read(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._originals_bucket,
                Key=_key(key),
                ChecksumMode="ENABLED",
            )
            body = response.get("Body")
            read = getattr(body, "read", None)
            if not callable(read):
                raise TypeError("S3 did not return a readable body")
            content = read()
            if not isinstance(content, bytes):
                raise TypeError("S3 returned a non-byte body")
            metadata = response.get("Metadata", {})
            expected = (
                metadata.get("maia-sha256")
                if isinstance(metadata, Mapping)
                else None
            )
            if isinstance(expected, str) and hashlib.sha256(content).hexdigest() != expected:
                raise MediaStorageError(
                    "La integridad de la fotografía almacenada no coincide."
                )
            return content
        except MediaStorageError:
            raise
        except Exception as exc:
            raise MediaStorageError(
                "No se pudo leer la fotografía autorizada."
            ) from exc

    async def purge_cache(self, keys: tuple[str, ...]) -> None:
        try:
            for key in keys:
                await asyncio.to_thread(
                    self._client.delete_object,
                    Bucket=self._cache_bucket,
                    Key=_key(key),
                )
        except Exception as exc:
            raise MediaStorageError(
                "No se pudo purgar la caché derivada de la fotografía."
            ) from exc

    async def check_health(self) -> MediaStorageHealth:
        try:
            await asyncio.gather(
                asyncio.to_thread(
                    self._client.head_bucket, Bucket=self._originals_bucket
                ),
                asyncio.to_thread(self._client.head_bucket, Bucket=self._cache_bucket),
            )
        except Exception as exc:
            return MediaStorageHealth(
                False,
                f"Object storage no está disponible en {self._endpoint_url}: "
                f"{type(exc).__name__}.",
            )
        return MediaStorageHealth(
            True,
            "Object storage S3-compatible disponible; buckets privados de "
            "originales y derivados accesibles.",
        )


class LocalMediaStorage:
    """Filesystem Adapter retained only to read a legacy volume during migration."""

    def __init__(self, root: Path, cache_root: Path) -> None:
        self._root = root.resolve()
        self._cache_root = cache_root.resolve()

    async def put(self, key: str, content: bytes) -> None:
        await asyncio.to_thread(self._write, self._path(self._root, key), content)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(self._root, key).unlink, missing_ok=True)

    async def read(self, key: str) -> bytes:
        path = self._path(self._root, key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise MediaStorageError("No se pudo leer la fotografía autorizada.") from exc

    async def purge_cache(self, keys: tuple[str, ...]) -> None:
        paths = [self._path(self._cache_root, key) for key in keys]
        await asyncio.to_thread(self._unlink_all, paths)

    async def check_health(self) -> MediaStorageHealth:
        exists = await asyncio.to_thread(self._root.is_dir)
        return MediaStorageHealth(
            exists,
            "El volumen legado está disponible para migración."
            if exists
            else "El volumen legado no está disponible.",
        )

    @staticmethod
    def _unlink_all(paths: list[Path]) -> None:
        for path in paths:
            path.unlink(missing_ok=True)

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _path(root: Path, key: str) -> Path:
        checked = _key(key)
        candidate = (root / checked).resolve()
        if candidate != root and root not in candidate.parents:
            raise MediaStorageError("La clave de almacenamiento salió de su raíz.")
        return candidate


def media_storage_from_settings(settings: Settings) -> MediaStorage:
    """Build the one runtime Adapter without leaking provider details inward."""
    return S3MediaStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        originals_bucket=settings.object_storage_originals_bucket,
        cache_bucket=settings.object_storage_cache_bucket,
        access_key_id=settings.object_storage_access_key_id,
        secret_access_key=settings.object_storage_secret_access_key,
    )
