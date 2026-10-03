"""webos-admin: run the server and manage the single user from a shell on the host.

Inside the container:  docker compose exec webos webos-admin <command>
"""

import argparse
import getpass
import logging
import sys
import time

import segno
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from webos import audit, migrate
from webos.config import Settings
from webos.db import make_engine
from webos.models import User, utcnow
from webos.security import totp
from webos.security.keys import derive_key
from webos.security.passwords import MIN_PASSWORD_LENGTH, hash_password
from webos.security.totp import SecretBox


class CliError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webos-admin", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="apply database migrations")
    serve = commands.add_parser("serve", help="apply migrations, then run the web server")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - inside the container
    serve.add_argument("--port", type=int, default=8000)
    create = commands.add_parser("create-user", help="create the panel user (once)")
    create.add_argument("--username", required=True)
    commands.add_parser("reset-password", help="set a new password; ends all sessions")
    commands.add_parser(
        "enable-totp", help="turn on 2FA (or replace the authenticator); ends all sessions"
    )
    commands.add_parser("disable-totp", help="turn off 2FA; ends all sessions")
    args = parser.parse_args(argv)

    settings = Settings()
    try:
        if args.command == "migrate":
            migrate.upgrade(settings.database_url)
        elif args.command == "serve":
            serve_app(settings, args.host, args.port)
        else:
            migrate.upgrade(settings.database_url)
            sessions = sessionmaker(make_engine(settings.database_url))
            secrets = SecretBox(derive_key(settings.secret_key.get_secret_value(), "totp"))
            with sessions() as db:
                if args.command == "create-user":
                    create_user(db, args.username)
                elif args.command == "reset-password":
                    reset_password(db)
                elif args.command == "enable-totp":
                    enable_totp(db, secrets)
                else:
                    disable_totp(db)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


def serve_app(settings: Settings, host: str, port: int) -> None:
    import uvicorn

    migrate.upgrade(settings.database_url)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(
        "webos.main:create_app",
        factory=True,
        host=host,
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        server_header=False,
    )


def create_user(db: Session, username: str) -> None:
    if db.scalar(select(User)) is not None:
        raise CliError("a user already exists; use reset-password instead")
    if not 1 <= len(username) <= 64:
        raise CliError("username must be 1-64 characters")
    password = prompt_password()
    db.add(User(username=username, password_hash=hash_password(password)))
    db.commit()
    audit.record(db, action="user.create", outcome="ok", actor="cli", target=username)
    print(f"Created user {username!r}. Sign in with username and password.")
    print("Optional: add a 6-digit code from a phone app with `webos-admin enable-totp`.")


def reset_password(db: Session) -> None:
    user = single_user(db)
    user.password_hash = hash_password(prompt_password())
    user.password_changed_at = utcnow()
    user.session_version += 1
    db.commit()
    audit.record(db, action="user.reset_password", outcome="ok", actor="cli", target=user.username)
    print("Password changed. All sessions have been ended.")


def enable_totp(db: Session, secrets: SecretBox) -> None:
    user = single_user(db)
    secret, step = enrol_totp(user.username)
    user.totp_secret_enc = secrets.seal(secret)
    user.totp_last_step = step
    user.session_version += 1
    db.commit()
    audit.record(db, action="user.enable_totp", outcome="ok", actor="cli", target=user.username)
    print("2FA is on: sign-in now also asks for the code from your app. Sessions ended.")


def disable_totp(db: Session) -> None:
    user = single_user(db)
    if user.totp_secret_enc is None:
        print("2FA is already off.")
        return
    user.totp_secret_enc = None
    user.totp_last_step = 0
    user.session_version += 1
    db.commit()
    audit.record(db, action="user.disable_totp", outcome="ok", actor="cli", target=user.username)
    print("2FA is off: sign in with username and password. Sessions ended.")


def single_user(db: Session) -> User:
    user: User | None = db.scalar(select(User))
    if user is None:
        raise CliError("no user yet; run create-user first")
    return user


def prompt_password() -> str:
    # rstrip: input piped from Windows arrives with CRLF, and getpass only drops the LF.
    password = getpass.getpass("New password: ").rstrip("\r")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"use at least {MIN_PASSWORD_LENGTH} characters")
    if getpass.getpass("Repeat it: ").rstrip("\r") != password:
        raise CliError("the passwords don't match")
    return password


def enrol_totp(username: str) -> tuple[str, int]:
    """Show a new secret as a QR code, and accept it only once a code from the app matches."""
    secret = totp.new_secret()
    uri = totp.provisioning_uri(secret, username)
    print("\nScan this with your authenticator app (Google Authenticator, Aegis, 1Password...):\n")
    segno.make(uri, error="m").terminal(compact=True)
    print(f"\nOr enter the key by hand: {secret}\n")
    code = input("Code shown in the app: ").strip()
    step = totp.verify(secret, code, last_step=0, now=time.time())
    if step is None:
        raise CliError("that code doesn't match; nothing was changed, run the command again")
    return secret, step


if __name__ == "__main__":
    sys.exit(main())
