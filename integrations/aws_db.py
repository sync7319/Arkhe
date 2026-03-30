"""
AWS RDS PostgreSQL database backend implementation.
Features: error handling, structured logging, connection pooling, health checks.
"""
import os
import asyncio
import time
import logging
from datetime import datetime
from uuid import uuid4

import json
import asyncpg

from integrations.base import BaseDB, Analysis, User
from integrations.exceptions import (
    BackendConnectionError,
    BackendQueryError,
    BackendValidationError,
    AnalysisNotFoundError,
    UserNotFoundError,
)
from integrations.logging import get_logger

log = get_logger("aws-rds")


class AWSDB(BaseDB):
    def __init__(self):
        self.host = os.getenv("AWS_RDS_HOST")
        self.port = int(os.getenv("AWS_RDS_PORT", "5432"))
        self.user = os.getenv("AWS_RDS_USER", "postgres")
        self.password = os.getenv("AWS_RDS_PASSWORD")
        self.database = os.getenv("AWS_RDS_DATABASE", "arkhe")

        if not self.host or not self.password:
            log.error(
                "Missing AWS RDS credentials",
                AWS_RDS_HOST=bool(self.host),
                AWS_RDS_PASSWORD=bool(self.password)
            )
            raise BackendConnectionError(
                "aws-rds",
                "Missing AWS_RDS_HOST or AWS_RDS_PASSWORD in environment",
                {"host_set": bool(self.host), "password_set": bool(self.password)}
            )

        self.pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        """Initialize RDS connection pool and create tables if needed."""
        log.operation_start("init", host=self.host, database=self.database)

        try:
            start = time.time()
            self.pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                min_size=5,
                max_size=20,
                command_timeout=10,
            )

            # Test connection
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT 1")

            duration = (time.time() - start) * 1000
            log.operation_success("init", duration_ms=duration)
        except Exception as e:
            log.operation_error("init", e, host=self.host)
            raise BackendConnectionError(
                "aws-rds",
                f"Failed to create connection pool: {str(e)}",
                {"error_type": type(e).__name__, "host": self.host}
            )

        # Create schema if needed
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(self._schema_migration())
            log.info("Schema ready", database=self.database)
        except Exception as e:
            log.warning(f"Schema creation may have failed (might already exist)", error=str(e))

    async def health_check(self) -> bool:
        """Check if RDS is responsive."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as e:
            log.warning(f"Health check failed", exception=e)
            return False

    async def get_user(self, user_id: str) -> User | None:
        """Fetch user by ID."""
        log.operation_start("get_user", user_id=user_id)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

                if row:
                    user = User(**dict(row))
                    log.operation_success("get_user", user_id=user_id)
                    return user

                log.debug("get_user - not found", user_id=user_id)
                return None
        except Exception as e:
            log.operation_error("get_user", e, user_id=user_id)
            raise BackendQueryError(
                "aws-rds",
                f"SELECT * FROM users WHERE id = '{user_id}'",
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
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO users (id, email, tier, created_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    user.id, user.email, user.tier, user.created_at,
                )
            log.operation_success("create_user", user_id=user_id)
            return user
        except Exception as e:
            log.operation_error("create_user", e, user_id=user_id, email=email)
            raise BackendQueryError(
                "aws-rds",
                f"INSERT INTO users VALUES ('{user_id}', '{email}')",
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
        analysis_id: str | None = None,
    ) -> Analysis:
        """Create a new analysis record."""
        log.operation_start(
            "create_analysis",
            user_id=user_id,
            repo_url=repo_url,
            cache_key=cache_key
        )

        analysis_id = analysis_id or str(uuid4())
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
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO analyses (id, user_id, repo_url, commit_sha, cache_key, status, result_paths, error_message, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    analysis.id, analysis.user_id, analysis.repo_url, analysis.commit_sha,
                    analysis.cache_key, analysis.status, json.dumps(analysis.result_paths), analysis.error_message, analysis.created_at,
                )
            log.operation_success("create_analysis", analysis_id=analysis_id)
            return analysis
        except Exception as e:
            log.operation_error("create_analysis", e, analysis_id=analysis_id)
            raise BackendQueryError(
                "aws-rds",
                f"INSERT INTO analyses VALUES ('{analysis_id}', ...)",
                str(e),
                {"analysis_id": analysis_id, "cache_key": cache_key}
            )

    async def get_analysis(self, analysis_id: str) -> Analysis | None:
        """Fetch analysis by ID."""
        log.operation_start("get_analysis", analysis_id=analysis_id)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM analyses WHERE id = $1", analysis_id)

                if row:
                    analysis = Analysis(**dict(row))
                    log.operation_success("get_analysis", analysis_id=analysis_id)
                    return analysis

                log.debug("get_analysis - not found", analysis_id=analysis_id)
                return None
        except Exception as e:
            log.operation_error("get_analysis", e, analysis_id=analysis_id)
            raise BackendQueryError(
                "aws-rds",
                f"SELECT * FROM analyses WHERE id = '{analysis_id}'",
                str(e),
                {"analysis_id": analysis_id}
            )

    async def get_analysis_by_cache_key(self, cache_key: str) -> Analysis | None:
        """Fetch analysis by cache key (for result caching)."""
        log.operation_start("get_analysis_by_cache_key", cache_key=cache_key)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM analyses WHERE cache_key = $1", cache_key)

                if row:
                    analysis = Analysis(**dict(row))
                    log.operation_success("get_analysis_by_cache_key", cache_key=cache_key)
                    return analysis

                log.debug("get_analysis_by_cache_key - not found", cache_key=cache_key)
                return None
        except Exception as e:
            log.operation_error("get_analysis_by_cache_key", e, cache_key=cache_key)
            raise BackendQueryError(
                "aws-rds",
                f"SELECT * FROM analyses WHERE cache_key = '{cache_key}'",
                str(e),
                {"cache_key": cache_key}
            )

    async def list_user_analyses(self, user_id: str, limit: int = 50) -> list[Analysis]:
        """List all analyses for a user."""
        log.operation_start("list_user_analyses", user_id=user_id, limit=limit)

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM analyses WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
                    user_id, limit,
                )
                analyses = [Analysis(**dict(row)) for row in rows]
                log.operation_success("list_user_analyses", user_id=user_id, count=len(analyses))
                return analyses
        except Exception as e:
            log.operation_error("list_user_analyses", e, user_id=user_id)
            raise BackendQueryError(
                "aws-rds",
                f"SELECT * FROM analyses WHERE user_id = '{user_id}'",
                str(e),
                {"user_id": user_id}
            )

    async def update_analysis_status(self, analysis_id: str, status: str) -> Analysis:
        """Update analysis status (pending → running → complete/error)."""
        log.operation_start("update_analysis_status", analysis_id=analysis_id, status=status)

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "UPDATE analyses SET status = $1 WHERE id = $2 RETURNING *",
                    status, analysis_id,
                )
                if row:
                    analysis = Analysis(**dict(row))
                    log.operation_success("update_analysis_status", analysis_id=analysis_id, status=status)
                    return analysis

            raise AnalysisNotFoundError(analysis_id)
        except Exception as e:
            log.operation_error("update_analysis_status", e, analysis_id=analysis_id)
            if isinstance(e, AnalysisNotFoundError):
                raise
            raise BackendQueryError(
                "aws-rds",
                f"UPDATE analyses SET status = '{status}' WHERE id = '{analysis_id}'",
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
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "UPDATE analyses SET status = $1, result_paths = $2 WHERE id = $3 RETURNING *",
                    status, json.dumps(result_paths), analysis_id,
                )
                if row:
                    analysis = Analysis(**dict(row))
                    log.operation_success("update_analysis_results", analysis_id=analysis_id)
                    return analysis

            raise AnalysisNotFoundError(analysis_id)
        except Exception as e:
            log.operation_error("update_analysis_results", e, analysis_id=analysis_id)
            if isinstance(e, AnalysisNotFoundError):
                raise
            raise BackendQueryError(
                "aws-rds",
                f"UPDATE analyses SET status = '{status}' WHERE id = '{analysis_id}'",
                str(e),
                {"analysis_id": analysis_id, "files_uploaded": len(result_paths)}
            )

    async def update_analysis_cache_key(self, analysis_id: str, cache_key: str, commit_sha: str) -> None:
        """Update cache_key and commit_sha after cloning (replaces pending placeholder)."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE analyses SET cache_key = $1, commit_sha = $2 WHERE id = $3",
                    cache_key, commit_sha, analysis_id,
                )
        except Exception as e:
            log.warning(f"update_analysis_cache_key failed", error=str(e), analysis_id=analysis_id)

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
  error_message TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_analyses_cache_key ON analyses(cache_key);
CREATE INDEX IF NOT EXISTS idx_analyses_status ON analyses(status);
        """
