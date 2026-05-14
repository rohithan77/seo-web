import hashlib
import os
import secrets
import time

import jwt

from db import db_create_user, db_get_user

SECRET_KEY = os.getenv("JWT_SECRET", "seo-agent-dev-secret-change-in-production")
TOKEN_EXPIRY = 30 * 86400  # 30 days


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
    if db_get_user(email):
        raise ValueError("Email already registered")
    return db_create_user(email, _hash(password))


def login(email: str, password: str) -> str:
    user = db_get_user(email)
    if not user or not _verify(password, user["password_hash"]):
        raise ValueError("Invalid email or password")
    return user["id"]


def make_token(user_id: str) -> str:
    payload = {"sub": user_id, "exp": int(time.time()) + TOKEN_EXPIRY}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except Exception:
        return None
