import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from webos import audit
from webos.context import get_context
from webos.db import get_db
from webos.models import User
from webos.schemas import LoginIn, LoginOut, MeOut
from webos.security import totp
from webos.security.auth import clear_session, issue_session, require_user
from webos.security.passwords import hash_password, needs_rehash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

INVALID_LOGIN = "Invalid username or password"
INVALID_CODE = "Invalid code"


@router.post("/login")
def login(
    body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)
) -> LoginOut:
    """Username + password. If the user has turned on 2FA, a second request adds the code."""
    ctx = get_context(request)
    ip = audit.client_ip(request)

    wait = ctx.throttle.retry_after(ip)
    if wait > 0:
        # Not written to the database, so a flood of blocked attempts can't fill the disk.
        logger.warning("login throttled for %s (%.0fs left)", ip, wait)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(math.ceil(wait))},
        )

    def fail(reason: str, message: str) -> HTTPException:
        ctx.throttle.record_failure(ip)
        audit.record_request(
            db, request, action="auth.login", outcome="error", actor=body.username, error=reason
        )
        return HTTPException(status.HTTP_401_UNAUTHORIZED, message)

    user = db.scalar(select(User).where(User.username == body.username))
    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok:
        raise fail("unknown_user" if user is None else "bad_password", INVALID_LOGIN)

    if user.totp_secret_enc is not None:
        if not body.code:
            # Right password, 2FA on: ask for the code. Not a failed attempt, but recorded,
            # so a stranger who has the password shows up in the audit log.
            audit.record_request(
                db, request, action="auth.login", outcome="started", actor=body.username
            )
            return LoginOut(code_required=True)
        secret = ctx.secrets.open(user.totp_secret_enc)
        step = totp.verify(secret, body.code, last_step=user.totp_last_step, now=ctx.clock())
        if step is None:
            # "bad_code" in the audit log means someone knows your password.
            raise fail("bad_code", INVALID_CODE)
        user.totp_last_step = step

    ctx.throttle.record_success(ip)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    db.commit()

    issue_session(response, ctx, user)
    request.state.user = user
    audit.record_request(db, request, action="auth.login", outcome="ok")
    return LoginOut(username=user.username)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    """Clears this browser's cookie. Use logout-all to end every session."""
    audit.record_request(db, request, action="auth.logout", outcome="ok")
    clear_session(response, get_context(request))


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    request: Request,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    user.session_version += 1
    db.commit()
    audit.record_request(db, request, action="auth.logout_all", outcome="ok")
    clear_session(response, get_context(request))


@router.get("/me")
def me(user: User = Depends(require_user)) -> MeOut:
    return MeOut(username=user.username)
