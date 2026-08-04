"""S3/MinIO-backed object storage for uploaded documents."""

from __future__ import annotations

import asyncio
import logging

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
            config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
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

    async def upload_file(self, content: bytes, object_name: str, content_type: str | None = None) -> bool:
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


storage = S3StorageService()
