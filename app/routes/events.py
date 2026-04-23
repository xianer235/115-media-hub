import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..core import *  # noqa: F401,F403

router = APIRouter()


@router.get("/events")
async def stream_events(request: Request) -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
    ui_event_subscribers.add(queue)
    cfg = get_config()
    queue.put_nowait(json.dumps(build_ui_state_payload(cfg), ensure_ascii=False))

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=UI_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"retry: {UI_EVENT_RETRY_MS}\nevent: state\ndata: {payload}\n\n"
        finally:
            ui_event_subscribers.discard(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
