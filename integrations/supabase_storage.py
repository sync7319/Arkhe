"""
Supabase Storage backend implementation.
"""
import os
import logging

from supabase import AsyncClient, create_client

from integrations.base import BaseStorage

logger = logging.getLogger("arkhe.supabase_storage")


class SupabaseStorage(BaseStorage):
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_ANON_KEY")
        self.bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "arkhe-results")

        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env"
            )

        self.client: AsyncClient | None = None

    async def init(self) -> None:
        """Initialize Supabase connection and verify bucket exists."""
        self.client = AsyncClient(self.url, self.key)

        try:
            # Try to list bucket to verify access
            await self.client.storage.from_(self.bucket).list()
            logger.info(f"[supabase_storage] Connected to bucket '{self.bucket}'")
        except Exception as e:
            logger.warning(f"[supabase_storage] Could not verify bucket: {e}")
            logger.warning(f"[supabase_storage] Create bucket '{self.bucket}' in Supabase dashboard")

    async def upload_file(self, cache_key: str, filename: str, content: bytes) -> str:
        """
        Upload a file to Supabase Storage.
        Returns the public URL.
        """
        path = f"{cache_key}/{filename}"

        # Upload to Supabase Storage
        response = await self.client.storage.from_(self.bucket).upload(path, content)

        # Generate public URL
        public_url = await self.client.storage.from_(self.bucket).get_public_url(path)

        logger.debug(f"[supabase_storage] Uploaded {path} → {public_url}")
        return public_url

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
        For private files, you'd need to implement token-based access control.
        """
        path = f"{cache_key}/{filename}"
        # Supabase doesn't support presigned URLs the same way S3 does.
        # Return the public URL; implement RLS (Row Level Security) instead for access control.
        public_url = await self.client.storage.from_(self.bucket).get_public_url(path)
        logger.debug(f"[supabase_storage] Signed URL for {path} → {public_url}")
        return public_url

    async def delete_analysis_files(self, cache_key: str) -> None:
        """
        Delete all files for a given analysis.
        """
        try:
            # List all files in the cache_key folder
            files = await self.client.storage.from_(self.bucket).list(cache_key)
            if files:
                # Delete each file
                for file_obj in files:
                    path = f"{cache_key}/{file_obj['name']}"
                    await self.client.storage.from_(self.bucket).remove([path])
                logger.info(f"[supabase_storage] Deleted {len(files)} files for {cache_key}")
        except Exception as e:
            logger.warning(f"[supabase_storage] Could not delete files for {cache_key}: {e}")
