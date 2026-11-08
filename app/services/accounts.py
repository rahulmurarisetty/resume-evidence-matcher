"""Passwords, session tokens and email addresses.

Passwords are hashed with argon2id (argon2-cffi's defaults, RFC 9106's low-memory
profile). Session tokens are random and only their SHA-256 hash is stored.
"""

import hashlib
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
MAX_EMAIL_LENGTH = 254
# 32 random bytes, about 43 URL-safe characters.
TOKEN_BYTES = 32

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


def default_hasher() -> PasswordHasher:
    """argon2id with RFC 9106's low-memory profile: 64 MiB, 3 passes, 4 lanes."""
    return PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)


_hasher = default_hasher()
# Checked against when the email is unknown, so a login takes as long whether or
# not the account exists.
_dummy_hash: str | None = None


def set_hasher(hasher: PasswordHasher) -> None:
    """Replace the hasher. The tests use cheap parameters to stay fast."""
    global _hasher, _dummy_hash
    _hasher = hasher
    _dummy_hash = None


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    """A plain shape check: something@domain.tld, with no spaces. Without email
    sending, nothing proves the address is real or belongs to the person."""
    return len(email) <= MAX_EMAIL_LENGTH and _EMAIL_RE.match(email) is not None


def password_problem(password: str) -> str | None:
    """Why a new password can't be used, or None when it can."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use a password of at most {MAX_PASSWORD_LENGTH} characters."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_unknown_user(password: str) -> None:
    """Spend the time a real check would, for an email with no account."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(_dummy_hash, password)


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def email_key(email: str) -> str:
    """A rate-limit key for an email, so the limiter never holds addresses."""
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()
