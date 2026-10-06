"""The production layer webos adds on top of a repository's compose file.

The repository stays untouched. webos writes `docker-compose.webos.yml` next to the
compose file and runs both together:

- the web service is published on 127.0.0.1 only, on the port webos assigned;
- every other service publishes nothing (databases stay inside Docker's network);
- everything restarts unless stopped;
- optionally, dev-only bind mounts (`.:/app`) and dev commands (`--reload`) are dropped.

It uses Compose's `!override` / `!reset` tags, so the repository's values are replaced
rather than merged. The agent's safety check runs on the merged result either way.
"""

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
DEV_COMMAND_HINTS = (
    "--reload",
    "--watch",
    "npm run dev",
    "yarn dev",
    "pnpm dev",
    "nodemon",
    "flask run",
    "manage.py runserver",
    "vite",
)
WEB_NAME_HINTS = ("web", "api", "app", "server", "frontend", "backend", "site")


@dataclass(frozen=True)
class ServiceChoice:
    # Targets of the volumes to keep. None leaves the service's volumes as they are.
    keep_volumes: tuple[str, ...] | None = None
    use_image_command: bool = False


def generate_override(
    *,
    compose_file: str,
    services: dict[str, dict[str, Any]],
    web_service: str,
    container_port: int,
    host_port: int,
    choices: dict[str, ServiceChoice],
) -> str:
    if web_service not in services:
        raise ValueError(f"{web_service} isn't a service in {compose_file}")
    lines = [
        f"# Written by webos: production settings layered on {compose_file}.",
        "# Change them in webos (project page); redeploys rewrite this file.",
        "services:",
    ]
    for name, service in sorted(services.items()):
        if not SERVICE_NAME.fullmatch(name):
            raise ValueError(f"unexpected service name {name!r}")
        choice = choices.get(name, ServiceChoice())
        lines += [f"  {name}:", "    restart: unless-stopped"]
        if name == web_service:
            lines += ["    ports: !override", f'      - "127.0.0.1:{host_port}:{container_port}"']
        elif service.get("ports"):
            lines.append("    ports: !reset []")
        if choice.use_image_command:
            lines.append("    command: !reset null")
        if choice.keep_volumes is not None:
            kept = [
                v for v in service.get("volumes") or [] if v.get("target") in choice.keep_volumes
            ]
            if not kept:
                lines.append("    volumes: !override []")
            else:
                lines.append("    volumes: !override")
                for volume in kept:
                    # JSON strings are valid YAML, and safely quoted.
                    lines += [
                        f"      - type: {json.dumps(volume.get('type') or 'volume')}",
                        f"        source: {json.dumps(volume.get('source') or '')}",
                        f"        target: {json.dumps(volume.get('target') or '')}",
                    ]
    return "\n".join(lines) + "\n"


def command_text(command: Any) -> str:
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return str(command or "")


def suggest(
    services: dict[str, dict[str, Any]], *, project_dir: str, compose_file: str
) -> dict[str, Any]:
    """A first guess at the wizard's choices, which the user then confirms or changes."""
    compose_dir = str(PurePosixPath(project_dir) / PurePosixPath(compose_file).parent)
    project_root = str(PurePosixPath(project_dir))

    def container_ports(service: dict[str, Any]) -> list[int]:
        ports = [int(p["target"]) for p in service.get("ports") or [] if p.get("target")]
        for item in service.get("expose") or []:
            text = str(item).split("/")[0]
            if text.isdigit():
                ports.append(int(text))
        return ports

    candidates = [name for name, svc in sorted(services.items()) if container_ports(svc)]
    web = next(
        (n for hint in WEB_NAME_HINTS for n in candidates if hint in n.lower()),
        candidates[0] if candidates else next(iter(sorted(services)), None),
    )
    choices: dict[str, dict[str, Any]] = {}
    for name, service in services.items():
        volumes = service.get("volumes") or []
        dev_mounts = [
            v
            for v in volumes
            if v.get("type") == "bind"
            and str(PurePosixPath(str(v.get("source", "")))) in (compose_dir, project_root)
        ]
        command = command_text(service.get("command"))
        choices[name] = {
            "keep_volumes": (
                [v.get("target") for v in volumes if v not in dev_mounts] if dev_mounts else None
            ),
            "use_image_command": bool(service.get("build"))
            and any(hint in command for hint in DEV_COMMAND_HINTS),
            "dev_mounts": [v.get("target") for v in dev_mounts],
        }
    ports = container_ports(services[web]) if web else []
    return {"web_service": web, "container_port": ports[0] if ports else None, "services": choices}
