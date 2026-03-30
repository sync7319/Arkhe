"""
AWS S3 storage backend implementation.
Features: error handling, structured logging, health checks, presigned URLs.
"""
import os
import time

import aioboto3

from integrations.base import BaseStorage
from integrations.exceptions import (
    BackendConnectionError,
    BackendStorageError,
)
from integrations.logging import get_logger

log = get_logger("aws-s3")


class S3Storage(BaseStorage):
    def __init__(self):
        self.bucket = os.getenv("AWS_S3_BUCKET", "arkhe-results-prod")
        self.region = os.getenv("AWS_REGION", "us-east-1")

        # AWS credentials come from environment or IAM role
        # If running on EC2, no explicit credentials needed (uses IAM role)
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        log.debug(
            "Initializing S3 storage",
            bucket=self.bucket,
            region=self.region,
            credentials="IAM role" if not self.access_key else "explicit keys"
        )

        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    async def init(self) -> None:
        """Initialize S3 connection and verify bucket exists."""
        log.operation_start("init", bucket=self.bucket, region=self.region)

        try:
            start = time.time()
            async with self.session.client("s3") as s3:
                await s3.head_bucket(Bucket=self.bucket)
            duration = (time.time() - start) * 1000

            log.operation_success("init", duration_ms=duration, bucket=self.bucket)
        except Exception as e:
            log.operation_error("init", e, bucket=self.bucket)
            raise BackendConnectionError(
                "aws-s3",
                f"Failed to access bucket '{self.bucket}': {str(e)}",
                {"bucket": self.bucket, "region": self.region, "error_type": type(e).__name__}
            )

    async def health_check(self) -> bool:
        """Check if S3 is responsive."""
        try:
            async with self.session.client("s3") as s3:
                await s3.head_bucket(Bucket=self.bucket)
            return True
        except Exception as e:
            log.warning(f"Health check failed", exception=e)
            return False

    async def upload_file(self, cache_key: str, filename: str, content: bytes) -> str:
        """
        Upload a file to S3.
        Returns the public URL (or presigned URL for private files).
        """
        key = f"{cache_key}/{filename}"
        log.operation_start("upload_file", cache_key=cache_key, filename=filename, size_bytes=len(content))

        try:
            start = time.time()

            async with self.session.client("s3") as s3:
                await s3.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=content,
                    ContentType=self._get_content_type(filename),
                    ACL="public-read",  # Make publicly readable
                )

            # Return public URL
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"

            duration = (time.time() - start) * 1000
            log.operation_success(
                "upload_file",
                duration_ms=duration,
                cache_key=cache_key,
                filename=filename,
                size_bytes=len(content)
            )

            return url
        except Exception as e:
            log.operation_error("upload_file", e, cache_key=cache_key, filename=filename)
            raise BackendStorageError(
                "aws-s3",
                "upload",
                filename,
                str(e),
                {"cache_key": cache_key, "size_bytes": len(content), "bucket": self.bucket}
            )

    async def upload_text(self, cache_key: str, filename: str, content: str) -> str:
        """
        Upload text file to S3.
        Returns the public URL.
        """
        return await self.upload_file(cache_key, filename, content.encode("utf-8"))

    async def get_signed_url(self, cache_key: str, filename: str, expires_in: int = 3600) -> str:
        """
        Generate a presigned URL for temporary access.
        expires_in: seconds until URL expires (default 1 hour).
        """
        key = f"{cache_key}/{filename}"
        log.operation_start("get_signed_url", cache_key=cache_key, filename=filename, expires_in=expires_in)

        try:
            start = time.time()

            async with self.session.client("s3") as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=expires_in,
                )

            duration = (time.time() - start) * 1000
            log.operation_success("get_signed_url", duration_ms=duration, cache_key=cache_key, filename=filename)

            return url
        except Exception as e:
            log.operation_error("get_signed_url", e, cache_key=cache_key, filename=filename)
            raise BackendStorageError(
                "aws-s3",
                "get_signed_url",
                filename,
                str(e),
                {"cache_key": cache_key, "bucket": self.bucket}
            )

    async def delete_analysis_files(self, cache_key: str) -> None:
        """
        Delete all files for a given analysis.
        """
        log.operation_start("delete_analysis_files", cache_key=cache_key)

        try:
            start = time.time()

            async with self.session.client("s3") as s3:
                # List all objects with this cache_key prefix
                paginator = s3.get_paginator("list_objects_v2")
                pages = paginator.paginate(Bucket=self.bucket, Prefix=cache_key)

                delete_list = []
                async for page in pages:
                    if "Contents" in page:
                        for obj in page["Contents"]:
                            delete_list.append({"Key": obj["Key"]})

                # Delete all files
                if delete_list:
                    await s3.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": delete_list},
                    )

                    duration = (time.time() - start) * 1000
                    log.operation_success(
                        "delete_analysis_files",
                        duration_ms=duration,
                        cache_key=cache_key,
                        count=len(delete_list)
                    )
                else:
                    log.debug("delete_analysis_files - no files found", cache_key=cache_key)
        except Exception as e:
            log.operation_error("delete_analysis_files", e, cache_key=cache_key)
            raise BackendStorageError(
                "aws-s3",
                "delete",
                cache_key,
                str(e),
                {"cache_key": cache_key, "bucket": self.bucket}
            )

    def _get_content_type(self, filename: str) -> str:
        """Infer Content-Type from filename."""
        ext = filename.lower().split(".")[-1]
        types = {
            "md": "text/markdown",
            "html": "text/html",
            "json": "application/json",
            "zip": "application/zip",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return types.get(ext, "text/plain")
