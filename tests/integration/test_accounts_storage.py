"""AccountRepository on its own: duplicate emails, the local account, sessions."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.storage.accounts import LOCAL_USER_ID, AccountRepository, EmailTaken
from app.storage.db import Database
from tests.support import EMAIL, PASSWORD


@pytest.fixture
def session(database_url: str) -> Iterator[Session]:
    db = Database(database_url)
    try:
        yield from db.session()
    finally:
        db.engine.dispose()


def test_a_second_account_with_the_same_email_is_refused(session: Session) -> None:
    repo = AccountRepository(session)
    first = repo.create_user(EMAIL, "hash")
    with pytest.raises(EmailTaken) as error:
        repo.create_user(EMAIL, "other hash")
    # The database error, which quotes the email on Postgres, isn't kept.
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert repo.by_email(EMAIL) is not None and repo.by_id(first.id) is not None


def test_the_local_account_is_made_once(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = AccountRepository(session)
    made = repo.local_user()
    assert made.id == LOCAL_USER_ID and repo.local_user().id == LOCAL_USER_ID
    # Two requests at once: the second finds it missing, then can't insert it.
    real = repo.by_id
    calls = iter([None])
    monkeypatch.setattr(repo, "by_id", lambda user_id: next(calls, real(user_id)))
    session.expunge_all()
    assert repo.local_user().id == LOCAL_USER_ID


def test_sessions_by_account(session: Session) -> None:
    repo = AccountRepository(session)
    user = repo.create_user(EMAIL, "hash")
    for token_hash in ("a" * 64, "b" * 64):
        repo.create_session(user.id, token_hash, timedelta(hours=1))
    repo.create_session(user.id, "c" * 64, timedelta(seconds=-1))
    assert repo.user_for_token("a" * 64) is not None
    assert repo.purge_expired_sessions() == 1
    assert repo.delete_sessions(user.id) == 2
    assert repo.user_for_token("a" * 64) is None
    assert not repo.delete_session("a" * 64)


def test_register_answers_the_same_when_a_twin_request_wins(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def taken(self: AccountRepository, email: str, password_hash: str) -> None:
        raise EmailTaken

    monkeypatch.setattr(AccountRepository, "create_user", taken)
    response = anon_client.post(
        "/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 202
