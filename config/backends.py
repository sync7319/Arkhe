"""
Backend selection — switch between Supabase and AWS via environment variables.

Example .env:
  DB_BACKEND=supabase          # or: aws
  STORAGE_BACKEND=supabase     # or: aws
"""
import os
from dotenv import load_dotenv
load_dotenv()
from integrations.base import BaseDB, BaseStorage

# Determine which backends to use
DB_BACKEND = os.getenv("DB_BACKEND", "supabase").lower()
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "supabase").lower()

# Validate
VALID_BACKENDS = {"supabase", "aws"}
if DB_BACKEND not in VALID_BACKENDS:
    raise ValueError(f"DB_BACKEND must be one of {VALID_BACKENDS}, got: {DB_BACKEND}")
if STORAGE_BACKEND not in VALID_BACKENDS:
    raise ValueError(f"STORAGE_BACKEND must be one of {VALID_BACKENDS}, got: {STORAGE_BACKEND}")


def get_db_client() -> BaseDB:
    """Get database client based on DB_BACKEND environment variable."""
    if DB_BACKEND == "supabase":
        from integrations.supabase_db import SupabaseDB
        return SupabaseDB()
    elif DB_BACKEND == "aws":
        from integrations.aws_db import AWSDB
        return AWSDB()
    raise ValueError(f"Unknown DB_BACKEND: {DB_BACKEND}")


def get_storage_client() -> BaseStorage:
    """Get storage client based on STORAGE_BACKEND environment variable."""
    if STORAGE_BACKEND == "supabase":
        from integrations.supabase_storage import SupabaseStorage
        return SupabaseStorage()
    elif STORAGE_BACKEND == "aws":
        from integrations.aws_storage import S3Storage
        return S3Storage()
    raise ValueError(f"Unknown STORAGE_BACKEND: {STORAGE_BACKEND}")


# Global clients (singletons)
_db_client: BaseDB | None = None
_storage_client: BaseStorage | None = None


async def init_backends() -> tuple[BaseDB, BaseStorage]:
    """
    Initialize both backends.
    Call this once at server startup.
    """
    global _db_client, _storage_client

    _db_client = get_db_client()
    _storage_client = get_storage_client()

    await _db_client.init()
    await _storage_client.init()

    return _db_client, _storage_client


def get_db() -> BaseDB:
    """Get the initialized database client."""
    if _db_client is None:
        raise RuntimeError("Database client not initialized. Call init_backends() at startup.")
    return _db_client


def get_storage() -> BaseStorage:
    """Get the initialized storage client."""
    if _storage_client is None:
        raise RuntimeError("Storage client not initialized. Call init_backends() at startup.")
    return _storage_client
