"""
Supabase database backend implementation.
"""
import os
from datetime import datetime
from uuid import uuid4
import logging

from supabase import AsyncClient, create_client

from integrations.base import BaseDB, Analysis, User

logger = logging.getLogger("arkhe.supabase_db")


class SupabaseDB(BaseDB):
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_ANON_KEY")

        if not self.url or not self.key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env"
            )

        self.client: AsyncClient | None = None

    async def init(self) -> None:
        """Initialize Supabase connection and create tables if needed."""
        self.client = AsyncClient(self.url, self.key)

        # Tables are expected to exist in Supabase.
        # If you're starting fresh, create them via the Supabase dashboard or use
        # Supabase migrations. This is just a check that we can connect.
        try:
            await self.client.table("users").select("id").limit(1).execute()
            logger.info("[supabase] Connected to users table")
        except Exception as e:
            logger.warning(f"[supabase] Could not verify users table: {e}")
            logger.warning("[supabase] Create tables in Supabase dashboard:")
            logger.warning(self._schema_migration())

    async def get_user(self, user_id: str) -> Analysis | None:
        """Fetch user by ID."""
        response = await self.client.table("users").select("*").eq("id", user_id).single().execute()
        if response.data:
            return User(**response.data)
        return None

    async def create_user(self, user_id: str, email: str, tier: str = "free") -> User:
        """Create a new user."""
        user = User(
            id=user_id,
            email=email,
            tier=tier,
            created_at=datetime.utcnow(),
        )
        await self.client.table("users").insert(user.__dict__).execute()
        return user

    async def create_analysis(
        self,
        user_id: str,
        repo_url: str,
        commit_sha: str,
        cache_key: str,
        status: str = "pending",
    ) -> Analysis:
        """Create a new analysis record."""
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
        await self.client.table("analyses").insert(analysis.__dict__).execute()
        return analysis

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        """Fetch analysis by ID."""
        response = await self.client.table("analyses").select("*").eq("id", analysis_id).single().execute()
        if response.data:
            return Analysis(**response.data)
        return None

    async def get_analysis_by_cache_key(self, cache_key: str) -> Analysis | None:
        """Fetch analysis by cache key (for result caching)."""
        response = await self.client.table("analyses").select("*").eq("cache_key", cache_key).execute()
        if response.data and len(response.data) > 0:
            return Analysis(**response.data[0])
        return None

    async def list_user_analyses(self, user_id: str, limit: int = 50) -> list[Analysis]:
        """List all analyses for a user."""
        response = await self.client.table("analyses").select("*").eq("user_id", user_id).limit(limit).order("created_at", desc=True).execute()
        return [Analysis(**row) for row in response.data or []]

    async def update_analysis_status(self, analysis_id: str, status: str) -> Analysis:
        """Update analysis status (pending → running → complete/error)."""
        response = await self.client.table("analyses").update({"status": status}).eq("id", analysis_id).execute()
        if response.data:
            return Analysis(**response.data[0])
        raise ValueError(f"Analysis {analysis_id} not found")

    async def update_analysis_results(
        self, analysis_id: str, result_paths: dict, status: str = "complete"
    ) -> Analysis:
        """Update analysis with result URLs after pipeline completes."""
        response = await self.client.table("analyses").update({
            "status": status,
            "result_paths": result_paths,
        }).eq("id", analysis_id).execute()
        if response.data:
            return Analysis(**response.data[0])
        raise ValueError(f"Analysis {analysis_id} not found")

    def _schema_migration(self) -> str:
        """Return SQL to create tables in Supabase."""
        return """
-- Create users table
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  tier TEXT DEFAULT 'free',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create analyses table
CREATE TABLE analyses (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  repo_url TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  cache_key TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'pending',
  result_paths JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_analyses_user_id ON analyses(user_id);
CREATE INDEX idx_analyses_cache_key ON analyses(cache_key);
CREATE INDEX idx_analyses_status ON analyses(status);
        """
