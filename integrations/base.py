"""
Abstract base classes for database and storage backends.
Allows swapping between Supabase and AWS without changing FastAPI code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import uuid

from integrations.exceptions import BackendValidationError


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
    error_message: Optional[str] = None

    def validate(self) -> None:
        """Validate analysis data before storage."""
        valid_statuses = {"pending", "running", "complete", "error"}

        if not self.id or not isinstance(self.id, str):
            raise BackendValidationError("id", self.id, "non-empty UUID string")
        if not self.user_id or not isinstance(self.user_id, str):
            raise BackendValidationError("user_id", self.user_id, "non-empty UUID string")
        if not self.repo_url or not isinstance(self.repo_url, str):
            raise BackendValidationError("repo_url", self.repo_url, "non-empty string")
        if not self.commit_sha or not isinstance(self.commit_sha, str):
            raise BackendValidationError("commit_sha", self.commit_sha, "non-empty string")
        if not self.cache_key or not isinstance(self.cache_key, str):
            raise BackendValidationError("cache_key", self.cache_key, "non-empty string")
        if self.status not in valid_statuses:
            raise BackendValidationError("status", self.status, f"one of {valid_statuses}")
        if not isinstance(self.result_paths, dict):
            raise BackendValidationError("result_paths", self.result_paths, "dict")
        if not isinstance(self.created_at, datetime):
            raise BackendValidationError("created_at", self.created_at, "datetime")


@dataclass
class User:
    """Represents a user account."""
    id: str
    email: str
    tier: str = "free"  # free | paid
    created_at: Optional[datetime] = None

    def validate(self) -> None:
        """Validate user data before storage."""
        valid_tiers = {"free", "paid"}

        if not self.id or not isinstance(self.id, str):
            raise BackendValidationError("id", self.id, "non-empty UUID string")
        if not self.email or not isinstance(self.email, str):
            raise BackendValidationError("email", self.email, "non-empty string")
        if "@" not in self.email:
            raise BackendValidationError("email", self.email, "valid email address")
        if self.tier not in valid_tiers:
            raise BackendValidationError("tier", self.tier, f"one of {valid_tiers}")
        if self.created_at and not isinstance(self.created_at, datetime):
            raise BackendValidationError("created_at", self.created_at, "datetime or None")


class BaseDB(ABC):
    """
    Abstract database backend interface.
    Implemented by: SupabaseDB, AWSDB

    All methods should:
    - Log operations with context (operation_start, operation_success, operation_error)
    - Raise specific BackendError subclasses on failure
    - Validate input data using model.validate() before storage
    """

    @abstractmethod
    async def init(self) -> None:
        """
        Initialize database connection and schema.
        Called once at server startup.

        Raises:
            BackendConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if backend is healthy and responding.
        Used by /health endpoint.

        Returns:
            True if healthy, False otherwise
        """
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

    @abstractmethod
    async def update_analysis_cache_key(self, analysis_id: str, cache_key: str, commit_sha: str) -> None:
        """Update the cache_key and commit_sha after cloning (replaces pending placeholder)."""
        pass


class BaseStorage(ABC):
    """
    Abstract storage backend interface.
    Implemented by: SupabaseStorage, S3Storage

    All methods should:
    - Log operations with context (operation_start, operation_success, operation_error)
    - Raise BackendStorageError on failure
    """

    @abstractmethod
    async def init(self) -> None:
        """
        Initialize storage connection.
        Called once at server startup.

        Raises:
            BackendConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check if backend is healthy and responding.
        Used by /health endpoint.

        Returns:
            True if healthy, False otherwise
        """
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
