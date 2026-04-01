"""
Supabase database backend implementation.
Features: error handling, structured logging, health checks, auth, per-user API keys.

Schema additions (run once in Supabase SQL editor):
  CREATE TABLE IF NOT EXISTS user_api_keys (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    api_key TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, provider)
  );
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
        self.key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not self.url or not self.key:
            log.error(
                "Missing Supabase credentials",
                SUPABASE_URL=bool(self.url),
                SUPABASE_SERVICE_KEY=bool(os.getenv("SUPABASE_SERVICE_KEY")),
                SUPABASE_ANON_KEY=bool(os.getenv("SUPABASE_ANON_KEY")),
            )
            raise BackendConnectionError(
                "supabase",
                "Missing SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_ANON_KEY) in environment",
                {"url_set": bool(self.url), "key_set": bool(self.key)}
            )

        self.anon_key = os.getenv("SUPABASE_ANON_KEY") or self.key
        self.client: AsyncClient | None = None
        self.auth_client: AsyncClient | None = None

    async def init(self) -> None:
        """Initialize Supabase connection and verify schema."""
        log.operation_start("init", url=self.url[:30] + "...")

        try:
            self.client = AsyncClient(self.url, self.key)
            # Separate client using anon key for user-facing auth operations
            self.auth_client = AsyncClient(self.url, self.anon_key)

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
            response = await self.client.table("users").select("*").eq("id", user_id).maybe_single().execute()

            if response and response.data:
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
            await self.client.table("users").insert({
                "id": user.id,
                "email": user.email,
                "tier": user.tier,
                "created_at": user.created_at.isoformat() if user.created_at else None,
            }).execute()
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
            await self.client.table("analyses").insert({
                "id": analysis.id,
                "user_id": analysis.user_id,
                "repo_url": analysis.repo_url,
                "commit_sha": analysis.commit_sha,
                "cache_key": analysis.cache_key,
                "status": analysis.status,
                "result_paths": analysis.result_paths,
                "error_message": analysis.error_message,
                "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
                "expires_at": analysis.expires_at.isoformat() if analysis.expires_at else None,
            }).execute()
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
            response = await self.client.table("analyses").select("*").eq("id", analysis_id).maybe_single().execute()

            if response and response.data:
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

    async def update_analysis_cache_key(self, analysis_id: str, cache_key: str, commit_sha: str) -> None:
        """Update cache_key and commit_sha after cloning (replaces pending placeholder)."""
        try:
            await self.client.table("analyses").update(
                {"cache_key": cache_key, "commit_sha": commit_sha}
            ).eq("id", analysis_id).execute()
        except Exception as e:
            log.warning(f"update_analysis_cache_key failed", error=str(e), analysis_id=analysis_id)

    # ── Auth operations ───────────────────────────────────────────────────────

    async def sign_in(self, email: str, password: str) -> dict:
        """Sign in with email/password. Returns {access_token, refresh_token, user_id, email}."""
        try:
            response = await self.auth_client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            if not response.session:
                raise ValueError("No session returned")
            return {
                "access_token":  response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user_id":       str(response.user.id),
                "email":         response.user.email,
            }
        except Exception as e:
            raise ValueError(f"Invalid email or password: {e}") from e

    async def sign_up(self, email: str, password: str) -> dict:
        """Sign up with email/password. Returns {access_token, refresh_token, user_id, email}."""
        try:
            response = await self.auth_client.auth.sign_up(
                {"email": email, "password": password}
            )
            if not response.user:
                raise ValueError("Sign-up failed")
            user_id = str(response.user.id)
            # Mirror user into public.users table (best-effort)
            try:
                existing = await self.get_user(user_id)
                if not existing:
                    await self.create_user(user_id, email, tier="free")
            except Exception:
                pass
            # Supabase may require email confirmation; session can be None
            if response.session:
                return {
                    "access_token":  response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "user_id":       user_id,
                    "email":         response.user.email,
                }
            # Email confirmation required — return user info without tokens
            return {"user_id": user_id, "email": response.user.email, "confirm_required": True}
        except Exception as e:
            raise ValueError(f"Sign-up error: {e}") from e

    async def verify_token(self, access_token: str) -> dict | None:
        """Verify JWT. Returns {user_id, email} or None if invalid/expired."""
        try:
            response = await self.auth_client.auth.get_user(jwt=access_token)
            if response and response.user:
                return {"user_id": str(response.user.id), "email": response.user.email}
            return None
        except Exception:
            return None

    async def refresh_session(self, refresh_token: str) -> dict | None:
        """Refresh an expired access token. Returns new tokens or None."""
        try:
            response = await self.auth_client.auth.refresh_session(refresh_token)
            if response.session:
                return {
                    "access_token":  response.session.access_token,
                    "refresh_token": response.session.refresh_token,
                    "user_id":       str(response.user.id),
                    "email":         response.user.email,
                }
            return None
        except Exception:
            return None

    # ── Per-user API keys ─────────────────────────────────────────────────────

    async def get_user_api_keys(self, user_id: str) -> dict[str, str]:
        """Get all saved API keys for a user. Returns {provider: key} dict."""
        try:
            response = await self.client.table("user_api_keys") \
                .select("provider,api_key").eq("user_id", user_id).execute()
            return {row["provider"]: row["api_key"] for row in (response.data or [])}
        except Exception as e:
            log.warning("get_user_api_keys failed", error=str(e), user_id=user_id)
            return {}

    async def save_user_api_keys(self, user_id: str, keys: dict[str, str]) -> None:
        """Upsert API keys for a user. Only saves non-empty values."""
        for provider, key in keys.items():
            if not key or not key.strip():
                continue
            try:
                await self.client.table("user_api_keys").upsert({
                    "user_id":    user_id,
                    "provider":   provider,
                    "api_key":    key.strip(),
                    "updated_at": datetime.utcnow().isoformat(),
                }).execute()
            except Exception as e:
                log.warning("save_user_api_keys failed", error=str(e), user_id=user_id, provider=provider)

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

-- Per-user BYOK API keys
CREATE TABLE IF NOT EXISTS user_api_keys (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  provider TEXT NOT NULL,
  api_key TEXT NOT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, provider)
);
        """
