"""
Supabase client + all database operations.
Replaces the file-based sessions/ and users.json approach.
"""

import os
import secrets
from supabase import create_client, Client

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY env vars must be set")
        _client = create_client(url, key)
    return _client


# ── Users ─────────────────────────────────────────────────────────────────────

def db_create_user(email: str, password_hash: str) -> str:
    user_id = secrets.token_hex(16)
    get_db().table("users").insert({
        "id": user_id,
        "email": email.lower().strip(),
        "password_hash": password_hash,
    }).execute()
    return user_id


def db_get_user(email: str) -> dict | None:
    res = get_db().table("users").select("*").eq("email", email.lower().strip()).execute()
    return res.data[0] if res.data else None


# ── Sessions ──────────────────────────────────────────────────────────────────

def db_create_session(session_id: str, user_id: str, url: str, started_at: str):
    get_db().table("sessions").insert({
        "id": session_id,
        "user_id": user_id,
        "url": url,
        "started_at": started_at,
        "status": "auditing",
    }).execute()


def db_get_session(session_id: str) -> dict | None:
    res = get_db().table("sessions").select("*").eq("id", session_id).execute()
    return res.data[0] if res.data else None


def db_update_session(session_id: str, **kwargs):
    get_db().table("sessions").update(kwargs).eq("id", session_id).execute()


def db_get_user_sessions(user_id: str) -> list[dict]:
    res = (
        get_db().table("sessions")
        .select("id, url, started_at, status")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .execute()
    )
    return res.data
