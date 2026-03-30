"""
AWS RDS PostgreSQL database backend implementation.
"""
import os
import asyncio
import logging
from datetime import datetime
from uuid import uuid4

import asyncpg

from integrations.base import BaseDB, Analysis, User

logger = logging.getLogger("arkhe.aws_db")


class AWSDB(BaseDB):
    def __init__(self):
        self.host = os.getenv("AWS_RDS_HOST")
        self.port = int(os.getenv("AWS_RDS_PORT", "5432"))
        self.user = os.getenv("AWS_RDS_USER", "postgres")
        self.password = os.getenv("AWS_RDS_PASSWORD")
        self.database = os.getenv("AWS_RDS_DATABASE", "arkhe")

        if not self.host or not self.password:
            raise ValueError(
                "AWS_RDS_HOST and AWS_RDS_PASSWORD must be set in .env"
            )

        self.pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        """Initialize connection pool and create tables if needed."""
        self.pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            min_size=5,
            max_size=20,
        )

        # Create tables if they don't exist
        async with self.pool.acquire() as conn:
            await conn.execute(self._schema_migration())
            logger.info("[aws_db] Connected to RDS, schema ready")

    async def get_user(self, user_id: str) -> User | None:
        """Fetch user by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if row:
                return User(**dict(row))
        return None

    async def create_user(self, user_id: str, email: str, tier: str = "free") -> User:
        """Create a new user."""
        user = User(
            id=user_id,
            email=email,
            tier=tier,
            created_at=datetime.utcnow(),
        )
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (id, email, tier, created_at)
                VALUES ($1, $2, $3, $4)
                """,
                user.id, user.email, user.tier, user.created_at,
            )
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
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO analyses (id, user_id, repo_url, commit_sha, cache_key, status, result_paths, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                analysis.id, analysis.user_id, analysis.repo_url, analysis.commit_sha,
                analysis.cache_key, analysis.status, analysis.result_paths, analysis.created_at,
            )
        return analysis

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        """Fetch analysis by ID."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM analyses WHERE id = $1", analysis_id)
            if row:
                return Analysis(**dict(row))
        return None

    async def get_analysis_by_cache_key(self, cache_key: str) -> Analysis | None:
        """Fetch analysis by cache key (for result caching)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM analyses WHERE cache_key = $1", cache_key)
            if row:
                return Analysis(**dict(row))
        return None

    async def list_user_analyses(self, user_id: str, limit: int = 50) -> list[Analysis]:
        """List all analyses for a user."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM analyses WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                user_id, limit,
            )
            return [Analysis(**dict(row)) for row in rows]

    async def update_analysis_status(self, analysis_id: str, status: str) -> Analysis:
        """Update analysis status (pending → running → complete/error)."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE analyses SET status = $1 WHERE id = $2 RETURNING *",
                status, analysis_id,
            )
            if row:
                return Analysis(**dict(row))
        raise ValueError(f"Analysis {analysis_id} not found")

    async def update_analysis_results(
        self, analysis_id: str, result_paths: dict, status: str = "complete"
    ) -> Analysis:
        """Update analysis with result URLs after pipeline completes."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE analyses SET status = $1, result_paths = $2 WHERE id = $3 RETURNING *",
                status, result_paths, analysis_id,
            )
            if row:
                return Analysis(**dict(row))
        raise ValueError(f"Analysis {analysis_id} not found")

    def _schema_migration(self) -> str:
        """Return SQL to create tables."""
        return """
CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  tier TEXT DEFAULT 'free',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
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

CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_analyses_cache_key ON analyses(cache_key);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
        """
