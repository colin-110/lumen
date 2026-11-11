"""Object storage for uploaded documents: S3-compatible, or the local disk.

`STORAGE_BACKEND=local` keeps files under `LOCAL_STORAGE_DIR`. On a single
server that is exactly as durable as running an S3 server on the same disk,
and it saves a container. `s3` (the default) works with AWS S3, R2 or any
S3-compatible endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3StorageService:
    def __init__(self) -> None:
        self.bucket = settings.S3_BUCKET
        # boto3.client() itself makes no network calls — safe to construct
        # at import time. Bucket verification is a real network call and is
        # deliberately NOT done here; see ensure_bucket(), called explicitly
        # from app startup / worker warm-up so an unreachable store degrades
        # to a clear runtime error on first use instead of crashing import
        # (which would break `pytest`, migrations, and anything else that
        # imports the app package without live infra).
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=BotoConfig(
                signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}
            ),
        )

    def _ensure_bucket_sync(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)
            logger.info("Created storage bucket %s", self.bucket)

    async def ensure_bucket(self) -> bool:
        """Verify (and create if missing) the target bucket. Returns False
        instead of raising on any failure — including connection-level
        failures like a down/unreachable MinIO, which botocore does NOT
        raise as `ClientError` — so callers can log and continue rather
        than crash the whole process at startup."""
        try:
            await asyncio.to_thread(self._ensure_bucket_sync)
            return True
        except Exception:
            logger.error("Could not create/verify bucket %s", self.bucket, exc_info=True)
            return False

    def _upload(self, content: bytes, object_name: str, content_type: str | None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.bucket, Key=object_name, Body=content, **extra)

    def _download(self, object_name: str, download_path: str) -> None:
        self._client.download_file(self.bucket, object_name, download_path)

    def _delete(self, object_name: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=object_name)

    async def upload_file(
        self, content: bytes, object_name: str, content_type: str | None = None
    ) -> bool:
        try:
            await asyncio.to_thread(self._upload, content, object_name, content_type)
            return True
        except Exception:
            logger.error("Error uploading %s", object_name, exc_info=True)
            return False

    async def download_file(self, object_name: str, download_path: str) -> bool:
        try:
            await asyncio.to_thread(self._download, object_name, download_path)
            return True
        except Exception:
            logger.error("Error downloading %s", object_name, exc_info=True)
            return False

    async def delete_file(self, object_name: str) -> bool:
        try:
            await asyncio.to_thread(self._delete, object_name)
            return True
        except Exception:
            logger.error("Error deleting %s", object_name, exc_info=True)
            return False


class LocalStorageService:
    """Same interface as S3StorageService, backed by a directory."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, object_name: str) -> Path:
        # Object names embed the uploaded filename, which the client controls.
        # Resolve and confirm the result is still under the root so a name
        # like "../../etc/cron.d/x" can never read or write outside it.
        path = (self.root / object_name).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError(f"Object name escapes the storage root: {object_name!r}")
        return path

    async def ensure_bucket(self) -> bool:
        try:
            await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
            return True
        except Exception:
            logger.error("Could not create storage directory %s", self.root, exc_info=True)
            return False

    def _upload(self, content: bytes, object_name: str) -> None:
        path = self._path(object_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a crash mid-write never leaves a truncated file
        # under the real name for ingestion to pick up.
        tmp = path.with_name(path.name + ".partial")
        tmp.write_bytes(content)
        tmp.replace(path)

    def _download(self, object_name: str, download_path: str) -> None:
        shutil.copyfile(self._path(object_name), download_path)

    def _delete(self, object_name: str) -> None:
        path = self._path(object_name)
        path.unlink(missing_ok=True)
        # Drop the now-empty per-document directory; leave anything non-empty.
        for parent in (path.parent, path.parent.parent):
            if parent != self.root:
                try:
                    parent.rmdir()
                except OSError:
                    break

    async def upload_file(
        self, content: bytes, object_name: str, content_type: str | None = None
    ) -> bool:
        try:
            await asyncio.to_thread(self._upload, content, object_name)
            return True
        except Exception:
            logger.error("Error storing %s", object_name, exc_info=True)
            return False

    async def download_file(self, object_name: str, download_path: str) -> bool:
        try:
            await asyncio.to_thread(self._download, object_name, download_path)
            return True
        except Exception:
            logger.error("Error reading %s", object_name, exc_info=True)
            return False

    async def delete_file(self, object_name: str) -> bool:
        try:
            await asyncio.to_thread(self._delete, object_name)
            return True
        except Exception:
            logger.error("Error deleting %s", object_name, exc_info=True)
            return False


storage: S3StorageService | LocalStorageService = (
    LocalStorageService(settings.LOCAL_STORAGE_DIR)
    if settings.STORAGE_BACKEND == "local"
    else S3StorageService()
)
