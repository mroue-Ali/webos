"""Server-Sent Events: live container events and log lines."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import cast

from starlette.responses import StreamingResponse

from webos.docker_api import DockerError

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15.0
SESSION_CHECK_SECONDS = 30.0
RECONNECT_MS = 3000

# (event name, JSON-serialisable data, optional event id)
SseEvent = tuple[str, object, str | None]
_DONE = object()


def format_event(event: str, data: object, event_id: str | None = None) -> str:
    # json.dumps escapes newlines, so log text can never inject extra SSE fields.
    lines = [f"event: {event}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"


async def _stream(
    source: AsyncIterator[SseEvent], session_ok: Callable[[], bool]
) -> AsyncIterator[str]:
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=1000)

    async def pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except DockerError as exc:
            await queue.put(("error", {"message": exc.message}, None))
        except Exception:
            logger.exception("event stream failed")
            await queue.put(("error", {"message": "Stream failed"}, None))
        await queue.put(_DONE)

    task = asyncio.create_task(pump())
    next_check = time.monotonic() + SESSION_CHECK_SECONDS
    try:
        # When a stream ends (say, the container stopped), the browser reconnects after
        # this delay and sends Last-Event-ID, so logs pick up where they left off.
        yield f"retry: {RECONNECT_MS}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), KEEPALIVE_SECONDS)
            except TimeoutError:
                item = None
            if time.monotonic() >= next_check or item is None:
                if not session_ok():
                    yield format_event("end", {"reason": "session"})
                    return
                next_check = time.monotonic() + SESSION_CHECK_SECONDS
            if item is None:
                yield ": keepalive\n\n"
            elif item is _DONE:
                yield format_event("end", {"reason": "eof"})
                return
            else:
                event, data, event_id = cast(SseEvent, item)
                yield format_event(event, data, event_id)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def sse_response(
    source: AsyncIterator[SseEvent], session_ok: Callable[[], bool]
) -> StreamingResponse:
    return StreamingResponse(
        _stream(source, session_ok),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
