import asyncio
import inspect
import logging
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional


class BackgroundTaskRuntime:
    """Run long async jobs on a dedicated event loop thread."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive() and self._loop and not self._loop.is_closed():
                return
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="media-hub-background",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    async def _run_guarded(self, job_factory: Callable[..., Any], args: tuple, kwargs: dict, label: str) -> Any:
        try:
            result = job_factory(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Background task failed: %s", label or getattr(job_factory, "__name__", "job"))
            raise

    def submit(self, job_factory: Callable[..., Any], *args: Any, label: str = "", **kwargs: Any) -> Future:
        self.start()
        if not self._loop or self._loop.is_closed():
            raise RuntimeError("后台任务运行器未就绪")
        coroutine = self._run_guarded(job_factory, args, kwargs, label)
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop)

    def stop(self) -> None:
        loop = self._loop
        if not loop or loop.is_closed():
            return
        loop.call_soon_threadsafe(loop.stop)


background_runtime = BackgroundTaskRuntime()


def submit_background(job_factory: Callable[..., Any], *args: Any, label: str = "", **kwargs: Any) -> Future:
    return background_runtime.submit(job_factory, *args, label=label, **kwargs)


def start_background_runtime() -> None:
    background_runtime.start()


def stop_background_runtime() -> None:
    background_runtime.stop()
