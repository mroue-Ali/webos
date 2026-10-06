"""Talks to webos-agent, the host helper, over its Unix socket (see agent/webos_agent.py).

One JSON request per connection; the agent answers with {"log": ...} lines while it works
and a final {"ok": ...}.
"""

import asyncio
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

LogFn = Callable[[str], None]


class AgentUnavailable(Exception):
    """webos-agent isn't installed or isn't running."""


class AgentError(Exception):
    """The agent refused, or the step failed. The message says why."""


class Agent(Protocol):
    async def call(
        self,
        verb: str,
        args: dict[str, Any] | None = None,
        *,
        on_log: LogFn | None = None,
        timeout: float = 120,  # noqa: ASYNC109 - the step's budget, applied with asyncio.timeout
    ) -> Any: ...


class AgentClient:
    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path

    async def call(
        self,
        verb: str,
        args: dict[str, Any] | None = None,
        *,
        on_log: LogFn | None = None,
        timeout: float = 120,  # noqa: ASYNC109 - applied below with asyncio.timeout
    ) -> Any:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.socket_path), limit=2**20), 5
            )
        except (OSError, TimeoutError, AttributeError) as exc:
            raise AgentUnavailable(
                f"can't reach webos-agent at {self.socket_path}; is it installed and running?"
            ) from exc
        try:
            writer.write((json.dumps({"verb": verb, "args": args or {}}) + "\n").encode())
            await writer.drain()
            async with asyncio.timeout(timeout):
                while True:
                    line = await reader.readline()
                    if not line:
                        raise AgentError("webos-agent closed the connection")
                    message = json.loads(line)
                    if "log" in message:
                        if on_log is not None:
                            on_log(str(message["log"]))
                        continue
                    if message.get("ok"):
                        return message.get("result")
                    raise AgentError(str(message.get("error") or "webos-agent refused"))
        except TimeoutError as exc:
            raise AgentError(f"{verb} took longer than {int(timeout)}s") from exc
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
