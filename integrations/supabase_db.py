"""
Supabase database backend implementation.
Features: error handling, structured logging, health checks.
"""
import os
import time
from datetime import datetime
from uuid import uuid4

from supabase import AsyncClient, create_client

from integrations.base import BaseDB, Analysis, User
from integrations.exceptions import (
    BackendConnectionError,
    BackendQueryError,
    BackendValidationError,
    AnalysisNotFoundError,
    UserNotFoundError,
)
from integrations.logging import get_logger

log = get_logger("supabase")


class SupabaseDB(BaseDB):
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_ANON_KEY")

        if not self.url or not self.key:
            log.error(
                "Missing Supabase credentials",
                SUPABASE_URL=bool(self.url),
                SUPABASE_ANON_KEY=bool(self.key)
            )
            raise BackendConnectionError(
                "supabase",
                "Missing SUPABASE_URL or SUPABASE_ANON_KEY in environment",
                {"url_set": bool(self.url), "key_set": bool(self.key)}
            )

        self.client: AsyncClient | None = None

    async def init(self) -> None:
        """Initialize Supabase connection and verify schema."""
        log.operation_start("init", url=self.url[:30] + "...")

        try:
            self.client = AsyncClient(self.url, self.key)

            # Test connection by querying users table
            start = time.time()
            await self.client.table("users").select("id").limit(1).execute()
            duration = (time.time() - start) * 1000

            log.operation_success("init", duration_ms=duration)
        except Exception as e:
            log.operation_error("init", e, url=self.url)
            raise BackendConnectionError(
                "supabase",
                f"Failed to connect: {str(e)}",
                {"error_type": type(e).__name__}
            )

    async def health_check(self) -> bool:
        """Check if Supabase is responsive."""
        try:
            await self.client.table("users").select("id").limit(1).execute()
            return True
        except Exception as e:
            log.warning(f"Health check failed", exception=e)
            return False

    async def get_user(self, user_id: str) -> User | None:
        """Fetch user by ID."""
        log.operation_start("get_user", user_id=user_id)

        try:
            response = await self.client.table("users").select("*").eq("id", user_id).single().execute()

            if response.data:
                user = User(**response.data)
                log.operation_success("get_user", user_id=user_id)
                return user

            log.debug("get_user - not found", user_id=user_id)
            return None
        except Exception as e:
            log.operation_error("get_user", e, user_id=user_id)
            raise BackendQueryError(
                "supabase",
                f"SELECT * FROM users WHERE id = {user_id}",
                str(e),
                {"user_id": user_id}
            )

    async def create_user(self, user_id: str, email: str, tier: str = "free") -> User:
        """Create a new user."""
        log.operation_start("create_user", user_id=user_id, email=email, tier=tier)

        user = User(
            id=user_id,
            email=email,
            tier=tier,
            created_at=datetime.utcnow(),
        )

        try:
            user.validate()
        except BackendValidationError as e:
            log.operation_error("create_user", e, user_id=user_id)
            raise

        try:
            await self.client.table("users").insert(user.__dict__).execute()
            log.operation_success("create_user", user_id=user_id)
            return user
        except Exception as e:
            log.operation_error("create_user", e, user_id=user_id, email=email)
            raise BackendQueryError(
                "supabase",
                f"INSERT INTO users VALUES ({user_id}, {email})",
                str(e),
                {"user_id": user_id, "email": email}
            )

    async def create_analysis(
        self,
        user_id: str,
        repo_url: str,
        commit_sha: str,
        cache_key: str,
        status: str = "pending",
    ) -> Analysis:
        """Create a new analysis record."""
        log.operation_start(
            "create_analysis",
            user_id=user_id,
            repo_url=repo_url,
            cache_key=cache_key
        )

        analysis_id = str(uuid4())
        analysis = Analysis(
            id=analysis_id,
            user_id=user_id,
            repo_url=repo_url,
            commit_sha=commit_sha,
            cache_key=cache_key,
            status=status,
            result_paths={},
            created_at=datetime.utcnow(),
        )

        try:
            analysis.validate()
        except BackendValidationError as e:
            log.operation_error("create_analysis", e, analysis_id=analysis_id)
            raise

        try:
            await self.client.table("analyses").insert(analysis.__dict__).execute()
            log.operation_success("create_analysis", analysis_id=analysis_id)
            return analysis
        except Exception as e:
            log.operation_error("create_analysis", e, analysis_id=analysis_id)
            raise BackendQueryError(
                "supabase",
                f"INSERT INTO analyses VALUES ({analysis_id}, ...)",
                str(e),
                {"analysis_id": analysis_id, "cache_key": cache_key}
            )

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        """Fetch analysis by ID."""
        log.operation_start("get_analysis", analysis_id=analysis_id)

        try:
            response = await self.client.table("analyses").select("*").eq("id", analysis_id).single().execute()

            if response.data:
                analysis = Analysis(**response.data)
                log.operation_success("get_analysis", analysis_id=analysis_id)
                return analysis

            log.debug("get_analysis - not found", analysis_id=analysis_id)
            return None
        except Exception as e:
            log.operation_error("get_analysis", e, analysis_id=analysis_id)
            raise BackendQueryError(
                "supabase",
                f"SELECT * FROM analyses WHERE id = {analysis_id}",
                str(e),
                {"analysis_id": analysis_id}
            )

    async def get_analysis_by_cache_key(self, cache_key: str) -> Analysis | None:
        """Fetch analysis by cache key (for result caching)."""
        log.operation_start("get_analysis_by_cache_key", cache_key=cache_key)

        try:
            response = await self.client.table("analyses").select("*").eq("cache_key", cache_key).execute()

            if response.data and len(response.data) > 0:
                analysis = Analysis(**response.data[0])
                log.operation_success("get_analysis_by_cache_key", cache_key=cache_key)
                return analysis

            log.debug("get_analysis_by_cache_key - not found", cache_key=cache_key)
            return None
        except Exception as e:
            log.operation_error("get_analysis_by_cache_key", e, cache_key=cache_key)
            raise BackendQueryError(
                "supabase",
                f"SELECT * FROM analyses WHERE cache_key = {cache_key}",
                str(e),
                {"cache_key": cache_key}
            )

    async def list_user_analyses(self, user_id: str, limit: int = 50) -> list[Analysis]:
        """List all analyses for a user."""
        log.operation_start("list_user_analyses", user_id=user_id, limit=limit)

        try:
            response = await self.client.table("analyses").select("*").eq("user_id", user_id).limit(limit).order("created_at", desc=True).execute()

            analyses = [Analysis(**row) for row in response.data or []]
            log.operation_success("list_user_analyses", user_id=user_id, count=len(analyses))
            return analyses
        except Exception as e:
            log.operation_error("list_user_analyses", e, user_id=user_id)
            raise BackendQueryError(
                "supabase",
                f"SELECT * FROM analyses WHERE user_id = {user_id}",
                str(e),
                {"user_id": user_id}
            )

    async def update_analysis_status(self, analysis_id: str, status: str) -> Analysis:
        """Update analysis status (pending → running → complete/error)."""
        log.operation_start("update_analysis_status", analysis_id=analysis_id, status=status)

        try:
            response = await self.client.table("analyses").update({"status": status}).eq("id", analysis_id).execute()

            if response.data:
                analysis = Analysis(**response.data[0])
                log.operation_success("update_analysis_status", analysis_id=analysis_id, status=status)
                return analysis

            raise AnalysisNotFoundError(analysis_id)
        except Exception as e:
            log.operation_error("update_analysis_status", e, analysis_id=analysis_id)
            if isinstance(e, AnalysisNotFoundError):
                raise
            raise BackendQueryError(
                "supabase",
                f"UPDATE analyses SET status = {status} WHERE id = {analysis_id}",
                str(e),
                {"analysis_id": analysis_id, "status": status}
            )

    async def update_analysis_results(
        self, analysis_id: str, result_paths: dict, status: str = "complete"
    ) -> Analysis:
        """Update analysis with result URLs after pipeline completes."""
        log.operation_start(
            "update_analysis_results",
            analysis_id=analysis_id,
            status=status,
            files=len(result_paths)
        )

        try:
            response = await self.client.table("analyses").update({
                "status": status,
                "result_paths": result_paths,
            }).eq("id", analysis_id).execute()

            if response.data:
                analysis = Analysis(**response.data[0])
                log.operation_success("update_analysis_results", analysis_id=analysis_id)
                return analysis

            raise AnalysisNotFoundError(analysis_id)
        except Exception as e:
            log.operation_error("update_analysis_results", e, analysis_id=analysis_id)
            if isinstance(e, AnalysisNotFoundError):
                raise
            raise BackendQueryError(
                "supabase",
                f"UPDATE analyses SET status = {status} WHERE id = {analysis_id}",
                str(e),
                {"analysis_id": analysis_id, "files_uploaded": len(result_paths)}
            )

    def _schema_migration(self) -> str:
        """Return SQL to create tables in Supabase."""
        return """
-- Create users table
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  tier TEXT DEFAULT 'free',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create analyses table
CREATE TABLE IF NOT EXISTS analyses (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  repo_url TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  cache_key TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'pending',
  result_paths JSONB DEFAULT '{}'::jsonb,
  error_message TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_analyses_cache_key ON analyses(cache_key);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
        """
