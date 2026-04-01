"""
Supabase Storage backend implementation.
Features: error handling, structured logging, health checks.
"""
import os
import time

from supabase import AsyncClient, create_client

from integrations.base import BaseStorage
from integrations.exceptions import (
    BackendConnectionError,
    BackendStorageError,
)
from integrations.logging import get_logger

log = get_logger("supabase-storage")


class SupabaseStorage(BaseStorage):
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
        self.bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "arkhe-results")

        if not self.url or not self.key:
            log.error(
                "Missing Supabase credentials",
                SUPABASE_URL=bool(self.url),
                SUPABASE_ANON_KEY=bool(self.key)
            )
            raise BackendConnectionError(
                "supabase-storage",
                "Missing SUPABASE_URL or SUPABASE_ANON_KEY in environment",
                {"url_set": bool(self.url), "key_set": bool(self.key)}
            )

        self.client: AsyncClient | None = None

    async def init(self) -> None:
        """Initialize Supabase Storage and verify bucket exists."""
        log.operation_start("init", url=self.url[:30] + "...", bucket=self.bucket)

        try:
            self.client = AsyncClient(self.url, self.key)

            # Try to list bucket to verify access
            start = time.time()
            await self.client.storage.from_(self.bucket).list()
            duration = (time.time() - start) * 1000

            log.operation_success("init", duration_ms=duration, bucket=self.bucket)
        except Exception as e:
            log.operation_error("init", e, bucket=self.bucket)
            raise BackendConnectionError(
                "supabase-storage",
                f"Failed to access bucket '{self.bucket}': {str(e)}",
                {"bucket": self.bucket, "error_type": type(e).__name__}
            )

    async def health_check(self) -> bool:
        """Check if Supabase Storage is responsive."""
        try:
            await self.client.storage.from_(self.bucket).list()
            return True
        except Exception as e:
            log.warning(f"Health check failed", exception=e)
            return False

    async def upload_file(self, cache_key: str, filename: str, content: bytes) -> str:
        """
        Upload a file to Supabase Storage.
        Returns the public URL.
        """
        path = f"{cache_key}/{filename}"
        log.operation_start("upload_file", cache_key=cache_key, filename=filename, size_bytes=len(content))

        try:
            start = time.time()

            # Upload to Supabase Storage
            await self.client.storage.from_(self.bucket).upload(path, content)

            # Generate public URL
            public_url = await self.client.storage.from_(self.bucket).get_public_url(path)

            duration = (time.time() - start) * 1000
            log.operation_success(
                "upload_file",
                duration_ms=duration,
                cache_key=cache_key,
                filename=filename,
                size_bytes=len(content)
            )

            return public_url
        except Exception as e:
            log.operation_error("upload_file", e, cache_key=cache_key, filename=filename)
            raise BackendStorageError(
                "supabase-storage",
                "upload",
                filename,
                str(e),
                {"cache_key": cache_key, "size_bytes": len(content)}
            )

    async def upload_text(self, cache_key: str, filename: str, content: str) -> str:
        """
        Upload text file to Supabase Storage.
        Returns the public URL.
        """
        return await self.upload_file(cache_key, filename, content.encode("utf-8"))

    async def get_signed_url(self, cache_key: str, filename: str, expires_in: int = 3600) -> str:
        """
        Get a presigned URL for temporary access.
        Supabase doesn't have presigned URLs natively, so we return the public URL.
        For private files, implement RLS (Row Level Security) instead.
        """
        path = f"{cache_key}/{filename}"
        log.operation_start("get_signed_url", cache_key=cache_key, filename=filename, expires_in=expires_in)

        try:
            # Supabase doesn't support presigned URLs the same way S3 does.
            # Return the public URL; implement RLS (Row Level Security) instead for access control.
            public_url = await self.client.storage.from_(self.bucket).get_public_url(path)
            log.operation_success("get_signed_url", cache_key=cache_key, filename=filename)
            return public_url
        except Exception as e:
            log.operation_error("get_signed_url", e, cache_key=cache_key, filename=filename)
            raise BackendStorageError(
                "supabase-storage",
                "get_signed_url",
                filename,
                str(e),
                {"cache_key": cache_key}
            )

    async def delete_analysis_files(self, cache_key: str) -> None:
        """
        Delete all files for a given analysis.
        """
        log.operation_start("delete_analysis_files", cache_key=cache_key)

        try:
            start = time.time()

            # List all files in the cache_key folder
            files = await self.client.storage.from_(self.bucket).list(cache_key)

            if files:
                # Delete each file
                for file_obj in files:
                    path = f"{cache_key}/{file_obj['name']}"
                    await self.client.storage.from_(self.bucket).remove([path])

                duration = (time.time() - start) * 1000
                log.operation_success("delete_analysis_files", duration_ms=duration, cache_key=cache_key, count=len(files))
            else:
                log.debug("delete_analysis_files - no files found", cache_key=cache_key)
        except Exception as e:
            log.operation_error("delete_analysis_files", e, cache_key=cache_key)
            raise BackendStorageError(
                "supabase-storage",
                "delete",
                cache_key,
                str(e),
                {"cache_key": cache_key}
            )
