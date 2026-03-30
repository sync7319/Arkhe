"""
Unit tests for database and storage backends.
Tests both Supabase and AWS implementations.

Run with:
  pytest tests/test_backends.py -v
  pytest tests/test_backends.py::test_supabase_create_user -v
  pytest tests/test_backends.py::test_aws_create_user -v
"""
import pytest
import os
from datetime import datetime, timedelta
from uuid import uuid4

# Skip AWS tests if credentials not configured
aws_configured = bool(os.getenv("AWS_RDS_HOST")) and bool(os.getenv("AWS_RDS_PASSWORD"))
supabase_configured = bool(os.getenv("SUPABASE_URL")) and bool(os.getenv("SUPABASE_ANON_KEY"))


@pytest.fixture
async def supabase_db():
    """Create a Supabase database client for testing."""
    if not supabase_configured:
        pytest.skip("Supabase not configured (SUPABASE_URL + SUPABASE_ANON_KEY)")

    from integrations.supabase_db import SupabaseDB
    db = SupabaseDB()
    try:
        await db.init()
        yield db
    except Exception as e:
        pytest.fail(f"Failed to initialize Supabase: {e}")


@pytest.fixture
async def aws_db():
    """Create an AWS RDS database client for testing."""
    if not aws_configured:
        pytest.skip("AWS RDS not configured (AWS_RDS_HOST + AWS_RDS_PASSWORD)")

    from integrations.aws_db import AWSDB
    db = AWSDB()
    try:
        await db.init()
        yield db
        # Cleanup: close pool
        if db.pool:
            await db.pool.close()
    except Exception as e:
        pytest.fail(f"Failed to initialize AWS RDS: {e}")


@pytest.fixture
async def supabase_storage():
    """Create a Supabase storage client for testing."""
    if not supabase_configured:
        pytest.skip("Supabase not configured")

    from integrations.supabase_storage import SupabaseStorage
    storage = SupabaseStorage()
    try:
        await storage.init()
        yield storage
    except Exception as e:
        pytest.fail(f"Failed to initialize Supabase Storage: {e}")


@pytest.fixture
async def aws_storage():
    """Create an AWS S3 storage client for testing."""
    if not aws_configured:
        pytest.skip("AWS S3 not configured")

    from integrations.aws_storage import S3Storage
    storage = S3Storage()
    try:
        await storage.init()
        yield storage
    except Exception as e:
        pytest.fail(f"Failed to initialize S3: {e}")


# ── Database Tests ──────────────────────────────────────────────

class TestSupabaseDB:
    """Test Supabase database implementation."""

    @pytest.mark.asyncio
    async def test_init(self, supabase_db):
        """Test database initialization."""
        assert supabase_db.client is not None

    @pytest.mark.asyncio
    async def test_health_check(self, supabase_db):
        """Test health check."""
        healthy = await supabase_db.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_create_and_get_user(self, supabase_db):
        """Test creating and fetching a user."""
        user_id = str(uuid4())
        email = f"test-{user_id[:8]}@arkhe.test"

        # Create user
        user = await supabase_db.create_user(user_id, email, tier="free")
        assert user.id == user_id
        assert user.email == email
        assert user.tier == "free"

        # Fetch user
        fetched = await supabase_db.get_user(user_id)
        assert fetched is not None
        assert fetched.email == email

    @pytest.mark.asyncio
    async def test_create_analysis(self, supabase_db):
        """Test creating an analysis record."""
        user_id = str(uuid4())
        repo_url = "https://github.com/sync7319/Arkhe"
        commit_sha = "abc123def456"
        cache_key = "test-cache-key"

        analysis = await supabase_db.create_analysis(
            user_id=user_id,
            repo_url=repo_url,
            commit_sha=commit_sha,
            cache_key=cache_key,
            status="pending"
        )

        assert analysis.user_id == user_id
        assert analysis.repo_url == repo_url
        assert analysis.commit_sha == commit_sha
        assert analysis.status == "pending"
        assert analysis.result_paths == {}

    @pytest.mark.asyncio
    async def test_get_analysis_by_cache_key(self, supabase_db):
        """Test fetching analysis by cache key (result caching)."""
        user_id = str(uuid4())
        cache_key = f"cache-{uuid4()}"

        # Create analysis
        created = await supabase_db.create_analysis(
            user_id=user_id,
            repo_url="https://github.com/test/repo",
            commit_sha="sha123",
            cache_key=cache_key,
        )

        # Fetch by cache key
        fetched = await supabase_db.get_analysis_by_cache_key(cache_key)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_update_analysis_status(self, supabase_db):
        """Test updating analysis status."""
        user_id = str(uuid4())
        analysis = await supabase_db.create_analysis(
            user_id=user_id,
            repo_url="https://github.com/test/repo",
            commit_sha="sha",
            cache_key=f"key-{uuid4()}",
        )

        # Update status
        updated = await supabase_db.update_analysis_status(analysis.id, "running")
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_update_analysis_results(self, supabase_db):
        """Test storing result URLs after pipeline completes."""
        user_id = str(uuid4())
        analysis = await supabase_db.create_analysis(
            user_id=user_id,
            repo_url="https://github.com/test/repo",
            commit_sha="sha",
            cache_key=f"key-{uuid4()}",
        )

        result_paths = {
            "CODEBASE_MAP.md": "https://storage.example.com/map.md",
            "DEPENDENCY_MAP.html": "https://storage.example.com/graph.html",
        }

        updated = await supabase_db.update_analysis_results(
            analysis.id, result_paths, status="complete"
        )

        assert updated.status == "complete"
        assert updated.result_paths == result_paths


class TestAWSDB:
    """Test AWS RDS database implementation."""

    @pytest.mark.asyncio
    async def test_init(self, aws_db):
        """Test database initialization."""
        assert aws_db.pool is not None

    @pytest.mark.asyncio
    async def test_health_check(self, aws_db):
        """Test health check."""
        healthy = await aws_db.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_create_and_get_user(self, aws_db):
        """Test creating and fetching a user."""
        user_id = str(uuid4())
        email = f"test-{user_id[:8]}@arkhe.test"

        user = await aws_db.create_user(user_id, email, tier="free")
        assert user.id == user_id
        assert user.email == email

        fetched = await aws_db.get_user(user_id)
        assert fetched is not None
        assert fetched.email == email

    @pytest.mark.asyncio
    async def test_create_analysis(self, aws_db):
        """Test creating an analysis record."""
        user_id = str(uuid4())
        cache_key = f"aws-test-{uuid4()}"

        analysis = await aws_db.create_analysis(
            user_id=user_id,
            repo_url="https://github.com/sync7319/Arkhe",
            commit_sha="abc123",
            cache_key=cache_key,
            status="pending"
        )

        assert analysis.status == "pending"
        assert analysis.cache_key == cache_key

    @pytest.mark.asyncio
    async def test_list_user_analyses(self, aws_db):
        """Test listing all analyses for a user."""
        user_id = str(uuid4())

        # Create multiple analyses
        for i in range(3):
            await aws_db.create_analysis(
                user_id=user_id,
                repo_url=f"https://github.com/test/repo{i}",
                commit_sha=f"sha{i}",
                cache_key=f"key-{uuid4()}",
            )

        # List analyses
        analyses = await aws_db.list_user_analyses(user_id)
        assert len(analyses) >= 3


# ── Storage Tests ───────────────────────────────────────────────

class TestSupabaseStorage:
    """Test Supabase storage implementation."""

    @pytest.mark.asyncio
    async def test_init(self, supabase_storage):
        """Test storage initialization."""
        assert supabase_storage.client is not None

    @pytest.mark.asyncio
    async def test_health_check(self, supabase_storage):
        """Test health check."""
        healthy = await supabase_storage.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_upload_text(self, supabase_storage):
        """Test uploading text file."""
        cache_key = f"test-{uuid4()}"
        content = "# Test Codebase Map\n\nThis is a test."

        url = await supabase_storage.upload_text(cache_key, "CODEBASE_MAP.md", content)

        assert url is not None
        assert "CODEBASE_MAP.md" in url or cache_key in url


class TestS3Storage:
    """Test AWS S3 storage implementation."""

    @pytest.mark.asyncio
    async def test_init(self, aws_storage):
        """Test storage initialization."""
        pass  # Init already called in fixture

    @pytest.mark.asyncio
    async def test_health_check(self, aws_storage):
        """Test health check."""
        healthy = await aws_storage.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_upload_text(self, aws_storage):
        """Test uploading text file to S3."""
        cache_key = f"test-{uuid4()}"
        content = "# Test Codebase Map\n\nThis is a test."

        url = await aws_storage.upload_text(cache_key, "CODEBASE_MAP.md", content)

        assert url is not None
        assert "s3" in url.lower() or cache_key in url


# ── Integration Tests ───────────────────────────────────────────

class TestBackendSwitch:
    """Test switching between backends."""

    @pytest.mark.asyncio
    async def test_both_backends_identical_interface(self, supabase_db, aws_db):
        """Verify both backends implement the same interface."""
        # Check all required methods exist
        required_methods = [
            "init", "health_check", "get_user", "create_user",
            "create_analysis", "get_analysis", "get_analysis_by_cache_key",
            "list_user_analyses", "update_analysis_status", "update_analysis_results"
        ]

        for method in required_methods:
            assert hasattr(supabase_db, method), f"Supabase missing {method}"
            assert hasattr(aws_db, method), f"AWS missing {method}"

    @pytest.mark.asyncio
    async def test_result_caching_workflow(self, supabase_db):
        """Test the complete caching workflow."""
        user_id = str(uuid4())
        repo_url = "https://github.com/test/repo"
        commit_sha = "abc123"
        cache_key = f"workflow-test-{uuid4()}"

        # Create first analysis
        analysis1 = await supabase_db.create_analysis(
            user_id=user_id,
            repo_url=repo_url,
            commit_sha=commit_sha,
            cache_key=cache_key,
        )

        # Update with results
        results = {
            "CODEBASE_MAP.md": "https://example.com/map.md",
            "DEPENDENCY_MAP.html": "https://example.com/graph.html",
        }
        await supabase_db.update_analysis_results(analysis1.id, results, "complete")

        # SECOND REQUEST — should hit cache
        cached = await supabase_db.get_analysis_by_cache_key(cache_key)
        assert cached is not None
        assert cached.status == "complete"
        assert cached.result_paths == results
        # Zero LLM cost! ✓
