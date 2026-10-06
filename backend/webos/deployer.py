"""Deploy pipelines: ordered webos-agent steps, streamed live and kept as history.

create  first deploy from the wizard: env, check, build, health, DNS, nginx, certificate
manual  "Deploy now": pull, check, build, health
auto    the same, started by auto-deploy when the branch has a new commit
env     after editing the environment: write it, check, rebuild, health
"""

import asyncio
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from webos import audit
from webos.agent_client import Agent, AgentError, AgentUnavailable
from webos.models import Deployment, Project, utcnow

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 20_000
MAX_LOG_CHARS = 400_000
TRIGGERS = ("create", "manual", "auto", "env")


class DeployBusy(Exception):
    pass


class DeployFailed(Exception):
    pass


@dataclass
class Run:
    """A deployment in progress: its log so far, and whoever is watching it live."""

    deployment_id: int
    slug: str
    lines: list[str] = field(default_factory=list)
    listeners: set[asyncio.Queue[str | None]] = field(default_factory=set)
    finished: bool = False

    def log(self, line: str) -> None:
        if len(self.lines) >= MAX_LOG_LINES:
            return
        self.lines.append(line)
        for queue in self.listeners:
            queue.put_nowait(line)

    def finish(self) -> None:
        self.finished = True
        for queue in self.listeners:
            queue.put_nowait(None)


@dataclass(frozen=True)
class SiteSpec:
    """The project's deploy settings, read once when a deployment starts."""

    slug: str
    branch: str
    compose_file: str
    env_file: str
    port: int
    domain: str
    aliases: tuple[str, ...]
    override: str

    @classmethod
    def of(cls, project: Project) -> "SiteSpec":
        missing = [
            name
            for name in ("branch", "compose_file", "port", "domain", "override")
            if not getattr(project, name)
        ]
        if missing:
            raise DeployFailed(
                f"{project.slug} isn't fully set up yet (missing {', '.join(missing)})"
            )
        return cls(
            slug=project.slug,
            branch=project.branch or "",
            compose_file=project.compose_file or "",
            env_file=project.env_file or ".env",
            port=project.port or 0,
            domain=project.domain or "",
            aliases=tuple(project.alias_list),
            override=project.override or "",
        )


async def resolve(name: str) -> list[str]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(name, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return sorted({str(info[4][0]) for info in infos})


Step = tuple[str, Callable[[Run], Awaitable[Any]]]


class Deployer:
    def __init__(self, agent: Agent, sessions: sessionmaker[Session]) -> None:
        self.agent = agent
        self.sessions = sessions
        self.runs: dict[int, Run] = {}
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        # The last commit auto-deploy tried per site, so a broken commit isn't retried forever.
        self._auto_attempted: dict[str, str] = {}

    def busy(self, slug: str) -> bool:
        return slug in self._busy

    def mark_interrupted(self) -> None:
        """At startup: deployments left 'running' by a panel restart can't be resumed."""
        with self.sessions() as db:
            for deployment in db.scalars(select(Deployment).where(Deployment.status == "running")):
                deployment.status = "failed"
                deployment.error = "interrupted: the panel restarted during this deployment"
                deployment.finished_at = utcnow()
            db.commit()

    async def start(
        self, slug: str, trigger: str, actor: str | None, *, env_content: str | None = None
    ) -> int:
        if trigger not in TRIGGERS:
            raise ValueError(trigger)
        if slug in self._busy:
            raise DeployBusy(f"{slug} is already deploying")
        with self.sessions() as db:
            project = db.scalar(select(Project).where(Project.slug == slug))
            if project is None or not project.managed:
                raise DeployFailed(f"{slug} isn't a site webos deployed")
            spec = SiteSpec.of(project)
            deployment = Deployment(
                project_id=project.id, trigger=trigger, status="running", actor=actor, log=""
            )
            db.add(deployment)
            db.commit()
            deployment_id = deployment.id
            audit.record(
                db,
                action=f"deploy.{trigger}",
                outcome="started",
                actor=actor,
                target=slug,
                params={"deployment": deployment_id},
            )
        self._busy.add(slug)
        run = Run(deployment_id, slug)
        self.runs[deployment_id] = run
        task = asyncio.create_task(self._execute(run, spec, trigger, actor, env_content))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return deployment_id

    async def _execute(
        self, run: Run, spec: SiteSpec, trigger: str, actor: str | None, env_content: str | None
    ) -> None:
        status, error, head = "ok", None, {}
        try:
            for title, step in self._steps(spec, trigger, env_content):
                run.log(f"==> {title}")
                result = await step(run)
                if isinstance(result, dict) and result.get("commit"):
                    head = result
            run.log("==> Done")
        except (AgentError, AgentUnavailable, DeployFailed) as exc:
            status, error = "failed", str(exc)
            run.log(f"!! {exc}")
        except Exception:
            logger.exception("deployment %s crashed", run.deployment_id)
            status, error = "failed", "internal error (see the panel's logs)"
            run.log(f"!! {error}")
        finally:
            self._save(run, spec, trigger, actor, status, error, head)
            run.finish()
            self._busy.discard(spec.slug)
            asyncio.get_running_loop().call_later(600, self.runs.pop, run.deployment_id, None)

    def _save(
        self,
        run: Run,
        spec: SiteSpec,
        trigger: str,
        actor: str | None,
        status: str,
        error: str | None,
        head: dict[str, Any],
    ) -> None:
        log = "\n".join(run.lines)
        with self.sessions() as db:
            deployment = db.get(Deployment, run.deployment_id)
            project = db.scalar(select(Project).where(Project.slug == spec.slug))
            if deployment is not None:
                deployment.status = status
                deployment.error = error[:500] if error else None
                deployment.finished_at = utcnow()
                deployment.commit = head.get("commit")
                deployment.subject = str(head.get("subject") or "")[:200] or None
                deployment.log = log[-MAX_LOG_CHARS:]
            if project is not None and status == "ok":
                project.deployed_commit = head.get("commit") or project.deployed_commit
                if trigger == "create":
                    project.state = "active"
            db.commit()
            audit.record(
                db,
                action=f"deploy.{trigger}",
                outcome=status if status == "ok" else "error",
                actor=actor,
                target=spec.slug,
                error=error,
                params={"deployment": run.deployment_id, "commit": (head.get("commit") or "")[:12]},
            )

    def _steps(self, spec: SiteSpec, trigger: str, env_content: str | None) -> list[Step]:
        name = {"name": spec.slug}
        compose = {**name, "compose_file": spec.compose_file}
        domains = {"domain": spec.domain, "aliases": list(spec.aliases)}

        def call(
            verb: str, args: dict[str, Any], timeout: float = 120
        ) -> Callable[[Run], Awaitable[Any]]:
            return lambda run: self.agent.call(verb, args, on_log=run.log, timeout=timeout)

        steps: list[Step] = []
        if trigger in ("manual", "auto"):
            steps.append(
                ("Pull the latest code", call("pull", {**name, "branch": spec.branch}, 900))
            )
        else:
            steps.append(("Read the current commit", call("head", name)))
        if env_content is not None:
            steps.append(
                (
                    "Write the environment file",
                    call(
                        "write_env", {**compose, "env_file": spec.env_file, "content": env_content}
                    ),
                )
            )
        steps.append(("Check the compose file", lambda run: self._check(run, compose, spec)))
        steps.append(("Build and start the containers", call("up", compose, 1900)))
        steps.append(("Health check", call("http_check", {"port": spec.port, "timeout": 120}, 180)))
        if trigger == "create":
            steps.append(("Check DNS", lambda run: self._check_dns(run, spec)))
            steps.append(
                ("nginx site", call("nginx_site", {**name, **domains, "port": spec.port}, 120))
            )
            steps.append(("HTTPS certificate", call("certbot", domains, 360)))
        return steps

    async def _check(self, run: Run, compose: dict[str, Any], spec: SiteSpec) -> None:
        result = await self.agent.call(
            "compose_config", {**compose, "override": spec.override}, on_log=run.log
        )
        problems = result.get("violations") or []
        for problem in problems:
            run.log(f"   refused: {problem}")
        if problems:
            raise DeployFailed("the safety check refused this compose setup (see above)")
        run.log(f"   services: {', '.join(sorted(result.get('services') or {}))}")

    async def _check_dns(self, run: Run, spec: SiteSpec) -> None:
        server = set((await self.agent.call("ping", {})).get("host_ips") or [])
        if not server:
            run.log("   couldn't read this server's addresses; skipping the DNS check")
            return
        for host in (spec.domain, *spec.aliases):
            found = await resolve(host)
            if not set(found) & server:
                shown = ", ".join(found) or "nothing"
                raise DeployFailed(
                    f"{host} points to {shown}, not this server ({', '.join(sorted(server))}). "
                    "Add an A record for it at your DNS provider, wait a few minutes, then retry."
                )
            run.log(f"   {host} -> {', '.join(found)}")

    async def check_for_updates(self) -> None:
        """Auto-deploy: start a deployment for each site whose branch has a new commit."""
        with self.sessions() as db:
            sites = [
                (p.slug, p.branch or "", p.deployed_commit)
                for p in db.scalars(
                    select(Project).where(
                        Project.managed.is_(True),
                        Project.auto_deploy.is_(True),
                        Project.state == "active",
                    )
                )
            ]
        for slug, branch, deployed in sites:
            if self.busy(slug) or not branch:
                continue
            try:
                head = await self.agent.call(
                    "remote_head", {"name": slug, "branch": branch}, timeout=60
                )
            except AgentUnavailable:
                return
            except AgentError as exc:
                logger.warning("auto-deploy: can't check %s: %s", slug, exc)
                continue
            commit = str(head.get("commit") or "")
            if commit and commit != deployed and self._auto_attempted.get(slug) != commit:
                self._auto_attempted[slug] = commit
                logger.info("auto-deploy: %s has new commit %s", slug, commit[:12])
                try:
                    await self.start(slug, "auto", "auto-deploy")
                except (DeployBusy, DeployFailed) as exc:
                    logger.warning("auto-deploy: %s", exc)


async def auto_deploy_loop(deployer: Deployer, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await deployer.check_for_updates()
        except Exception:
            logger.exception("auto-deploy check failed")
