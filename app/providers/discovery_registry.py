"""
DiscoveryProvider 注册表 + 内置 Provider 实现

用法:
    from .discovery_registry import (
        register_discovery, search_all, builtin_providers,
        get_discovery_provider, list_discovery_providers,
    )

    # 注册自定义 Provider
    register_discovery(MyProvider())

    # 搜索所有已注册 Provider
    results = search_all("黑客帝国")

    # 列出所有已注册 Provider
    for p in list_discovery_providers():
        print(p.name, p.label)
"""

import logging
from typing import Any, Dict, List, Optional

from .discovery_base import DiscoveryProvider, DiscoveryResult

log = logging.getLogger("discovery")

# ── 注册表 ────────────────────────────────────────────────────────────────

_discovery_providers: Dict[str, DiscoveryProvider] = {}


def register_discovery(provider: DiscoveryProvider):
    """注册一个 DiscoveryProvider"""
    if not provider.name:
        raise ValueError("Provider name cannot be empty")
    if provider.name in _discovery_providers:
        log.warning(
            "Discovery provider %s 已存在，覆盖旧实现",
            provider.name,
        )
    _discovery_providers[provider.name] = provider
    log.info("Registered discovery provider: %s (%s)", provider.name, provider.label)


def get_discovery_provider(name: str) -> Optional[DiscoveryProvider]:
    """按名称获取 Provider"""
    return _discovery_providers.get(name)


def list_discovery_providers() -> List[DiscoveryProvider]:
    """列出所有已注册 Provider"""
    return list(_discovery_providers.values())


def search_all(
    keyword: str,
    provider_filter: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    轮询所有已注册 Provider 搜索资源。

    Args:
        keyword: 搜索关键词
        provider_filter: 限定搜索的 Provider 名称列表，None=全部
        **kwargs: 传递给各 Provider 的扩展参数

    Returns:
        {
            "results": [DiscoveryResult, ...],
            "stats": {"total": N, "by_provider": {...}},
            "errors": [...]
        }
    """
    results: List[DiscoveryResult] = []
    errors: List[Dict[str, Any]] = []
    by_provider: Dict[str, int] = {}

    for p in list_discovery_providers():
        if provider_filter and p.name not in provider_filter:
            continue
        try:
            items = p.search(keyword, **kwargs)
            if items:
                results.extend(items)
                by_provider[p.name] = len(items)
        except Exception as e:
            errors.append({"provider": p.name, "error": str(e)})
            log.warning("Discovery provider %s search failed: %s", p.name, e)

    return {
        "results": results,
        "stats": {"total": len(results), "by_provider": by_provider},
        "errors": errors,
    }


# ── 内置 Provider: Telegram 频道搜索 ──────────────────────────────────────

class TelegramDiscoveryProvider(DiscoveryProvider):
    """包装 resource_tg 的 TG 频道搜索"""

    name = "telegram"
    label = "Telegram 频道"

    def __init__(self):
        self._cfg_cache: Optional[Dict[str, Any]] = None

    def _get_cfg(self) -> Dict[str, Any]:
        if self._cfg_cache is None:
            from ..core import get_config
            self._cfg_cache = get_config()
        return self._cfg_cache

    def search(self, keyword: str, **kwargs) -> List[DiscoveryResult]:
        from ..resource_tg import (
            TG_SEARCH_MATCH_LIMIT_PER_CHANNEL,
            TG_SEARCH_TOTAL_LIMIT,
            fetch_telegram_channel_posts_page,
        )
        from ..core import get_config

        cfg = get_config()
        sources = cfg.get("resource_sources", [])
        if not isinstance(sources, list) or not sources:
            return []

        limit = max(1, min(int(kwargs.get("limit", 0) or TG_SEARCH_MATCH_LIMIT_PER_CHANNEL), TG_SEARCH_TOTAL_LIMIT))
        results: List[DiscoveryResult] = []

        for source in sources:
            channel_id = str(source.get("channel_id", "") or "").strip()
            if not channel_id or not source.get("enabled", True):
                continue
            try:
                posts_data = fetch_telegram_channel_posts_page(
                    cfg, source,
                    limit=limit,
                    query=keyword,
                )
                items = posts_data.get("posts", posts_data.get("items", [])) if isinstance(posts_data, dict) else (posts_data if isinstance(posts_data, list) else [])
                from ..resource_linking import pick_resource_title, guess_resource_quality

                for item in items:
                    raw_text = str(item.get("raw_text", "") or "").strip()
                    title = pick_resource_title(raw_text) or str(item.get("title", "") or "").strip()
                    if not title:
                        continue
                    link = item.get("link_url", "") or ""
                    link_type = item.get("link_type", "") or ""
                    quality = guess_resource_quality(raw_text)
                    source_name = str(source.get("name", "") or source.get("channel_id", "") or "").strip()
                    results.append(DiscoveryResult(
                        title=title,
                        link_url=link,
                        link_type=link_type or "",
                        quality=quality or "",
                        source_name=f"TG:{source_name}",
                        extra={"channel_id": channel_id, "raw_text": raw_text},
                    ))
            except Exception:
                continue

        return results

    def validate(self) -> bool:
        cfg = self._get_cfg()
        sources = cfg.get("resource_sources", [])
        return bool(sources) and any(s.get("enabled", True) for s in sources)

    @property
    def config_fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "resource_sources", "label": "TG 频道列表", "type": "list"},
            {"key": "tg_proxy_enabled", "label": "TG 代理", "type": "bool"},
            {"key": "tg_proxy_host", "label": "代理地址", "type": "text"},
            {"key": "tg_proxy_port", "label": "代理端口", "type": "text"},
        ]


# ── 内置 Provider: PanSou 盘搜 ───────────────────────────────────────────

class PansouDiscoveryProvider(DiscoveryProvider):
    """包装 pansou.py 的盘搜"""

    name = "pansou"
    label = "PanSou 盘搜"

    def search(self, keyword: str, **kwargs) -> List[DiscoveryResult]:
        from ..providers.pansou import request_pansou_search, PANSOU_SEARCH_TOTAL_LIMIT
        from ..core import get_config

        cfg = get_config()
        base_url = str(cfg.get("pansou_base_url", "") or "").strip()
        if not base_url:
            return []

        limit = max(1, min(int(kwargs.get("limit", 0) or PANSOU_SEARCH_TOTAL_LIMIT), 200))
        provider = str(kwargs.get("provider_filter", "all") or "all").strip()

        try:
            result = request_pansou_search(
                cfg, keyword,
                provider_filter=provider,
                limit=limit,
            )
            items = result.get("items", [])
        except Exception:
            return []

        results: List[DiscoveryResult] = []
        for item in items:
            title = str(item.get("title", "") or "").strip()
            if not title:
                continue
            results.append(DiscoveryResult(
                title=title,
                link_url=str(item.get("link_url", "") or "").strip(),
                link_type=str(item.get("link_type", "") or "").strip(),
                quality=str(item.get("quality", "") or "").strip(),
                source_name=str(item.get("source_name", "") or "PanSou").strip(),
                year=str(item.get("year", "") or "").strip(),
                receive_code=str(item.get("receive_code", "") or "").strip(),
                extra={"channel": str(item.get("channel_name", "") or "").strip()},
            ))

        return results

    def validate(self) -> bool:
        from ..core import get_config
        cfg = get_config()
        return bool(str(cfg.get("pansou_base_url", "") or "").strip())

    @property
    def config_fields(self) -> List[Dict[str, Any]]:
        return [
            {"key": "pansou_base_url", "label": "PanSou 地址", "type": "url"},
            {"key": "pansou_username", "label": "账号", "type": "text"},
            {"key": "pansou_password", "label": "密码", "type": "password"},
            {"key": "pansou_src", "label": "搜索源", "type": "text"},
        ]


# ── 自动注册内置 Provider ─────────────────────────────────────────────────

register_discovery(TelegramDiscoveryProvider())
register_discovery(PansouDiscoveryProvider())
