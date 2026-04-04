from .core import app
from .routes.events import router as events_router
from .routes.monitor import router as monitor_router
from .routes.pages import router as pages_router
from .routes.resource import router as resource_router
from .routes.settings import router as settings_router
from .routes.tree import router as tree_router

app.include_router(pages_router)
app.include_router(settings_router)
app.include_router(tree_router)
app.include_router(resource_router)
app.include_router(events_router)
app.include_router(monitor_router)

from . import startup  # noqa: E402,F401

__all__ = ["app"]
