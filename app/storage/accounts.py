"""Accounts and login sessions."""

import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.storage.db import AuthSessionRecord, UserRecord, utcnow
from app.storage.repository import AnalysisRepository, aware

# The single account used when AUTH_MODE=disabled. Its email isn't an address and
# its password hash isn't a hash, so nobody can log in as it.
LOCAL_USER_ID = "local"
LOCAL_USER_EMAIL = "local"
_NO_PASSWORD = "!"


class EmailTaken(Exception):
    """An account with this email already exists."""


class AccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # -- users ------------------------------------------------------------------

    def by_email(self, email: str) -> UserRecord | None:
        return self.session.scalar(select(UserRecord).where(UserRecord.email == email))

    def by_id(self, user_id: str) -> UserRecord | None:
        return self.session.get(UserRecord, user_id)

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        user = UserRecord(
            id=uuid.uuid4().hex, email=email, password_hash=password_hash, created_at=utcnow()
        )
        self.session.add(user)
        try:
            self.session.commit()
        except IntegrityError:
            # Never logged or chained: on Postgres the error message quotes the email.
            self.session.rollback()
            raise EmailTaken from None
        return user

    def set_password_hash(self, user: UserRecord, password_hash: str) -> None:
        user.password_hash = password_hash
        self.session.commit()

    def reset_password(self, user: UserRecord, password_hash: str) -> int:
        """Set a new password and end every session of the account."""
        user.password_hash = password_hash
        ended = self.delete_sessions(user.id, commit=False)
        self.session.commit()
        return ended

    def delete_user(self, user_id: str) -> int:
        """Delete the account, its sessions, and every analysis it owns with
        everything stored with them, in one transaction. Returns the analyses deleted."""
        analyses = AnalysisRepository(self.session).delete_all_for_owner(user_id, commit=False)
        self.delete_sessions(user_id, commit=False)
        self.session.execute(delete(UserRecord).where(UserRecord.id == user_id))
        self.session.commit()
        return analyses

    def local_user(self) -> UserRecord:
        user = self.by_id(LOCAL_USER_ID)
        if user is not None:
            return user
        user = UserRecord(
            id=LOCAL_USER_ID,
            email=LOCAL_USER_EMAIL,
            password_hash=_NO_PASSWORD,
            created_at=utcnow(),
        )
        self.session.add(user)
        try:
            self.session.commit()
        except IntegrityError:  # another request made it first
            self.session.rollback()
            existing = self.by_id(LOCAL_USER_ID)
            assert existing is not None
            return existing
        return user

    # -- sessions ---------------------------------------------------------------

    def create_session(self, user_id: str, token_hash: str, ttl: timedelta) -> AuthSessionRecord:
        now = utcnow()
        record = AuthSessionRecord(
            token_hash=token_hash, user_id=user_id, created_at=now, expires_at=now + ttl
        )
        self.session.add(record)
        self.session.commit()
        return record

    def user_for_token(self, token_hash: str) -> UserRecord | None:
        """The account a session token belongs to, or None when the session doesn't
        exist or has expired."""
        record = self.session.get(AuthSessionRecord, token_hash)
        if record is None:
            return None
        if aware(record.expires_at) <= utcnow():
            self.session.delete(record)
            self.session.commit()
            return None
        return self.by_id(record.user_id)

    def delete_session(self, token_hash: str) -> bool:
        result = self.session.execute(
            delete(AuthSessionRecord).where(AuthSessionRecord.token_hash == token_hash)
        )
        self.session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def delete_sessions(self, user_id: str, *, commit: bool = True) -> int:
        result = self.session.execute(
            delete(AuthSessionRecord).where(AuthSessionRecord.user_id == user_id)
        )
        if commit:
            self.session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]

    def purge_expired_sessions(self) -> int:
        result = self.session.execute(
            delete(AuthSessionRecord).where(AuthSessionRecord.expires_at <= utcnow())
        )
        self.session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]
