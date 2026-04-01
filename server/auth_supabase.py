"""
Standalone Supabase Auth client.

Used for email/password auth regardless of which DB backend is active (aws or supabase).
Only requires SUPABASE_URL and SUPABASE_ANON_KEY — no dashboard access, no schema migration.

EC2 deploy: add SUPABASE_URL and SUPABASE_ANON_KEY to .env, then restart.
"""
import os
from supabase import AsyncClient as _AsyncClient

_client: _AsyncClient | None = None


def _get_client() -> _AsyncClient:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_ANON_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required for auth")
        _client = _AsyncClient(url, key)
    return _client


async def sign_in(email: str, password: str) -> dict:
    """Sign in with email/password. Returns {access_token, refresh_token, user_id, email}."""
    try:
        client = _get_client()
        response = await client.auth.sign_in_with_password({"email": email, "password": password})
        if not response.session:
            raise ValueError("Invalid credentials")
        return {
            "access_token":  response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "user_id":       str(response.user.id),
            "email":         response.user.email,
        }
    except RuntimeError:
        raise
    except Exception as e:
        raise ValueError("Invalid email or password") from e


async def sign_up(email: str, password: str) -> dict:
    """
    Sign up with email/password.
    Returns {access_token, refresh_token, user_id, email}
    OR {user_id, email, confirm_required: True} if email confirmation is enabled.
    """
    try:
        client = _get_client()
        response = await client.auth.sign_up({"email": email, "password": password})
        if not response.user:
            raise ValueError("Sign-up failed — no user returned")
        user_id = str(response.user.id)
        if response.session:
            return {
                "access_token":  response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user_id":       user_id,
                "email":         response.user.email,
            }
        # Email confirmation required
        return {"user_id": user_id, "email": response.user.email, "confirm_required": True}
    except RuntimeError:
        raise
    except Exception as e:
        raise ValueError(f"Sign-up error: {e}") from e


async def verify_token(access_token: str) -> dict | None:
    """Verify JWT. Returns {user_id, email} or None if invalid/expired."""
    try:
        client = _get_client()
        response = await client.auth.get_user(jwt=access_token)
        if response and response.user:
            return {"user_id": str(response.user.id), "email": response.user.email}
        return None
    except Exception:
        return None


async def refresh_session(refresh_token: str) -> dict | None:
    """Refresh an expired access token. Returns new {access_token, refresh_token, ...} or None."""
    try:
        client = _get_client()
        response = await client.auth.refresh_session(refresh_token)
        if response and response.session:
            return {
                "access_token":  response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user_id":       str(response.user.id),
                "email":         response.user.email,
            }
        return None
    except Exception:
        return None
