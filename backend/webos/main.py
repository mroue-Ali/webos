import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from webos import __version__
from webos.agent_client import Agent, AgentClient, AgentError, AgentUnavailable
from webos.config import Settings
from webos.context import AppContext
from webos.db import make_engine
from webos.deployer import DeployBusy, Deployer, DeployFailed, auto_deploy_loop
from webos.docker_api import DockerClient, DockerError
from webos.metrics import HostSampler, ServerMetrics
from webos.routers import audit_log, auth, containers, overview, projects, server, sites
from webos.security.keys import derive_key
from webos.security.middleware import (
    OriginGuardMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)
from webos.security.sessions import SessionCodec
from webos.security.throttle import LoginThrottle
from webos.security.totp import SecretBox


class SPAStaticFiles(StaticFiles):
    """Serves the built frontend; unknown non-API paths get index.html (client-side routes)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)


def create_app(
    settings: Settings | None = None,
    *,
    docker: DockerClient | None = None,
    agent: Agent | None = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    docker = docker or DockerClient(settings.docker_url)
    agent = agent or AgentClient(settings.agent_socket)
    sessions = sessionmaker(engine, expire_on_commit=False)
    secret = settings.secret_key.get_secret_value()

    ctx = AppContext(
        settings=settings,
        sessionmaker=sessions,
        docker=docker,
        sessions=SessionCodec(
            derive_key(secret, "session"),
            idle_seconds=settings.session_idle_minutes * 60,
            max_seconds=settings.session_max_hours * 3600,
        ),
        secrets=SecretBox(derive_key(secret, "totp")),
        throttle=LoginThrottle(),
        metrics=ServerMetrics(
            docker,
            HostSampler(
                proc_root=settings.proc_root,
                net_dev=settings.host_net_dev,
                disk_path=settings.disk_path,
                interval=settings.metrics_interval_seconds,
                clock=clock,
            ),
        ),
        agent=agent,
        deployer=Deployer(agent, sessions),
        clock=clock,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        ctx.metrics.sampler.sample()  # a baseline, so the first CPU % needs one interval
        sampler = asyncio.create_task(ctx.metrics.sampler.run())
        ctx.deployer.mark_interrupted()
        deploys = asyncio.create_task(
            auto_deploy_loop(ctx.deployer, settings.auto_deploy_interval_seconds)
        )
        yield
        for task in (sampler, deploys):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await docker.aclose()
        engine.dispose()

    app = FastAPI(
        title="webos",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
    )
    app.state.ctx = ctx

    @app.exception_handler(DockerError)
    async def docker_error(_request: Request, exc: DockerError) -> JSONResponse:
        # Pass through "no such container" and similar; anything else is a gateway problem.
        code = exc.status if exc.status in (400, 404, 409) else 502
        return JSONResponse({"detail": exc.message}, status_code=code)

    @app.exception_handler(AgentUnavailable)
    async def agent_unavailable(_request: Request, exc: AgentUnavailable) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(AgentError)
    async def agent_error(_request: Request, exc: AgentError) -> JSONResponse:
        # The agent's refusals and failures are meant to be read: pass them through.
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(DeployBusy)
    async def deploy_busy(_request: Request, exc: DeployBusy) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(DeployFailed)
    async def deploy_failed(_request: Request, exc: DeployFailed) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    for module in (auth, overview, server, sites, projects, containers, audit_log):
        app.include_router(module.router)

    static_dir = settings.static_dir
    if static_dir is not None and Path(static_dir, "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")

    # The last one added runs first: headers wrap everything, including refusals.
    app.add_middleware(OriginGuardMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    return app
