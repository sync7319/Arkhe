"""
Abstract base classes for database and storage backends.
Allows swapping between Supabase and AWS without changing FastAPI code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Analysis:
    """Represents a single codebase analysis record."""
    id: str
    user_id: str
    repo_url: str
    commit_sha: str
    cache_key: str
    status: str  # pending | running | complete | error
    result_paths: dict  # {"CODEBASE_MAP.md": "url", ...}
    created_at: datetime
    expires_at: Optional[datetime] = None


@dataclass
class User:
    """Represents a user account."""
    id: str
    email: str
    tier: str = "free"  # free | paid
    created_at: Optional[datetime] = None


class BaseDB(ABC):
    """Abstract database backend."""

    @abstractmethod
    async def init(self) -> None:
        """Initialize database connection and schema."""
        pass

    @abstractmethod
    async def get_user(self, user_id: str) -> Optional[User]:
        """Fetch user by ID."""
        pass

    @abstractmethod
    async def create_user(self, user_id: str, email: str, tier: str = "free") -> User:
        """Create a new user."""
        pass

    @abstractmethod
    async def create_analysis(
        self,
        user_id: str,
        repo_url: str,
        commit_sha: str,
        cache_key: str,
        status: str = "pending",
    ) -> Analysis:
        """Create a new analysis record."""
        pass

    @abstractmethod
    async def get_analysis(self, analysis_id: str) -> Optional[Analysis]:
        """Fetch analysis by ID."""
        pass

    @abstractmethod
    async def get_analysis_by_cache_key(self, cache_key: str) -> Optional[Analysis]:
        """Fetch analysis by cache key (for result caching)."""
        pass

    @abstractmethod
    async def list_user_analyses(self, user_id: str, limit: int = 50) -> list[Analysis]:
        """List all analyses for a user."""
        pass

    @abstractmethod
    async def update_analysis_status(self, analysis_id: str, status: str) -> Analysis:
        """Update analysis status (pending → running → complete/error)."""
        pass

    @abstractmethod
    async def update_analysis_results(
        self, analysis_id: str, result_paths: dict, status: str = "complete"
    ) -> Analysis:
        """Update analysis with result URLs after pipeline completes."""
        pass


class BaseStorage(ABC):
    """Abstract storage backend."""

    @abstractmethod
    async def init(self) -> None:
        """Initialize storage connection."""
        pass

    @abstractmethod
    async def upload_file(self, cache_key: str, filename: str, content: bytes) -> str:
        """
        Upload a file to storage.
        Returns the public/presigned URL.
        """
        pass

    @abstractmethod
    async def upload_text(self, cache_key: str, filename: str, content: str) -> str:
        """
        Upload text file to storage.
        Returns the public/presigned URL.
        """
        pass

    @abstractmethod
    async def get_signed_url(self, cache_key: str, filename: str, expires_in: int = 3600) -> str:
        """
        Get a presigned/temporary URL for downloading a file.
        expires_in: seconds until URL expires.
        """
        pass

    @abstractmethod
    async def delete_analysis_files(self, cache_key: str) -> None:
        """
        Delete all files for a given analysis (for cleanup after expiration).
        """
        pass
