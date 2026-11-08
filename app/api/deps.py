"""Request dependencies shared by the routers: settings, the database session, the
logged-in user, the client address and rate limits."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.config import Settings
from app.services.accounts import email_key, token_hash
from app.services.network import TrustedProxies
from app.services.ratelimit import IP, RateLimiter, retry_after_seconds
from app.storage.accounts import AccountRepository
from app.storage.repository import aware

logger = logging.getLogger("app.api")

_bearer = HTTPBearer(
    auto_error=False,
    description="The token from POST /api/v1/auth/login, sent as `Authorization: Bearer <token>`.",
)


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    created_at: datetime
    # None when AUTH_MODE=disabled, where there is no session to end.
    token_hash: str | None


def not_authenticated() -> ApiError:
    return ApiError(
        401,
        "not_authenticated",
        "Log in first. Send the token from POST /api/v1/auth/login as "
        '"Authorization: Bearer <token>". Sessions end after SESSION_TTL_HOURS and at logout.',
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    repo = AccountRepository(session)
    if settings.auth_mode == "disabled":
        local = repo.local_user()
        request.state.user_id = local.id
        return CurrentUser(local.id, local.email, aware(local.created_at), None)
    if credentials is None or not credentials.credentials:
        raise not_authenticated()
    hashed = token_hash(credentials.credentials)
    user = repo.user_for_token(hashed)
    if user is None:
        raise not_authenticated()
    request.state.user_id = user.id
    return CurrentUser(user.id, user.email, aware(user.created_at), hashed)


UserDep = Annotated[CurrentUser, Depends(current_user)]


def client_address(request: Request) -> str:
    """The address per-IP limits count, read through TRUSTED_PROXIES."""
    proxies: TrustedProxies = request.app.state.proxies
    peer = request.client.host if request.client else None
    return proxies.client_address(peer, request.headers.getlist("x-forwarded-for"))


def enforce_limit(
    request: Request, action: str, *, user_id: str | None = None, email: str | None = None
) -> None:
    """Count one `action` for the client address and, when given, the account or the
    email tried. Raises 429 with Retry-After when any of them is over its rate."""
    limiter: RateLimiter | None = request.app.state.limiter
    if limiter is None:
        return
    keys = [(IP, client_address(request))]
    if user_id is not None:
        keys.append(("user", user_id))
    if email is not None:
        keys.append(("email", email_key(email)))
    wait = limiter.hit(action, keys)
    if wait is None:
        return
    seconds = retry_after_seconds(wait)
    logger.warning(
        "rate limited",
        extra={"action": action, "user_id": user_id, "retry_after": seconds},
    )
    raise ApiError(
        429,
        "rate_limited",
        f"Too many requests of this kind. Try again in {seconds} seconds.",
        headers={"Retry-After": str(seconds)},
    )
