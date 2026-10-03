from collections.abc import Callable
from dataclasses import replace

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from webos.context import AppContext, get_context
from webos.db import get_db
from webos.models import User
from webos.security.sessions import SessionData

REFRESH_AFTER_SECONDS = 60


def issue_session(response: Response, ctx: AppContext, user: User) -> None:
    now = int(ctx.clock())
    _set_cookie(
        response, ctx, SessionData(uid=user.id, ver=user.session_version, iat=now, seen=now)
    )


def clear_session(response: Response, ctx: AppContext) -> None:
    response.delete_cookie(
        ctx.cookie_name,
        path="/",
        secure=ctx.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _set_cookie(response: Response, ctx: AppContext, data: SessionData) -> None:
    response.set_cookie(
        ctx.cookie_name,
        ctx.sessions.dump(data),
        max_age=ctx.sessions.max_seconds,
        path="/",
        secure=ctx.settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def require_user(request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    """The signed-in user, or 401. Slides the idle timeout forward on activity."""
    ctx = get_context(request)
    token = request.cookies.get(ctx.cookie_name)
    now = ctx.clock()
    data = ctx.sessions.load(token, now=now) if token else None
    user = db.get(User, data.uid) if data else None
    if data is None or user is None or user.session_version != data.ver:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    if now - data.seen >= REFRESH_AFTER_SECONDS:
        _set_cookie(response, ctx, replace(data, seen=int(now)))
    request.state.user = user
    # The cookie the browser holds right now; streams use it to know when to end.
    request.state.session = data
    return user


def session_guard(request: Request) -> Callable[[], bool]:
    """For long-lived streams: a check that turns False once the session ends.

    It ends at the idle/absolute deadline of the cookie that opened the stream, or as soon
    as the session version is bumped (log out everywhere, password or TOTP reset).
    """
    ctx = get_context(request)
    data: SessionData = request.state.session
    deadline = ctx.sessions.deadline(data)

    def still_valid() -> bool:
        if ctx.clock() >= deadline:
            return False
        with ctx.sessionmaker() as db:
            user = db.get(User, data.uid)
            return user is not None and user.session_version == data.ver

    return still_valid
