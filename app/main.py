from fastapi import Depends

from .core import app, require_auth
from .routes.cross_copy import router as cross_copy_router
from .routes.emby_bridge import router as emby_bridge_router
from .routes.events import router as events_router
from .routes.monitor import router as monitor_router, webhook_router
from .routes.pages import router as pages_router
from .routes.recommendation import router as recommendation_router
from .routes.resource import router as resource_router
from .routes.scraper import router as scraper_router
from .routes.servarr import router as servarr_router
from .routes.settings import router as settings_router
from .routes.strm import router as strm_router
from .routes.subscription import router as subscription_router
from .routes.tmdb import router as tmdb_router
from .routes.tree import router as tree_router

_auth_deps = [Depends(require_auth)]

app.include_router(pages_router)
app.include_router(settings_router, dependencies=_auth_deps)
app.include_router(tree_router, dependencies=_auth_deps)
app.include_router(resource_router, dependencies=_auth_deps)
app.include_router(scraper_router, dependencies=_auth_deps)
app.include_router(strm_router)
app.include_router(webhook_router)
app.include_router(subscription_router, dependencies=_auth_deps)
app.include_router(tmdb_router, dependencies=_auth_deps)
app.include_router(events_router, dependencies=_auth_deps)
app.include_router(monitor_router, dependencies=_auth_deps)
app.include_router(recommendation_router, dependencies=_auth_deps)
app.include_router(cross_copy_router, dependencies=_auth_deps)
app.include_router(servarr_router)  # 自带 /api/v3 前缀与 X-Api-Key 鉴权，不走登录会话
app.include_router(emby_bridge_router)  # 自带 /emby-bridge 前缀，对 Seerr 侧透明，不走登录会话

from . import startup  # noqa: E402,F401

__all__ = ["app"]
