"""
Database and storage backend abstractions.

Switch between Supabase and AWS via environment variables:
  DB_BACKEND=supabase|aws
  STORAGE_BACKEND=supabase|aws
"""

from integrations.base import BaseDB, BaseStorage, Analysis, User
from config.backends import init_backends, get_db, get_storage

__all__ = [
    "BaseDB",
    "BaseStorage",
    "Analysis",
    "User",
    "init_backends",
    "get_db",
    "get_storage",
]
