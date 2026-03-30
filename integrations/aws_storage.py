"""
AWS S3 storage backend implementation.
"""
import os
import logging
from datetime import timedelta

import aioboto3

from integrations.base import BaseStorage

logger = logging.getLogger("arkhe.aws_storage")


class S3Storage(BaseStorage):
    def __init__(self):
        self.bucket = os.getenv("AWS_S3_BUCKET", "arkhe-results-prod")
        self.region = os.getenv("AWS_REGION", "us-east-1")

        # AWS credentials come from environment or IAM role
        # If running on EC2, no explicit credentials needed (uses IAM role)
        self.access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        self.session = aioboto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )

    async def init(self) -> None:
        """Initialize S3 connection and verify bucket exists."""
        async with self.session.client("s3") as s3:
            try:
                await s3.head_bucket(Bucket=self.bucket)
                logger.info(f"[s3_storage] Connected to bucket '{self.bucket}'")
            except Exception as e:
                logger.warning(f"[s3_storage] Could not verify bucket: {e}")
                logger.warning(f"[s3_storage] Create bucket '{self.bucket}' in AWS console")

    async def upload_file(self, cache_key: str, filename: str, content: bytes) -> str:
        """
        Upload a file to S3.
        Returns the public URL (or presigned URL for private files).
        """
        key = f"{cache_key}/{filename}"

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
        logger.debug(f"[s3_storage] Uploaded {key} → {url}")
        return url

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

        async with self.session.client("s3") as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        logger.debug(f"[s3_storage] Presigned URL for {key} expires in {expires_in}s")
        return url

    async def delete_analysis_files(self, cache_key: str) -> None:
        """
        Delete all files for a given analysis.
        """
        try:
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
                    logger.info(f"[s3_storage] Deleted {len(delete_list)} files for {cache_key}")
        except Exception as e:
            logger.warning(f"[s3_storage] Could not delete files for {cache_key}: {e}")

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
