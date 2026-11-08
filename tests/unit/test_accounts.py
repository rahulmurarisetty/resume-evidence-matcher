"""Passwords, tokens and emails (app/services/accounts.py)."""

import hashlib

import pytest

from app.services import accounts


def test_the_real_hasher_is_argon2id_with_rfc_9106_parameters() -> None:
    # The tests run with cheap parameters (conftest.py); production uses these.
    hashed = accounts.default_hasher().hash("correct horse battery staple")
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


def test_hash_and_verify() -> None:
    hashed = accounts.hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert accounts.verify_password(hashed, "correct horse battery staple")
    assert not accounts.verify_password(hashed, "Correct horse battery staple")
    # A stored value that isn't a hash (the local account's "!") never verifies.
    assert not accounts.verify_password("!", "!")
    assert not accounts.password_needs_rehash("!")


def test_unknown_users_cost_one_check() -> None:
    accounts.verify_unknown_user("anything at all")
    first = accounts._dummy_hash
    accounts.verify_unknown_user("something else")
    assert first is not None and accounts._dummy_hash == first


@pytest.mark.parametrize(
    ("password", "ok"),
    [("x" * 11, False), ("x" * 12, True), ("x" * 256, True), ("x" * 257, False)],
)
def test_password_rules(password: str, ok: bool) -> None:
    assert (accounts.password_problem(password) is None) is ok


@pytest.mark.parametrize(
    ("email", "ok"),
    [
        ("person@example.com", True),
        ("first.last+tag@sub.example.co.uk", True),
        ("person@example", False),
        ("person@@example.com", False),
        ("two words@example.com", False),
        ("person@example.", False),
        ("a@" + "b" * 250 + ".com", False),
    ],
)
def test_email_shape(email: str, ok: bool) -> None:
    assert accounts.valid_email(email) is ok


def test_tokens_are_random_and_only_their_hash_is_kept() -> None:
    first, second = accounts.new_token(), accounts.new_token()
    assert first != second and len(first) >= 43
    assert accounts.token_hash(first) == hashlib.sha256(first.encode()).hexdigest()
    assert accounts.normalize_email("  Person@Example.COM ") == "person@example.com"
    # Rate-limit keys for emails are hashes, so the limiter never holds an address.
    assert accounts.email_key("Person@Example.com") == accounts.email_key("person@example.com")
    assert "@" not in accounts.email_key("person@example.com")
