"""Accounts: register, log in, log out, see and delete your account.

Errors never say whether an email has an account. Registering answers the same
way either way, and a failed login is "The email or password is wrong" whether
the email is unknown or the password is wrong, after the same amount of work.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response, status

from app.api.deps import SessionDep, SettingsDep, UserDep, enforce_limit
from app.api.errors import ApiError
from app.api.schemas import (
    CredentialsRequest,
    ErrorResponse,
    LoginResponse,
    MessageResponse,
    UserOut,
)
from app.config import Settings
from app.services.accounts import (
    hash_password,
    new_token,
    normalize_email,
    password_needs_rehash,
    password_problem,
    token_hash,
    valid_email,
    verify_password,
    verify_unknown_user,
)
from app.storage.accounts import AccountRepository, EmailTaken
from app.storage.repository import aware

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (401, 409, 422, 429)
}
REGISTERED = (
    "If this email can be used, the account is ready. Log in with the same email and "
    "password. If you already had an account with this email, log in with its password."
)
_WRONG = "The email or password is wrong."


def _accounts_on(settings: Settings) -> None:
    if settings.auth_mode == "disabled":
        raise ApiError(
            409,
            "auth_disabled",
            "Accounts are off on this server (AUTH_MODE=disabled): every request uses the "
            "single local account.",
        )


def _user_out(user_id: str, email: str, created_at: datetime, settings: Settings) -> UserOut:
    return UserOut(id=user_id, email=email, created_at=created_at, auth_mode=settings.auth_mode)


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MessageResponse,
    responses=_ERRORS,
    summary="Create an account. Then log in with the same email and password.",
)
def register(
    body: CredentialsRequest, request: Request, session: SessionDep, settings: SettingsDep
) -> MessageResponse:
    _accounts_on(settings)
    email = normalize_email(body.email)
    enforce_limit(request, "auth", email=email)
    if not valid_email(email):
        raise ApiError(422, "invalid_email", "Enter an email address such as name@example.com.")
    problem = password_problem(body.password)
    if problem is not None:
        raise ApiError(422, "weak_password", problem)

    repo = AccountRepository(session)
    # Hash first on both paths, so an existing email takes as long as a new one.
    hashed = hash_password(body.password)
    if repo.by_email(email) is None:
        try:
            user = repo.create_user(email, hashed)
        except EmailTaken:
            pass  # registered by a request a moment ago; answer the same way
        else:
            logger.info("account created", extra={"user_id": user.id})
    return MessageResponse(message=REGISTERED)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses=_ERRORS,
    summary="Log in. Returns a session token for the Authorization header.",
)
def login(
    body: CredentialsRequest, request: Request, session: SessionDep, settings: SettingsDep
) -> LoginResponse:
    _accounts_on(settings)
    email = normalize_email(body.email)
    enforce_limit(request, "auth", email=email)
    repo = AccountRepository(session)
    user = repo.by_email(email) if valid_email(email) else None
    if user is None:
        verify_unknown_user(body.password)
        raise ApiError(401, "invalid_credentials", _WRONG)
    if not verify_password(user.password_hash, body.password):
        logger.info("login failed", extra={"user_id": user.id})
        raise ApiError(401, "invalid_credentials", _WRONG)
    if password_needs_rehash(user.password_hash):
        repo.set_password_hash(user, hash_password(body.password))

    repo.purge_expired_sessions()
    token = new_token()
    record = repo.create_session(
        user.id, token_hash(token), timedelta(hours=settings.session_ttl_hours)
    )
    request.state.user_id = user.id
    logger.info("logged in", extra={"user_id": user.id})
    return LoginResponse(
        token=token,
        expires_at=aware(record.expires_at),
        user=_user_out(user.id, user.email, aware(user.created_at), settings),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    summary="End this session. The token stops working at once.",
)
def logout(user: UserDep, session: SessionDep, settings: SettingsDep) -> Response:
    _accounts_on(settings)
    if user.token_hash is not None:
        AccountRepository(session).delete_session(user.token_hash)
    logger.info("logged out", extra={"user_id": user.id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut, responses=_ERRORS, summary="The logged-in account.")
def me(user: UserDep, settings: SettingsDep) -> UserOut:
    return _user_out(user.id, user.email, user.created_at, settings)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
    summary=(
        "Delete the account and every analysis, suggestion, correction and answer it owns, at once."
    ),
)
def delete_me(user: UserDep, session: SessionDep) -> Response:
    analyses = AccountRepository(session).delete_user(user.id)
    logger.info("account deleted", extra={"user_id": user.id, "analyses": analyses})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
