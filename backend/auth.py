import hashlib
import json
import os
import secrets
import time
from pathlib import Path

import jwt

SECRET_KEY = os.getenv("JWT_SECRET", "seo-agent-dev-secret-change-in-production")
TOKEN_EXPIRY = 30 * 86400  # 30 days

USERS_FILE = Path(os.getenv("USERS_FILE", "./users.json"))


def _load() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def _save(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def _hash(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"{salt}:{h.hex()}"


def _verify(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(":", 1)
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(computed.hex(), h)
    except Exception:
        return False


def register(email: str, password: str) -> str:
    """Create account. Returns user_id. Raises ValueError on duplicate."""
    users = _load()
    key = email.lower().strip()
    if key in users:
        raise ValueError("Email already registered")
    user_id = secrets.token_hex(16)
    users[key] = {"id": user_id, "email": key, "password_hash": _hash(password)}
    _save(users)
    return user_id


def login(email: str, password: str) -> str:
    """Verify credentials. Returns user_id. Raises ValueError on bad creds."""
    users = _load()
    user = users.get(email.lower().strip())
    if not user or not _verify(password, user["password_hash"]):
        raise ValueError("Invalid email or password")
    return user["id"]


def make_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_EXPIRY}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> str | None:
    """Returns user_id or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except Exception:
        return None
