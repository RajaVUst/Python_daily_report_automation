"""Admin authentication: PBKDF2 password hashes + session cookie."""
import hashlib
import hmac
import logging
import os
import secrets
import time

from fastapi import Request

from .db import User, session_scope

log = logging.getLogger("auth")
_ITER = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITER)
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def ensure_admin() -> None:
    """Create the admin user on first start from ADMIN_USERNAME / ADMIN_PASSWORD."""
    username = os.getenv("ADMIN_USERNAME", "admin")
    with session_scope() as s:
        if s.query(User).count():
            return
        password = os.getenv("ADMIN_PASSWORD")
        if not password:
            password = secrets.token_urlsafe(12)
            log.warning("ADMIN_PASSWORD not set. Generated admin password for '%s': %s", username, password)
        s.add(User(username=username, password_hash=hash_password(password)))


def authenticate(username: str, password: str) -> bool:
    with session_scope() as s:
        u = s.query(User).filter_by(username=username).first()
        # Run a hash even when the user is missing to keep timing similar.
        stored = u.password_hash if u else hash_password("dummy")
        ok = verify_password(password, stored)
        return bool(u and ok)


class NotAuthenticated(Exception):
    pass


def require_admin(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


# --- tiny in-memory login throttle (per client IP) ---
_fails: dict[str, list[float]] = {}
_WINDOW, _MAX = 300, 5


def throttled(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < _WINDOW]
    return len(_fails[ip]) >= _MAX


def record_failure(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.time())
