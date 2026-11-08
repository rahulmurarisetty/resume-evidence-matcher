"""Account administration for the person running the server.

    python -m app.admin reset-password person@example.com
    python -m app.admin reset-password person@example.com --password-stdin < file
    python -m app.admin delete-user person@example.com [--yes]

v1.0 sends no email, so there is no self-service password reset: the operator
sets a new password here and tells the person over a channel they trust.
Resetting a password ends every session of the account. Deleting a user removes
the account and every analysis it owns, as DELETE /api/v1/auth/me does.

It uses DATABASE_URL, like the app, and needs the database to be migrated.
"""

import argparse
import getpass
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from app.config import Settings
from app.errors import StartupError
from app.services.accounts import hash_password, normalize_email, password_problem
from app.storage.accounts import AccountRepository
from app.storage.db import Database
from app.storage.migrations import ensure_current


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.admin", description="Reset a password or delete an account."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset-password", help="set a new password and end every session")
    reset.add_argument("email")
    reset.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the new password from the first line of standard input",
    )
    delete = commands.add_parser("delete-user", help="delete an account and all of its data")
    delete.add_argument("email")
    delete.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    prompt_password: Callable[[str], str] = getpass.getpass,
    prompt: Callable[[str], str] = input,
) -> int:
    args = _parse(argv)
    settings = settings or Settings()
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    db = Database(settings.database_url)
    try:
        try:
            ensure_current(db.engine)
        except StartupError as exc:
            print(str(exc), file=out)
            return 2
        for session in db.session():
            repo = AccountRepository(session)
            user = repo.by_email(normalize_email(args.email))
            if user is None:
                print("No account with that email.", file=out)
                return 1
            if args.command == "reset-password":
                if args.password_stdin:
                    password = stdin.readline().rstrip("\r\n")
                else:
                    password = prompt_password("New password: ")
                    if prompt_password("Same password again: ") != password:
                        print("The two passwords differ. Nothing changed.", file=out)
                        return 2
                problem = password_problem(password)
                if problem is not None:
                    print(f"{problem} Nothing changed.", file=out)
                    return 2
                ended = repo.reset_password(user, hash_password(password))
                print(f"Password reset. {ended} session(s) of that account ended.", file=out)
                return 0
            if not args.yes and normalize_email(prompt("Type the email again to delete: ")) != (
                user.email
            ):
                print("That doesn't match. Nothing was deleted.", file=out)
                return 2
            analyses = repo.delete_user(user.id)
            print(f"Deleted the account and {analyses} analysis(es).", file=out)
            return 0
    finally:
        db.engine.dispose()
    raise AssertionError("unreachable")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
