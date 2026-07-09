#!/usr/bin/env python3
"""
|115 — 115 Media Hub CLI 工具

|用法:
  115 status                            系统状态
  115 search <关键词>                    搜索资源
  115 channels sync|list|classify|more|sync-names|sync-cancel
                                       管理资源频道
  115 subscribe list|add|remove|start|stop|status|logs|logs-clear|rebuild|episodes|start-with-link
                                       管理订阅
  115 jobs list|clear|retry|create|refresh|cancel
                                       管理资源任务
  115 settings [key=value...]           查看/修改配置
  115 logs [tail]                       查看系统日志
  115 cookies check|status|test         检查 Cookie 状态
  115 sign run|status                   115 每日签到
  115 tmdb search|popular|trending|detail|genres|discover
                                       TMDB 搜索
  115 monitor list|status|start|stop|logs|logs-clear|add|remove|userscript-jobs
                                       文件夹监控管理
  115 tree run|status|logs|logs-clear  目录树同步
  115 browse ls|tree|folders|create-folder
                                       网盘浏览
  115 share preview|receive|preview-batch  分享管理
  115 scrape identify|rename-plan|rename|diff|jobs|providers|entries|folders|rename-warning|jobs-create|move|copy|delete|rollback|jobs-clear
                                       刮削管理
  115 watchlist list|add|remove|update  推荐清单
  115 strm orphans|cleanup|dirs         STRM 管理
  115 resource import|preview|quick-links|delete
                                       资源中心管理
  115 api <method> <path> [body]        通用 API 调用
  115 providers                         列出网盘提供商
  115 sources list|search|test|save     发现源管理
  115 version                           版本信息
  115 health                            全链路健康检查
  115 stats                             统计摘要
  115 daemon status|logs|restart        容器管理

示例:
  115 status
  115 search "黑客帝国 4K"
  115 subscribe add "黑客帝国4" --quality 4K --savepath "/电影"
  115 tmdb search "黑客帝国"
  115 browse ls --provider 115 --cid 0
  115 share preview "https://115.com/s/swxxxx"
  115 scrape identify "/电影/黑客帝国4.mkv"
  115 settings cookie_115="xxx"
  115 api POST /resource/channels/sync '{"force": true}'
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

import httpx

API_BASE = os.environ.get("MH_API_BASE", "http://127.0.0.1:18080")
COOKIE_FILE = os.environ.get("MH_COOKIE_FILE", "/tmp/.115_cookies.txt")


# ── API Client ────────────────────────────────────────────────────────────

class Client:
    """HTTP client with session persistence."""

    def __init__(self, base_url: str = API_BASE):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[httpx.Client] = None

    def _ensure_session(self) -> httpx.Client:
        if self._session is not None:
            return self._session
        self._session = httpx.Client(base_url=self.base_url, timeout=30.0)
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE) as f:
                    jar = json.load(f)
                    for cookie_data in jar:
                        self._session.cookies.set(
                            cookie_data["name"], cookie_data["value"],
                            domain=cookie_data.get("domain", "127.0.0.1"),
                            path=cookie_data.get("path", "/"),
                        )
            except Exception:
                pass
        return self._session

    def _save_cookies(self):
        jar = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self._session.cookies.jar
        ] if self._session else []
        os.makedirs(os.path.dirname(COOKIE_FILE) or ".", exist_ok=True)
        with open(COOKIE_FILE, "w") as f:
            json.dump(jar, f)

    def _login_if_needed(self):
        session = self._ensure_session()
        r = session.get("/status-summary")
        if r.status_code == 401:
            r = session.post("/login", json={"username": "admin", "password": "admin123"})
            if r.status_code != 200:
                sys.exit(f"登录失败 (HTTP {r.status_code}): {r.text[:200]}")
            self._save_cookies()

    def request(self, method: str, path: str, body: Any = None) -> httpx.Response:
        self._login_if_needed()
        session = self._ensure_session()
        url = path if path.startswith("http") else path
        if method == "GET":
            resp = session.get(url, params=body if isinstance(body, dict) else None)
        else:
            headers = {"Content-Type": "application/json"}
            data = json.dumps(body) if body is not None else None
            resp = session.request(method, url, content=data, headers=headers)
        return resp

    def json(self, method: str, path: str, body: Any = None) -> Any:
        resp = self.request(method, path, body)
        if resp.status_code >= 400:
            sys.exit(f"HTTP {resp.status_code} {path}: {resp.text[:300]}")
        try:
            return resp.json()
        except Exception:
            return resp.text


# ── Formatters ────────────────────────────────────────────────────────────

def fmt_json(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


def fmt_status(data: dict) -> str:
    main = data.get("main", {})
    monitor = data.get("monitor", {})
    sub = data.get("subscription", {})
    lines = [
        "📊 系统状态", "",
        f"  目录树任务: {main.get('running', False) and '🟢 运行中' or '⏸ 空闲'}",
        f"  文件夹监控: {monitor.get('running', False) and '🟢 运行中' or '⏸ 空闲'}",
        f"  订阅引擎:   {sub.get('running', False) and '🟢 运行中' or '⏸ 空闲'}",
    ]
    nr = main.get("next_run")
    if nr:
        lines.append(f"  下次目录树: {nr}")
    return "\n".join(lines)


def fmt_search_items(items: list, keyword: str) -> str:
    if not items:
        return f"未找到与「{keyword}」相关的资源"
    lines = [f"找到 {len(items)} 个资源：", ""]
    for item in items[:20]:
        title = str(item.get("title", "") or "").strip()
        source = str(item.get("source_name", "") or item.get("link_type", "") or "").strip()
        quality = str(item.get("quality", "") or "").strip()
        link = str(item.get("link_url", "") or "").strip()
        lines.append(f"  • {title}")
        if quality or source:
            lines.append(f"    来源: {source or '未知'}  |  质量: {quality or '未知'}")
        if link:
            lines.append(f"    链接: {link[:80]}")
        lines.append("")
    return "\n".join(lines)


def fmt_subscriptions(tasks: list) -> str:
    if not tasks:
        return "当前没有订阅任务"
    lines = [f"共 {len(tasks)} 个订阅任务：", ""]
    for task in tasks:
        name = str(task.get("name", "") or "").strip()
        if not name:
            continue
        media_type = "电影" if task.get("media_type") == "movie" else "电视剧"
        quality = task.get("quality", "balanced")
        savepath = task.get("savepath", "")
        enabled = "🟢" if task.get("enabled", True) else "🔴"
        provider = task.get("provider", "115")
        lines.append(f"  {enabled} {name}")
        lines.append(f"    类型: {media_type}  质量: {quality}  网盘: {provider}")
        lines.append(f"    保存: {savepath}")
        lines.append("")
    return "\n".join(lines)


def fmt_logs(logs: list, title: str = "日志") -> str:
    if not logs:
        return f"暂无{title}"
    lines = []
    for log in logs[:50]:
        text = str(log.get("text", "") or "").strip()
        level = str(log.get("level", "info") or "").strip()
        icon = {"error": "❌", "warning": "⚠️", "success": "✅", "info": "ℹ️"}.get(level, "ℹ️")
        lines.append(f"  {icon} {text}")
    return "\n".join(lines)


def fmt_tmdb_items(items: list) -> str:
    if not items:
        return "未找到结果"
    lines = [f"共 {len(items)} 条：", ""]
    for item in items[:20]:
        title = str(item.get("title", "") or item.get("name", "") or "").strip()
        year = str(item.get("release_date", "") or item.get("first_air_date", "") or "")[:4]
        vote = item.get("vote_average", 0) or 0
        tmdb_id = item.get("id", "?")
        media_type = item.get("media_type", "movie")
        lines.append(f"  • {title} ({year})  ⭐ {vote:.1f}  [{media_type}:{tmdb_id}]")
    return "\n".join(lines)


def fmt_providers(data: Any) -> str:
    providers = data if isinstance(data, list) else data.get("providers", [])
    if not providers:
        return "未获取到提供商信息"
    lines = []
    for p in providers:
        name = p.get("name", "?")
        label = p.get("label", name)
        enabled = "🟢" if p.get("enabled", True) else "🔴"
        configured = "✅" if p.get("configured", p.get("cookie_configured", False)) else "❌"
        lines.append(f"  {enabled} {label} ({name})  Cookie: {configured}")
    return "\n".join(lines)


# ── Subcommands ───────────────────────────────────────────────────────────

def cmd_status(args, c: Client):
    """系统状态"""
    data = c.json("GET", "/status-summary")
    print(fmt_status(data))


def cmd_version(args, c: Client):
    """版本信息"""
    data = c.json("GET", "/version")
    print(fmt_json(data))


def cmd_search(args, c: Client):
    """搜索资源"""
    if args.action == "cancel":
        data = c.json("POST", "/resource/search/cancel")
        print(f"✅ 搜索已取消: {json.dumps(data, ensure_ascii=False)}")
        return
    keyword = " ".join(args.keyword)
    data = c.json("GET", "/resource/state", {"q": keyword, "compact": "1"})
    items = []
    if isinstance(data, dict):
        items = data.get("items", data.get("search_items", data.get("results", [])))
    print(fmt_search_items(items, keyword))


def cmd_channels(args, c: Client):
    """管理资源频道"""
    if args.action == "sync":
        data = c.json("POST", "/resource/channels/sync", {"force": args.force})
        print(f"✅ 频道同步已完成: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "list":
        cfg = c.json("GET", "/get_settings")
        sources = cfg.get("resource_sources", [])
        if not sources:
            print("未配置资源频道")
            return
        print(f"共 {len(sources)} 个资源频道：")
        for s in sources:
            name = str(s.get("name", "") or "").strip()
            channel = str(s.get("channel_id", "") or "").strip()
            enabled = "🟢" if s.get("enabled", True) else "🔴"
            print(f"  {enabled} {name} (@{channel})")
    elif args.action == "classify":
        channel_id = args.channel_id or ""
        if not channel_id:
            sys.exit("请指定频道 ID（--channel 参数）")
        data = c.json("POST", "/resource/channels/classify", {"channel_id": channel_id})
        print(f"✅ 频道分类已完成: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "more":
        channel_id = args.channel_id or ""
        if not channel_id:
            sys.exit("请指定频道 ID（--channel 参数）")
        data = c.json("POST", "/resource/channels/more", {"channel_id": channel_id, "limit": args.limit or 10})
        items = data if isinstance(data, list) else data.get("items", data.get("posts", []))
        if not items:
            print(f"频道 @{channel_id} 暂无更多内容")
            return
        print(f"频道 @{channel_id} 最新 {len(items)} 条：")
        print()
        for item in items:
            title = str(item.get("title", "") or "").strip() or "(无标题)"
            link = str(item.get("link_url", "") or "").strip()
            print(f"  • {title}")
            if link:
                print(f"    链接: {link[:80]}")
            print()

    elif args.action == "sync-names":
        channel_id = args.channel_id or ""
        if not channel_id:
            sys.exit("请指定频道 ID（--channel 参数）")
        data = c.json("POST", "/resource/channels/sync-names", {"channel_ids": [channel_id]})
        print(f"✅ 频道名称已同步: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "sync-cancel":
        data = c.json("POST", "/resource/channels/sync/cancel")
        print(f"✅ 同步已取消: {json.dumps(data, ensure_ascii=False)}")


def cmd_subscribe(args, c: Client):
    """管理订阅"""
    cfg = c.json("GET", "/get_settings")
    tasks: list = cfg.get("subscription_tasks", [])
    if not isinstance(tasks, list):
        tasks = []

    if args.action == "list":
        print(fmt_subscriptions(tasks))

    elif args.action == "add":
        title = " ".join(args.name) if args.name else ""
        if not title:
            sys.exit("请指定订阅名称")
        for t in tasks:
            if str(t.get("name", "") or "").strip() == title.strip():
                sys.exit(f"订阅「{title}」已存在")
        new_task = {
            "name": title.strip(),
            "media_type": args.type,
            "title": title.strip(),
            "keyword": title.strip(),
            "quality": args.quality,
            "savepath": args.savepath.rstrip("/") or "/电影",
            "provider": args.provider,
            "enabled": True,
            "score": 60,
            "tmdb_enabled": False,
            "schedule_weekdays": [],
            "schedule_start_time": "00:00",
            "schedule_end_time": "23:59",
            "schedule_interval_minutes": 120,
        }
        tasks.append(new_task)
        cfg["subscription_tasks"] = tasks
        c.json("POST", "/save_settings", cfg)
        print(f"✅ 已创建订阅「{title}」")

    elif args.action == "remove":
        name = " ".join(args.name)
        before = len(tasks)
        cfg["subscription_tasks"] = [t for t in tasks if str(t.get("name", "") or "").strip() != name.strip()]
        removed = before - len(cfg["subscription_tasks"])
        if removed == 0:
            sys.exit(f"未找到订阅「{name}」")
        c.json("POST", "/save_settings", cfg)
        print(f"✅ 已删除订阅「{name}」")

    elif args.action == "start":
        name = " ".join(args.name) if args.name else ""
        if name:
            data = c.json("POST", "/subscription/start", {"task_name": name})
        else:
            data = c.json("POST", "/subscription/start", {})
        print(f"✅ 订阅已触发: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "stop":
        data = c.json("POST", "/subscription/stop")
        print(f"✅ 订阅已停止: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "status":
        data = c.json("GET", "/subscription/status")
        print(fmt_json(data))

    elif args.action == "logs":
        data = c.json("GET", "/subscription/logs")
        logs = data if isinstance(data, list) else data.get("logs", [])
        print(fmt_logs(logs, "订阅日志"))

    elif args.action == "logs-clear":
        data = c.json("POST", "/subscription/logs/clear")
        print(f"✅ 订阅日志已清除: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "rebuild":
        name = args.name or ""
        if not name:
            sys.exit("请指定订阅名称（--name 参数）")
        data = c.json("POST", "/subscription/rebuild", {"name": name})
        print(f"✅ 订阅已重建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "episodes":
        name = args.name or ""
        if not name:
            sys.exit("请指定订阅名称（--name 参数）")
        data = c.json("GET", "/subscription/episodes", {"name": name})
        episodes = data if isinstance(data, list) else data.get("episodes", data.get("items", []))
        if not episodes:
            print("暂无剧集信息")
            return
        print(f"剧集更新 ({len(episodes)}):")
        for ep in episodes[:30]:
            title = str(ep.get("title", "") or ep.get("name", "") or "").strip()
            season = ep.get("season_number", ep.get("season", ""))
            episode = ep.get("episode_number", ep.get("episode", ""))
            air_date = str(ep.get("air_date", "") or "").strip()
            print(f"  • S{season}E{episode} {title}  ({air_date})")

    elif args.action == "start-with-link":
        link = args.link or ""
        if not link:
            sys.exit("请指定资源链接（--link 参数）")
        savepath = args.savepath or "/115"
        data = c.json("POST", "/subscription/start_with_link", {"link": link, "savepath": savepath})
        print(f"✅ 订阅已通过链接触发: {json.dumps(data, ensure_ascii=False)}")


def cmd_jobs(args, c: Client):
    """管理资源任务"""
    if args.action == "list":
        data = c.json("GET", "/resource/jobs/state", {"limit": args.limit, "status": args.status or ""})
        print(fmt_json(data))
    elif args.action == "clear":
        data = c.json("POST", "/resource/jobs/clear")
        print(f"✅ 已清理: {json.dumps(data, ensure_ascii=False)}")
    elif args.action in ("clear_completed", "clear-completed"):
        data = c.json("POST", "/resource/jobs/clear_completed")
        print(f"✅ 已完成任务已清理: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "retry":
        if not args.job_id:
            sys.exit("请指定任务 ID")
        data = c.json("POST", "/resource/jobs/retry", {"job_id": int(args.job_id[0])})
        print(f"✅ 已重试: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "create":
        resource_id = args.resource_id[0] if args.resource_id else ""
        if not resource_id:
            sys.exit("请指定资源 ID（先 search 获取）")
        savepath = args.savepath or "/115"
        data = c.json("POST", "/resource/jobs/create", {"resource_id": int(resource_id), "savepath": savepath})
        print(f"✅ 转存任务已创建: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "refresh":
        job_id = args.job_id[0] if args.job_id else ""
        if not job_id:
            sys.exit("请指定任务 ID")
        data = c.json("POST", "/resource/jobs/refresh", {"job_id": int(job_id)})
        print(f"✅ 已触发刷新: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "cancel":
        job_id = args.job_id[0] if args.job_id else ""
        if not job_id:
            sys.exit("请指定任务 ID")
        data = c.json("POST", "/resource/jobs/cancel", {"job_id": int(job_id)})
        print(f"✅ 已取消任务: {json.dumps(data, ensure_ascii=False)}")


def cmd_settings(args, c: Client):
    """查看/修改配置"""
    if args.test_proxy:
        result = c.json("POST", "/settings/tg_proxy/test", {})
        print(fmt_json(result))
        return
    if args.test_pansou:
        result = c.json("POST", "/settings/pansou/test", {})
        print(fmt_json(result))
        return
    if args.test_notify:
        result = c.json("POST", "/settings/notify/test", {})
        print(fmt_json(result))
        return

    cfg = c.json("GET", "/get_settings")

    if not args.kv:
        keys = [
            "cookie_115", "cookie_quark", "pansou_base_url",
            "tg_proxy_enabled", "tg_proxy_host", "tg_proxy_port",
            "tmdb_enabled", "tmdb_api_key",
            "resource_sources", "subscription_tasks", "monitor_tasks",
            "strm_external_host", "extensions",
        ]
        print(f"配置 ({len(cfg)} 项)")
        print()
        for key in keys:
            val = cfg.get(key)
            if val is None:
                continue
            if "cookie" in key.lower() or "password" in key.lower() or "secret" in key.lower() or "token" in key.lower():
                displayed = (str(val)[:8] + "..." + str(val)[-4:]) if len(str(val)) > 16 else ("***" if str(val).strip() else "(空)")
            elif isinstance(val, list):
                displayed = f"[{len(val)} 项]" if val else "[]"
            elif isinstance(val, dict):
                displayed = f"{{{len(val)} 字段}}"
            else:
                displayed = str(val)
            print(f"  {key}: {displayed}")
    else:
        for kv in args.kv:
            if "=" not in kv:
                print(f"⚠️ 跳过无效格式: {kv} (需要 key=value)")
                continue
            key, val = kv.split("=", 1)
            key = key.strip()
            existing = cfg.get(key)
            if isinstance(existing, bool):
                cfg[key] = val.lower() in ("true", "1", "yes")
            elif isinstance(existing, int):
                cfg[key] = int(val)
            elif isinstance(existing, float):
                cfg[key] = float(val)
            elif isinstance(existing, list):
                try:
                    cfg[key] = json.loads(val)
                except json.JSONDecodeError:
                    cfg[key] = [v.strip() for v in val.split(",") if v.strip()]
            elif isinstance(existing, dict):
                try:
                    cfg[key] = json.loads(val)
                except json.JSONDecodeError:
                    print(f"⚠️ 字典字段需要 JSON 格式")
                    continue
            else:
                cfg[key] = val
            print(f"  ✅ {key} = {cfg[key]}")
        c.json("POST", "/save_settings", cfg)
        print("✅ 配置已保存")


def cmd_logs(args, c: Client):
    """查看系统日志"""
    if args.action == "clear":
        data = c.json("POST", "/logs/clear")
        print(f"✅ 日志已清除: {json.dumps(data, ensure_ascii=False)}")
        return
    data = c.json("GET", "/logs")
    logs = data if isinstance(data, list) else data.get("logs", [])
    if args.tail:
        logs = logs[-int(args.tail):]
    print(fmt_logs(logs, "系统日志"))


def cmd_cookies(args, c: Client):
    """检查 Cookie 状态"""
    if args.action == "check":
        data = c.json("POST", "/settings/cookies/check")
        print(fmt_json(data))
    elif args.action == "status":
        data = c.json("GET", "/settings/cookies/status")
        print(fmt_json(data))
    elif args.action == "test":
        provider = args.provider or "115"
        data = c.json("POST", "/test_provider_cookie", {"provider": provider})
        print(fmt_json(data))


def cmd_sign(args, c: Client):
    """115 每日签到"""
    if args.action == "run":
        data = c.json("POST", "/settings/115/sign/run")
        print(f"✅ 签到结果: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "status":
        data = c.json("GET", "/settings/115/sign/status")
        print(fmt_json(data))


def cmd_tmdb(args, c: Client):
    """TMDB 搜索"""
    if args.action == "search":
        keyword = " ".join(args.keyword) if args.keyword else ""
        if not keyword:
            sys.exit("请指定搜索关键词")
        data = c.json("GET", "/tmdb/search", {"q": keyword, "page": args.page or 1})
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        print(fmt_tmdb_items(items))

    elif args.action == "popular":
        data = c.json("GET", "/tmdb/popular", {"page": args.page or 1})
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        print(fmt_tmdb_items(items))

    elif args.action == "trending":
        data = c.json("GET", "/tmdb/trending", {"page": args.page or 1})
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        print(fmt_tmdb_items(items))

    elif args.action == "detail":
        if not args.tmdb_id:
            sys.exit("请指定 TMDB ID")
        data = c.json("GET", "/tmdb/detail", {"tmdb_id": int(args.tmdb_id[0])})
        print(fmt_json(data))

    elif args.action == "genres":
        data = c.json("GET", "/tmdb/genres")
        print(fmt_json(data))

    elif args.action == "discover":
        data = c.json("GET", "/tmdb/discover", {"page": args.page or 1})
        items = data if isinstance(data, list) else data.get("results", data.get("items", []))
        print(fmt_tmdb_items(items))


def cmd_monitor(args, c: Client):
    """文件夹监控管理"""
    if args.action == "list":
        cfg = c.json("GET", "/get_settings")
        tasks = cfg.get("monitor_tasks", [])
        if not tasks:
            print("未配置文件夹监控任务")
            return
        print(f"共 {len(tasks)} 个监控任务：")
        for t in tasks:
            name = str(t.get("name", "") or "").strip()
            path = str(t.get("scan_path", "") or "").strip()
            cron = t.get("cron_minutes", 0)
            enabled = "🟢" if t.get("enabled", True) else "🔴"
            print(f"  {enabled} {name}  (扫描: {path}, 周期: {cron}分钟)")

    elif args.action == "status":
        data = c.json("GET", "/monitor/status")
        running = data.get("running", False)
        current = data.get("current_task", "") or ""
        queued = data.get("queued", [])
        print(f"  运行中: {'🟢 是' if running else '⏸ 否'}")
        if current:
            print(f"  当前任务: {current}")
        if queued:
            print(f"  排队中: {', '.join(queued)}")

    elif args.action == "add":
        cfg = c.json("GET", "/get_settings")
        tasks: list = cfg.get("monitor_tasks", [])
        name = args.name.strip() if args.name else ""
        if not name:
            sys.exit("请指定监控任务名称")
        for t in tasks:
            if str(t.get("name", "") or "").strip() == name:
                sys.exit(f"监控任务「{name}」已存在")
        new_task = {
            "name": name,
            "scan_path": args.scan_path.rstrip("/") if args.scan_path else "/",
            "cron_minutes": args.cron_minutes or 0,
            "webhook_enabled": args.webhook,
            "delay_seconds": args.delay or 0,
            "enabled": not args.pause,
        }
        tasks.append(new_task)
        cfg["monitor_tasks"] = tasks
        c.json("POST", "/save_settings", cfg)
        print(f"✅ 已创建监控任务「{name}」")

    elif args.action == "remove":
        cfg = c.json("GET", "/get_settings")
        tasks: list = cfg.get("monitor_tasks", [])
        name = args.name.strip() if args.name else ""
        if not name:
            sys.exit("请指定要删除的监控任务名称")
        before = len(tasks)
        cfg["monitor_tasks"] = [t for t in tasks if str(t.get("name", "") or "").strip() != name]
        removed = before - len(cfg["monitor_tasks"])
        if removed == 0:
            sys.exit(f"未找到监控任务「{name}」")
        c.json("POST", "/save_settings", cfg)
        print(f"✅ 已删除监控任务「{name}」")

    elif args.action == "start":
        data = c.json("POST", "/monitor/start")
        print(f"✅ 监控已启动: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "stop":
        data = c.json("POST", "/monitor/stop")
        print(f"✅ 监控已停止: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "logs":
        data = c.json("GET", "/monitor/logs/tasks")
        print(fmt_json(data))

    elif args.action == "logs-clear":
        data = c.json("POST", "/monitor/logs/clear")
        print(f"✅ 监控日志已清除: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "userscript-jobs":
        data = c.json("GET", "/monitor/userscript/jobs")
        jobs = data if isinstance(data, list) else data.get("jobs", data.get("items", []))
        if not jobs:
            print("无油猴脚本任务")
            return
        print(f"油猴脚本任务 ({len(jobs)}):")
        for j in jobs:
            name = str(j.get("name", "") or j.get("task_name", "") or "").strip()
            status = j.get("status", "?")
            print(f"  • {name}  [{status}]")


def cmd_tree(args, c: Client):
    """目录树同步"""
    if args.action == "run":
        data = c.json("POST", "/start")
        print(f"✅ 目录树同步已触发: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "status":
        data = c.json("GET", "/status-summary")
        main = data.get("main", {})
        running = main.get("running", False)
        progress = main.get("progress", {})
        print(f"  运行中: {'🟢 是' if running else '⏸ 否'}")
        if progress:
            step = progress.get("step", "") or ""
            detail = progress.get("detail", "") or ""
            pct = progress.get("percent", 0) or 0
            print(f"  步骤: {step}  ({pct}%)")
            if detail:
                print(f"  详情: {detail}")
    elif args.action == "logs":
        data = c.json("GET", "/logs")
        if isinstance(data, list):
            for line in data:
                text = str(line.get("text", line)) if isinstance(line, dict) else str(line)
                print(text)
        elif isinstance(data, dict):
            lines = data.get("logs", data.get("lines", data.get("messages", [])))
            for line in lines:
                text = str(line.get("text", line)) if isinstance(line, dict) else str(line)
                print(text)
    elif args.action == "logs-clear":
        data = c.json("POST", "/logs/clear")
        print(f"✅ 目录树日志已清除: {json.dumps(data, ensure_ascii=False)}")


def cmd_sources(args, c: Client):
    """管理发现源 (DiscoveryProvider)"""
    if args.action == "save":
        channel_id = args.channel or ""
        title = args.title or ""
        if not channel_id:
            sys.exit("请指定频道 ID（--channel）")
        if not title:
            sys.exit("请指定频道名称（--title）")
        data = c.json("POST", "/resource/sources/save", {"sources": [{"channel_id": channel_id, "name": title}]})
        print(f"✅ 来源已保存: {json.dumps(data, ensure_ascii=False)}")
        return

    container = os.environ.get("MH_CONTAINER", "115-media-hub")

    if args.action == "list":
        code = """
from app.providers.discovery_registry import list_discovery_providers
providers = list_discovery_providers()
if not providers:
    print("未注册任何发现源")
else:
    print(f"共 {len(providers)} 个发现源：")
    print()
    for p in providers:
        ok = "✅" if p.validate() else "❌"
        print(f"  {ok} {p.label} ({p.name})")
"""
        r = subprocess.run(
            ["docker", "exec", "-i", container, "python3", "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            print(r.stdout.strip())
        else:
            print(r.stderr.strip() or f"执行失败 (exit {r.returncode})")

    elif args.action == "search":
        keyword = " ".join(args.keyword) if args.keyword else ""
        if not keyword:
            sys.exit("请指定搜索关键词")
        import shlex
        safe_kw = shlex.quote(keyword)
        code = f"""
from app.providers.discovery_registry import search_all
result = search_all({safe_kw}, limit=10)
items = result.get("results", [])
errors = result.get("errors", [])
stats = result.get("stats", {{}})
import json
all_items = [dict(title=i.title, link_url=i.link_url, link_type=i.link_type, quality=i.quality, source_name=i.source_name) for i in items]
print(json.dumps(dict(items=all_items, stats=stats, errors=errors), ensure_ascii=False))
"""
        r = subprocess.run(
            ["docker", "exec", "-i", container, "python3", "-c", code],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            print(r.stderr.strip() or f"执行失败 (exit {r.returncode})")
            return

        try:
            data = json.loads(r.stdout.strip())
        except json.JSONDecodeError:
            print(r.stdout.strip()[:1000])
            return

        items = data.get("items", [])
        if not items:
            print(f"未找到与「{keyword}」相关的资源")
            return

        print(f"找到 {len(items)} 个资源：")
        print()
        for item in items:
            print(f"  • {item.get('title', '')}")
            info = []
            if item.get("quality"):
                info.append(f"质量: {item['quality']}")
            if item.get("source_name"):
                info.append(f"来源: {item['source_name']}")
            if item.get("link_type"):
                info.append(f"类型: {item['link_type']}")
            if item.get("link_url"):
                info.append(f"链接: {item['link_url'][:80]}")
            if info:
                print(f"    {'  |  '.join(info)}")
            print()
        print(f"  来源统计: {data.get('stats', {}).get('by_provider', {})}")

    elif args.action == "test":
        name = args.name or ""
        if not name:
            sys.exit("请指定 Provider 名称（使用 --name 参数）")
        code = (
            "from app.providers.discovery_registry import get_discovery_provider\n"
            f"p = get_discovery_provider({name!r})\n"
            "if not p:\n"
            '    print(f"NOT_FOUND: {name}")\n'
            "else:\n"
            "    ok = p.validate()\n"
            '    print("OK" if ok else "FAIL")\n'
            "    print(p.label)\n"
        )
        r = subprocess.run(
            ["docker", "exec", "-i", container, "python3", "-c", code],
            capture_output=True, text=True, timeout=30,
        )
        lines = r.stdout.strip().split("\n")
        if r.returncode != 0 or "NOT_FOUND" in (lines[0] if lines else ""):
            print(f"❌ 未找到 Provider: {name}")
        elif lines[0] == "OK":
            print(f"✅ {lines[1] if len(lines) > 1 else name}: 配置有效")
        else:
            print(f"❌ {lines[1] if len(lines) > 1 else name}: 配置无效")


def cmd_api(args, c: Client):
    """通用 API 调用"""
    method = args.method.upper()
    path = args.path
    body = None
    if args.body:
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError:
            body = args.body
    resp = c.request(method, path, body)
    print(f"HTTP {resp.status_code}")
    print()
    try:
        print(fmt_json(resp.json()))
    except Exception:
        print(resp.text[:2000])


def cmd_providers(args, c: Client):
    """列出提供商"""
    data = c.json("GET", "/api/providers")
    print(fmt_providers(data))


# ── Phase 3: browse ───────────────────────────────────────────────────────

def cmd_browse(args, c: Client):
    """网盘浏览"""
    provider = args.provider or "115"
    cid = args.cid or "0"
    if args.action == "ls":
        data = c.json("GET", "/resource/browse", {"provider_name": provider, "cid": cid})
        entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))
        if not entries:
            print("(空目录)")
            return
        print(f"📁 {provider} 目录 (cid={cid})")
        print()
        for e in entries:
            name = str(e.get("name", "") or "").strip()
            is_dir = bool(e.get("is_dir", e.get("is_directory", e.get("type", "") == "folder")))
            icon = "📁" if is_dir else "📄"
            file_id = e.get("file_id", e.get("id", e.get("cid", "")))
            size = str(e.get("size", "") or "").strip()
            print(f"  {icon} {name}  (id={file_id})" + (f"  {size}" if size else ""))

    elif args.action == "tree":
        data = c.json("GET", "/resource/browse", {"provider_name": provider, "cid": cid, "folders_only": "1"})
        entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))
        if not entries:
            print("(空目录)")
            return
        _print_tree(entries, provider, c, prefix="")

    elif args.action == "folders":
        data = c.json("GET", f"/resource/browse/{provider}/folders", {"cid": cid})
        folders = data if isinstance(data, list) else data.get("folders", data.get("items", []))
        if not folders:
            print("(空目录)")
            return
        print(f"📁 {provider} 子目录 (cid={cid})")
        for f in folders:
            name = str(f.get("name", "") or "").strip()
            fid = f.get("file_id", f.get("id", f.get("cid", "")))
            print(f"  📁 {name}  (id={fid})")

    elif args.action == "create-folder":
        name = args.name or ""
        if not name:
            sys.exit("请指定目录名称（--name）")
        data = c.json("POST", f"/resource/browse/{provider}/folders/create", {"cid": cid, "name": name})
        print(f"✅ 已创建目录「{name}」: {json.dumps(data, ensure_ascii=False)}")


def _print_tree(entries: list, provider: str, c: Client, prefix: str = "", depth: int = 0):
    if depth > 3:
        print(f"{prefix}  ...")
        return
    for i, e in enumerate(entries):
        name = str(e.get("name", "") or "").strip()
        file_id = e.get("file_id", e.get("id", e.get("cid", "")))
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}{name}  (id={file_id})")
        if depth < 3:
            sub = c.json("GET", "/resource/browse", {"provider_name": provider, "cid": file_id, "folders_only": "1"})
            sub_items = sub if isinstance(sub, list) else sub.get("entries", sub.get("items", []))
            if sub_items:
                sub_prefix = prefix + ("    " if is_last else "│   ")
                _print_tree(sub_items, provider, c, sub_prefix, depth + 1)


# ── Phase 3: share ────────────────────────────────────────────────────────

def cmd_share(args, c: Client):
    """分享管理"""
    if args.action == "preview":
        url = args.url or ""
        if not url:
            sys.exit("请指定分享链接")
        provider = args.provider or "115"
        code = args.code or ""
        cid = args.cid or ""
        params = {"link_url": url, "receive_code": code, "cid": cid}
        try:
            data = c.json("GET", f"/resource/browse/{provider}/share_entries", params)
        except SystemExit:
            # Try direct share endpoint
            data = c.json("GET", f"/resource/{provider}/share_entries", params)
        entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))
        summary = data.get("summary", {}) if isinstance(data, dict) else {}
        print(f"📦 分享内容 ({url[:60]})")
        if summary:
            print(f"   文件夹: {summary.get('folder_count', 0)}  文件: {summary.get('file_count', 0)}")
        print()
        for e in entries[:30]:
            name = str(e.get("name", "") or "").strip()
            is_dir = bool(e.get("is_dir", e.get("is_directory", e.get("type", "") == "folder")))
            icon = "📁" if is_dir else "📄"
            file_id = e.get("file_id", e.get("id", ""))
            size = str(e.get("size", "") or "").strip()
            print(f"  {icon} {name}  (id={file_id})" + (f"  {size}" if size else ""))

    elif args.action == "receive":
        resource_id = args.resource_id or ""
        if not resource_id:
            sys.exit("请指定资源 ID（先 search 获取）")
        savepath = args.savepath or "/115"
        if args.auto_path:
            title = args.title or ""
            if not title:
                sys.exit("--auto-path 需要 --title 参数指定资源标题")
            # 1. 清洗标题
            import re as _re
            clean = _re.sub(
                r"\b(4K|1080P|720P|2160P|WEB-DL|WEBRIP|BLURAY|BDRIP|HDRip|HDTV|DVD|H264|H265|x264|x265|HEVC|AAC|DTS|AC3|TRUEHD|ATMOS|HDR|DOLBY|VISION|REMUX|COMPLETE|CHINESE|ENGLISH|国语|粤语|英语|日语|内封|内嵌|外挂|简繁|字幕|S\d{2}E\d{2}|EP\d{2}|第.+[季集])\b",
                "", title, flags=_re.IGNORECASE,
            )
            clean = _re.sub(r"[\[\]【】()（）\-]", " ", clean).strip()
            clean = _re.sub(r"\s+", " ", clean).strip()
            # 去掉末尾年份
            clean = _re.sub(r"\s+(19|20)\d{2}\s*$", "", clean).strip()
            # 2. TMDB 查 media_type
            try:
                resp = c.request("GET", "/tmdb/search", {"q": clean})
                if resp.status_code == 200:
                    tmdb_data = resp.json()
                    items = tmdb_data if isinstance(tmdb_data, list) else tmdb_data.get("results", tmdb_data.get("items", []))
                    if items:
                        mt = str(items[0].get("media_type", "") or "").strip()
                        tmdb_title = str(items[0].get("title", "") or items[0].get("name", "") or clean).strip()
                        tmdb_year = str(items[0].get("year", "") or "").strip()
                        if mt == "movie":
                            savepath = f"/电影/{tmdb_title}"
                            if tmdb_year:
                                savepath += f" ({tmdb_year})"
                        elif mt == "tv":
                            savepath = f"/剧集/{tmdb_title}"
                        else:
                            savepath = f"/电影/{tmdb_title}"
                        print(f"📺 TMDB 识别: {mt} → {savepath}")
                    else:
                        savepath = f"/电影/{clean}"
                        print(f"⚠️ TMDB 未识别, 默认电影: {savepath}")
                else:
                    savepath = f"/电影/{clean}"
                    print(f"⚠️ TMDB 未启用, 默认电影: {savepath}")
            except Exception as e:
                savepath = f"/电影/{clean}"
                print(f"⚠️ TMDB 查询失败, 默认电影: {savepath}")
            print(f"📦 保存路径: {savepath}")
        data = c.json("POST", "/resource/jobs/create", {"resource_id": int(resource_id), "savepath": savepath})
        print(f"✅ 转存任务已创建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "preview-batch":
        url = args.url or ""
        if not url:
            sys.exit("请指定分享链接")
        provider = args.provider or "115"
        data = c.json("POST", f"/resource/browse/{provider}/share_entries_preview", {"link_url": url})
        print(fmt_json(data))


# ── Phase 3: scrape ────────────────────────────────────────────────────────

def cmd_scrape(args, c: Client):
    """刮削管理"""
    if args.action == "identify":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        data = c.json("POST", "/scraper/identify", {"path": path})
        print(fmt_json(data))

    elif args.action == "rename-plan":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        data = c.json("POST", "/scraper/rename-plan", {"path": path})
        print(fmt_json(data))

    elif args.action == "diff":
        job_id = args.job_id[0] if args.job_id else ""
        if not job_id:
            sys.exit("请指定 Job ID")
        data = c.json("GET", "/scraper/jobs/state", {"limit": 50})
        jobs = data if isinstance(data, list) else data.get("jobs", data.get("items", []))
        for j in jobs:
            if str(j.get("id", j.get("job_id", "")) or "") == job_id:
                actions = j.get("actions", [])
                if not actions:
                    print("该任务无操作记录")
                    return
                print(f"刮削 Job #{job_id} 操作列表：")
                print()
                for a in actions:
                    old_n = a.get("old_name", a.get("old_path", ""))
                    new_n = a.get("new_name", a.get("new_path", ""))
                    icon = "✅" if a.get("status") == "completed" else "⏳"
                    print(f"  {icon} {old_n}")
                    print(f"       → {new_n}")
                    print()
                return
        print(f"未找到 Job #{job_id}")

    elif args.action == "jobs":
        provider = args.provider or ""
        params = {"limit": args.limit or 20}
        if provider:
            params["provider"] = provider
        data = c.json("GET", "/scraper/jobs/state", params)
        print(fmt_json(data))

    elif args.action == "providers":
        data = c.json("GET", "/scraper/providers")
        print(fmt_json(data))

    elif args.action == "entries":
        provider = args.provider or "115"
        data = c.json("GET", f"/scraper/{provider}/entries")
        entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))
        if not entries:
            print("(无条目)")
            return
        print(f"{provider} 刮削条目 ({len(entries)}):")
        for e in entries[:30]:
            name = str(e.get("name", "") or e.get("path", "") or "").strip()
            media_type = e.get("media_type", e.get("type", "?"))
            print(f"  • {name}  [{media_type}]")

    elif args.action == "folders":
        provider = args.provider or "115"
        cid = args.cid or "0"
        data = c.json("POST", f"/scraper/{provider}/folders", {"cid": cid})
        folders = data if isinstance(data, list) else data.get("folders", data.get("items", []))
        if not folders:
            print("(空目录)")
            return
        print(f"📁 {provider} 刮削目录 (cid={cid})")
        for f in folders:
            name = str(f.get("name", "") or "").strip()
            fid = f.get("file_id", f.get("id", f.get("cid", "")))
            print(f"  📁 {name}  (id={fid})")

    elif args.action == "rename-warning":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        provider = args.provider or "115"
        data = c.json("POST", f"/scraper/{provider}/rename-warning", {"path": path})
        print(fmt_json(data))

    elif args.action == "rename":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        name = args.name or ""
        if not name:
            sys.exit("请指定新名称（--name）")
        provider = args.provider or "115"
        data = c.json("POST", f"/scraper/{provider}/rename", {"path": path, "name": name})
        print(f"✅ 已重命名: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "jobs-create":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        data = c.json("POST", "/scraper/jobs/create", {"path": path})
        print(f"✅ 刮削任务已创建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "move":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        dest = args.dest or ""
        if not dest:
            sys.exit("请指定目标路径（--dest）")
        provider = args.provider or "115"
        data = c.json("POST", f"/scraper/{provider}/move", {"path": path, "dest": dest})
        print(f"✅ 移动完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "copy":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        dest = args.dest or ""
        if not dest:
            sys.exit("请指定目标路径（--dest）")
        provider = args.provider or "115"
        data = c.json("POST", f"/scraper/{provider}/copy", {"path": path, "dest": dest})
        print(f"✅ 复制完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "delete":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        provider = args.provider or "115"
        confirm = args.yes or input(f"确定要删除 {path}？(y/N): ").lower() == "y"
        if not confirm:
            print("已取消")
            return
        data = c.json("POST", f"/scraper/{provider}/delete", {"path": path})
        print(f"✅ 删除完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "rollback":
        job_id = args.job_id[0] if args.job_id else ""
        if not job_id:
            sys.exit("请指定 Job ID")
        data = c.json("POST", f"/scraper/jobs/{job_id}/rollback")
        print(f"✅ 回滚完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "jobs-clear":
        data = c.json("POST", "/scraper/jobs/clear")
        print(f"✅ 刮削任务已清理: {json.dumps(data, ensure_ascii=False)}")


# ── Phase 3: watchlist ────────────────────────────────────────────────────

def cmd_watchlist(args, c: Client):
    """推荐清单"""
    if args.action == "list":
        data = c.json("GET", "/recommendation/state")
        items = data if isinstance(data, list) else data.get("items", data.get("watchlist", []))
        if not items:
            print("推荐清单为空")
            return
        print(f"共 {len(items)} 部推荐：")
        print()
        for item in items:
            title = str(item.get("title", "") or item.get("name", "") or "").strip()
            tmdb_id = item.get("tmdb_id", item.get("id", "?"))
            status = item.get("status", "pending")
            status_icon = {"watching": "📺", "completed": "✅", "pending": "⏳", "dropped": "⏹️"}.get(status, "⏳")
            print(f"  {status_icon} {title}  (TMDB:{tmdb_id})  [{status}]")

    elif args.action == "add":
        tmdb_id = args.tmdb_id[0] if args.tmdb_id else ""
        if not tmdb_id:
            sys.exit("请指定 TMDB ID")
        data = c.json("POST", "/recommendation/watchlist/add", {"tmdb_id": int(tmdb_id)})
        print(f"✅ 已添加到推荐清单: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "remove":
        tmdb_id = args.tmdb_id[0] if args.tmdb_id else ""
        if not tmdb_id:
            sys.exit("请指定 TMDB ID")
        data = c.json("POST", "/recommendation/watchlist/remove", {"tmdb_id": int(tmdb_id)})
        print(f"✅ 已从推荐清单移除: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "update":
        tmdb_id = args.tmdb_id[0] if args.tmdb_id else ""
        if not tmdb_id:
            sys.exit("请指定 TMDB ID")
        status = args.status or "completed"
        data = c.json("POST", "/recommendation/watchlist/update_status",
                       {"tmdb_id": int(tmdb_id), "status": status})
        print(f"✅ 状态已更新: {json.dumps(data, ensure_ascii=False)}")


# ── Phase 3: strm ─────────────────────────────────────────────────────────

def cmd_strm(args, c: Client):
    """STRM 管理"""
    if args.action == "orphans":
        data = c.json("GET", "/strm/orphan-metadata/preview")
        items = data if isinstance(data, list) else data.get("orphans", data.get("items", []))
        dirs = data.get("local_dirs", data.get("dirs", [])) if isinstance(data, dict) else []
        if not items and not dirs:
            print("未发现孤儿 STRM 文件")
            return
        print(f"孤儿 STRM 文件: {len(items)} 个")
        for item in items[:20]:
            path = str(item.get("path", "") or item.get("file", "") or item.get("name", "") or "").strip()
            print(f"  ❌ {path}")
        if len(items) > 20:
            print(f"  ... 还有 {len(items)-20} 个")
        if dirs:
            print()
            print(f"本地目录: {len(dirs)} 个")
            for d in dirs[:10]:
                print(f"  📁 {d}")
            if len(dirs) > 10:
                print(f"  ... 还有 {len(dirs)-10} 个")

    elif args.action == "cleanup":
        data = c.json("POST", "/strm/orphan-metadata/delete")
        deleted = data.get("deleted", data.get("count", data.get("ok", "?")))
        print(f"✅ 已清理孤儿 STRM: {deleted} 项")

    elif args.action == "dirs":
        data = c.json("GET", "/strm/orphan-metadata/local-dirs")
        dirs = data if isinstance(data, list) else data.get("dirs", data.get("local_dirs", []))
        if not dirs:
            print("无本地目录记录")
            return
        print(f"STRM 本地目录: {len(dirs)} 个")
        for d in dirs:
            print(f"  📁 {str(d).strip()}")


# ── Phase 5: resource ─────────────────────────────────────────────────────

def cmd_resource(args, c: Client):
    """资源中心管理"""
    if args.action == "import":
        text = args.text or ""
        if not text and not sys.stdin.isatty():
            text = sys.stdin.read().strip()
        if not text:
            sys.exit("请指定资源文本（--text 参数或通过管道传入）")
        provider = args.provider or "115"
        data = c.json("POST", "/resource/items/import_text", {"text": text, "provider": provider})
        imported = data.get("imported", data.get("count", 0))
        total = data.get("total", data.get("items", 0))
        print(f"✅ 已导入 {imported}/{total} 个资源")
        if data.get("errors"):
            for err in data["errors"][:5]:
                print(f"  ⚠️ {err}")

    elif args.action == "preview":
        text = args.text or ""
        if not text and not sys.stdin.isatty():
            text = sys.stdin.read().strip()
        if not text:
            sys.exit("请指定资源文本（--text 参数或通过管道传入）")
        data = c.json("POST", "/resource/items/preview_text", {"text": text})
        items = data if isinstance(data, list) else data.get("items", data.get("results", []))
        if not items:
            print("未识别到有效资源")
            return
        print(f"识别到 {len(items)} 个资源：")
        print()
        for item in items[:20]:
            title = str(item.get("title", "") or "").strip() or "(无标题)"
            link = str(item.get("link_url", "") or "").strip()
            link_type = str(item.get("link_type", "") or "").strip()
            print(f"  • {title}  [{link_type}]")
            if link:
                print(f"    链接: {link[:80]}")
            print()

    elif args.action == "quick-links":
        if args.sub_action == "list":
            cfg = c.json("GET", "/get_settings")
            links = cfg.get("quick_links", [])
            if not links:
                print("未配置快捷链接")
                return
            print(f"共 {len(links)} 个快捷链接：")
            for link in links:
                name = str(link.get("name", "") or "").strip()
                url = str(link.get("url", "") or "").strip()
                print(f"  • {name}  → {url}")
        elif args.sub_action == "add":
            name = args.name or ""
            url = args.url or ""
            if not name or not url:
                sys.exit("请指定 --name 和 --url")
            cfg = c.json("GET", "/get_settings")
            quick_links: list = cfg.get("quick_links", [])
            quick_links.append({"name": name, "url": url})
            cfg["quick_links"] = quick_links
            c.json("POST", "/save_settings", cfg)
            print(f"✅ 已添加快捷链接「{name}」")
        elif args.sub_action == "remove":
            name = args.name or ""
            if not name:
                sys.exit("请指定快捷链接名称")
            cfg = c.json("GET", "/get_settings")
            before = len(cfg.get("quick_links", []))
            cfg["quick_links"] = [l for l in cfg.get("quick_links", []) if str(l.get("name", "") or "").strip() != name]
            removed = before - len(cfg["quick_links"])
            if removed == 0:
                sys.exit(f"未找到快捷链接「{name}」")
            c.json("POST", "/save_settings", cfg)
            print(f"✅ 已删除快捷链接「{name}」")

    elif args.action == "delete":
        resource_id = args.resource_id[0] if args.resource_id else ""
        if not resource_id:
            sys.exit("请指定资源 ID")
        confirm = args.yes or input(f"确定要删除资源 #{resource_id}？(y/N): ").lower() == "y"
        if not confirm:
            print("已取消")
            return
        data = c.json("POST", "/resource/items/delete", {"id": int(resource_id)})
        print(f"✅ 已删除: {json.dumps(data, ensure_ascii=False)}")


# ── Phase 6: Ops ──────────────────────────────────────────────────────────

def cmd_health(args, c: Client):
    """全链路健康检查"""
    print("🏥 115 Media Hub 健康检查")
    print()

    # 1. Version
    try:
        ver = c.json("GET", "/version")
        v = ver.get("version", ver.get("app_version", "?"))
        print(f"  版本: {v}")
    except Exception as e:
        print(f"  ❌ 版本: 获取失败 ({e})")

    # 2. Status summary
    try:
        status = c.json("GET", "/status-summary")
        main = status.get("main", {})
        mon = status.get("monitor", {})
        sub = status.get("subscription", {})
        print(f"  目录树任务: {'🟢 运行中' if main.get('running') else '⏸ 空闲'}")
        print(f"  文件夹监控: {'🟢 运行中' if mon.get('running') else '⏸ 空闲'}")
        print(f"  订阅引擎:   {'🟢 运行中' if sub.get('running') else '⏸ 空闲'}")
    except Exception as e:
        print(f"  ❌ 状态: 获取失败 ({e})")

    # 3. Cookie health
    try:
        health = c.json("POST", "/settings/cookies/check", {})
        ch = health.get("cookie_health", health)
        for provider, info in ch.items() if isinstance(ch, dict) else []:
            state = info.get("state", "unknown")
            msg = info.get("message", "")
            icon = "✅" if state == "valid" else ("⚠️" if state == "missing" else "❌")
            print(f"  {icon} {provider}: {msg}")
    except Exception as e:
        print(f"  ❌ Cookie: 检测失败 ({e})")

    # 4. TG connectivity
    try:
        tg = c.json("POST", "/settings/tg_proxy/test", {})
        ok = tg.get("ok", False)
        latency = tg.get("latency_ms", 0)
        mode = tg.get("mode", "?")
        print(f"  {'🟢' if ok else '❌'} TG 连通: {mode} 模式, {latency}ms")
    except Exception as e:
        print(f"  ❌ TG: 连接失败 ({e})")

    # 5. Resource stats
    try:
        state = c.json("GET", "/resource/state", {"compact": "1"})
        stats = state.get("stats", {})
        setup = state.get("setup_status", {})
        print(f"  📦 资源数: {stats.get('item_count', 0)}  |  频道: {stats.get('source_count', 0)}  |  任务: {stats.get('total_job_count', 0)}")
        print(f"  🔧 配置状态: Cookie={'✅' if setup.get('cookie_configured') else '❌'}  资源={'✅' if setup.get('has_sources') else '❌'}  STRM={'✅' if setup.get('strm_ready') else '❌'}")
    except Exception as e:
        print(f"  ❌ 资源: 获取失败 ({e})")

    # 6. Docker
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=115-media-hub", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=5,
        )
        dkr = r.stdout.strip()
        print(f"  🐳 容器: {'🟢 ' + dkr if dkr else '❌ 未运行'}")
    except Exception as e:
        print(f"  ❌ Docker: {e}")


def cmd_stats(args, c: Client):
    """统计摘要"""
    try:
        state = c.json("GET", "/resource/state", {"compact": "1"})
    except Exception as e:
        sys.exit(f"获取状态失败: {e}")

    stats = state.get("stats", {})
    setup = state.get("setup_status", {})
    job_counts = state.get("job_counts", {})
    sections = state.get("channel_sections", [])

    # 计算各频道资源数
    total_items = 0
    channel_items = {}
    for sec in sections:
        count = sec.get("item_count", 0) or 0
        total_items += count
        if count > 0:
            channel_items[sec.get("name", sec.get("channel_id", "?"))] = count

    print("📊 统计摘要")
    print()
    print(f"  资源频道: {stats.get('source_count', 0)} 个")
    print(f"  资源条目: {stats.get('item_count', 0)} 条 (频道内 {total_items} 条)")
    print(f"  活跃频道: {len(channel_items)} 个")
    print()
    print("  任务统计:")
    print(f"    总计: {job_counts.get('total', 0)}")
    print(f"    运行中: {job_counts.get('running', 0)}")
    print(f"    已完成: {job_counts.get('completed', 0)}")
    print(f"    失败: {job_counts.get('failed', 0)}")
    print()

    # 按频道来源分类
    link_types: dict = {}
    for sec in sections:
        ltc = sec.get("link_type_counts", {})
        for lt, cnt in ltc.items():
            link_types[lt] = link_types.get(lt, 0) + cnt
    if link_types:
        print("  资源类型分布:")
        for lt, cnt in sorted(link_types.items(), key=lambda x: -x[1]):
            print(f"    {lt}: {cnt} 条")

    if channel_items:
        top = sorted(channel_items.items(), key=lambda x: -x[1])[:10]
        print()
        print("  资源最多的频道 (Top 10):")
        for name, cnt in top:
            print(f"    {name}: {cnt} 条")


def cmd_daemon(args, c: Client):
    """容器管理"""
    container = os.environ.get("MH_CONTAINER", "115-media-hub")

    if args.action == "status":
        r = subprocess.run(
            ["docker", "ps", "-a", "--filter", f"name={container}",
             "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=5,
        )
        out = r.stdout.strip()
        if out:
            print(out)
        else:
            print(f"容器 {container} 未找到")

    elif args.action == "logs":
        tail = args.tail or 50
        r = subprocess.run(
            ["docker", "logs", container, "--tail", str(tail)],
            capture_output=True, text=True, timeout=5,
        )
        if r.stdout:
            print(r.stdout.strip())
        if r.stderr:
            print(r.stderr.strip()[:1000])

    elif args.action == "restart":
        print(f"🔄 重启容器 {container}...")
        r = subprocess.run(["docker", "restart", container], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            print("✅ 容器已重启")
        else:
            print(f"❌ 重启失败: {r.stderr.strip()}")
        # 等待服务就绪
        import time
        for i in range(15):
            time.sleep(2)
            try:
                c = Client()
                c.json("GET", "/status-summary")
                print(f"✅ 服务已就绪 (等待 {2*(i+1)}s)")
                return
            except Exception:
                continue
        print("⚠️ 容器已重启但服务未响应")


# ── Main CLI ──────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="115",
        description="115 Media Hub CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sp = p.add_subparsers(dest="command")

    # status
    sp.add_parser("status", help="系统状态")

    # version
    sp.add_parser("version", help="版本信息")

    # search
    sp_search = sp.add_parser("search", help="搜索资源")
    sp_search.add_argument("keyword", nargs="*", help="搜索关键词 (留空=cancel 时忽略)")
    sp_search.add_argument("action", nargs="?", default="", choices=["", "cancel"], help="cancel=取消搜索")

    # channels
    sp_ch = sp.add_parser("channels", help="管理资源频道")
    sp_ch.add_argument("action", choices=["sync", "list", "classify", "more", "sync-names", "sync-cancel"], help="sync=同步, list=列出, classify=分类, more=更多内容, sync-names=同步名称, sync-cancel=取消同步")
    sp_ch.add_argument("--force", action="store_true", help="强制重新同步")
    sp_ch.add_argument("--channel", dest="channel_id", default="", help="频道 ID (more/classify/sync-names)")
    sp_ch.add_argument("--limit", type=int, default=10, help="条数 (more)")

    # subscribe
    sp_sub = sp.add_parser("subscribe", help="管理订阅")
    sp_sub.add_argument("action", choices=["list", "add", "remove", "start", "stop", "status", "logs", "logs-clear", "rebuild", "episodes", "start-with-link"])
    sp_sub.add_argument("name", nargs="*", help="订阅名称 (add/remove/start)")
    sp_sub.add_argument("--type", default="movie", choices=["movie", "tv"], help="媒体类型")
    sp_sub.add_argument("--quality", default="balanced", help="质量偏好 (4K/1080p/720p/balanced)")
    sp_sub.add_argument("--savepath", default="/电影", help="115 保存路径")
    sp_sub.add_argument("--provider", default="115", choices=["115", "quark"], help="网盘提供商")
    sp_sub.add_argument("--link", default="", help="资源链接 (start-with-link)")
    sp_sub.add_argument("--name", default="", help="订阅名称 (rebuild/episodes)")

    # jobs
    sp_jobs = sp.add_parser("jobs", help="管理资源任务")
    sp_jobs.add_argument("action", choices=["list", "clear", "clear_completed", "clear-completed", "retry", "create", "refresh", "cancel"])
    sp_jobs.add_argument("job_id", nargs="*", help="任务 ID (retry/refresh/cancel)")
    sp_jobs.add_argument("--limit", type=int, default=20, help="列表条数")
    sp_jobs.add_argument("--status", default="", help="过滤状态 (pending/submitted/completed/failed)")
    sp_jobs.add_argument("resource_id", nargs="*", help="资源 ID (create)")
    sp_jobs.add_argument("--savepath", default="/115", help="保存路径 (create)")

    # settings
    sp_set = sp.add_parser("settings", help="查看/修改配置")
    sp_set.add_argument("kv", nargs="*", help='key=value (例如 cookie_115="xxx")')
    sp_set.add_argument("--test-proxy", action="store_true", help="测试 TG 代理连接")
    sp_set.add_argument("--test-pansou", action="store_true", help="测试 PanSou 盘搜")
    sp_set.add_argument("--test-notify", action="store_true", help="测试通知推送")

    # logs
    sp_logs = sp.add_parser("logs", help="查看系统日志")
    sp_logs.add_argument("action", nargs="?", default="", choices=["", "clear"], help="clear=清除日志, 留空=查看")
    sp_logs.add_argument("tail", nargs="?", type=int, default=0, help="只显示最后 N 条 (与 action 互斥)")

    # cookies
    sp_cookies = sp.add_parser("cookies", help="检查 Cookie 状态")
    sp_cookies.add_argument("action", choices=["check", "status", "test"], help="check=检测, status=查看缓存状态, test=测试指定提供商")
    sp_cookies.add_argument("--provider", default="115", help="网盘提供商 (test)")

    # sign
    sp_sign = sp.add_parser("sign", help="115 每日签到")
    sp_sign.add_argument("action", choices=["run", "status"])

    # tmdb
    sp_tmdb = sp.add_parser("tmdb", help="TMDB 搜索")
    sp_tmdb.add_argument("action", choices=["search", "popular", "trending", "detail", "genres", "discover"])
    sp_tmdb.add_argument("keyword", nargs="*", help="搜索关键词 (search)")
    sp_tmdb.add_argument("tmdb_id", nargs="*", help="TMDB ID (detail)")
    sp_tmdb.add_argument("--page", type=int, default=1, help="页码")

    # sources (DiscoveryProvider)
    sp_src = sp.add_parser("sources", help="管理发现源 (DiscoveryProvider)")
    sp_src.add_argument("action", choices=["list", "search", "test", "save"])
    sp_src.add_argument("keyword", nargs="*", help="搜索关键词 (search)")
    sp_src.add_argument("--name", help="Provider 名称 (test)")
    sp_src.add_argument("--channel", default="", help="频道 ID (save)")
    sp_src.add_argument("--title", default="", help="频道名称 (save)")

    # monitor
    sp_mon = sp.add_parser("monitor", help="文件夹监控管理")
    sp_mon.add_argument("action", choices=["list", "status", "start", "stop", "logs", "logs-clear", "userscript-jobs", "add", "remove"])
    sp_mon.add_argument("name", nargs="?", default="", help="监控任务名称 (add/remove)")
    sp_mon.add_argument("--scan-path", default="/", help="扫描路径 (add)")
    sp_mon.add_argument("--cron-minutes", type=int, default=0, help="定时周期分钟数, 0=仅手动 (add)")
    sp_mon.add_argument("--webhook", action="store_true", help="启用 Webhook 触发 (add)")
    sp_mon.add_argument("--delay", type=int, default=0, help="触发后延迟秒数 (add)")
    sp_mon.add_argument("--pause", action="store_true", help="创建后暂停 (add)")

    # tree
    sp_tree = sp.add_parser("tree", help="目录树同步")
    sp_tree.add_argument("action", choices=["run", "status", "logs", "logs-clear"])

    # api
    sp_api = sp.add_parser("api", help="通用 API 调用")
    sp_api.add_argument("method", help="HTTP 方法 (GET/POST)")
    sp_api.add_argument("path", help="API 路径 (如 /resource/state)")
    sp_api.add_argument("body", nargs="?", help='JSON 请求体 (如 \'{"key":"val"}\')')

    # providers
    sp.add_parser("providers", help="列出网盘提供商")

    # browse
    sp_browse = sp.add_parser("browse", help="网盘浏览")
    sp_browse.add_argument("action", choices=["ls", "tree", "folders", "create-folder"])
    sp_browse.add_argument("--provider", default="115", help="网盘提供商 (115/quark)")
    sp_browse.add_argument("--cid", default="0", help="目录 ID")
    sp_browse.add_argument("--name", default="", help="目录名称 (create-folder)")

    # share
    sp_share = sp.add_parser("share", help="分享管理")
    sp_share.add_argument("action", choices=["preview", "receive", "preview-batch"])
    sp_share.add_argument("url", nargs="?", help="分享链接 (preview/preview-batch)")
    sp_share.add_argument("--provider", default="115", help="网盘提供商")
    sp_share.add_argument("--code", default="", help="提取码")
    sp_share.add_argument("--cid", default="", help="目录 ID")
    sp_share.add_argument("--savepath", default="/115", help="保存路径")
    sp_share.add_argument("--id", dest="resource_id", default="", help="资源 ID (receive)")
    sp_share.add_argument("--auto-path", action="store_true", help="自动根据 TMDB 识别类型确定保存路径")
    sp_share.add_argument("--title", default="", help="资源标题 (--auto-path 需要)")

    # scrape
    sp_scrape = sp.add_parser("scrape", help="刮削管理")
    sp_scrape.add_argument("action", choices=["identify", "rename-plan", "diff", "jobs", "providers", "entries", "folders", "rename", "rename-warning", "jobs-create", "move", "copy", "delete", "rollback", "jobs-clear"])
    sp_scrape.add_argument("path", nargs="*", help="文件路径 (identify/rename-plan/move/copy/delete/rename/rename-warning/jobs-create)")
    sp_scrape.add_argument("job_id", nargs="*", help="Job ID (diff/rollback)")
    sp_scrape.add_argument("--provider", default="", help="提供商 (jobs/move/copy/delete/rename)")
    sp_scrape.add_argument("--limit", type=int, default=20, help="列表条数 (jobs)")
    sp_scrape.add_argument("--dest", default="", help="目标路径 (move/copy)")
    sp_scrape.add_argument("--name", default="", help="新名称 (rename)")
    sp_scrape.add_argument("--cid", default="0", help="目录 ID (folders)")
    sp_scrape.add_argument("--yes", action="store_true", help="跳过确认 (delete)")

    # watchlist
    sp_wl = sp.add_parser("watchlist", help="推荐清单")
    sp_wl.add_argument("action", choices=["list", "add", "remove", "update"])
    sp_wl.add_argument("tmdb_id", nargs="*", help="TMDB ID (add/remove/update)")
    sp_wl.add_argument("--status", default="completed",
                       choices=["watching", "completed", "pending", "dropped"],
                       help="状态 (update)")

    # strm
    sp_strm = sp.add_parser("strm", help="STRM 管理")
    sp_strm.add_argument("action", choices=["orphans", "cleanup", "dirs"])

    # resource
    sp_rsrc = sp.add_parser("resource", help="资源中心管理")
    sp_rsrc.add_argument("action", choices=["import", "preview", "quick-links", "delete"])
    sp_rsrc.add_argument("sub_action", nargs="?", default="list", help="quick-links 子操作 (list/add/remove)")
    sp_rsrc.add_argument("resource_id", nargs="*", help="资源 ID (delete)")
    sp_rsrc.add_argument("--text", default="", help="资源文本 (import/preview)")
    sp_rsrc.add_argument("--provider", default="115", help="网盘提供商 (import)")
    sp_rsrc.add_argument("--name", default="", help="名称 (quick-links add/remove)")
    sp_rsrc.add_argument("--url", default="", help="链接 URL (quick-links add)")
    sp_rsrc.add_argument("--yes", action="store_true", help="跳过确认 (delete)")

    # health
    sp.add_parser("health", help="全链路健康检查")

    # stats
    sp.add_parser("stats", help="统计摘要")

    # daemon
    sp_daemon = sp.add_parser("daemon", help="容器管理")
    sp_daemon.add_argument("action", choices=["status", "logs", "restart"])
    sp_daemon.add_argument("tail", nargs="?", type=int, default=0, help="日志行数 (logs)")

    return p


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    c = Client()

    dispatch = {
        "status": cmd_status,
        "version": cmd_version,
        "search": cmd_search,
        "channels": cmd_channels,
        "subscribe": cmd_subscribe,
        "jobs": cmd_jobs,
        "settings": cmd_settings,
        "logs": cmd_logs,
        "cookies": cmd_cookies,
        "sign": cmd_sign,
        "tmdb": cmd_tmdb,
        "sources": cmd_sources,
        "monitor": cmd_monitor,
        "tree": cmd_tree,
        "api": cmd_api,
        "providers": cmd_providers,
        "browse": cmd_browse,
        "share": cmd_share,
        "scrape": cmd_scrape,
        "watchlist": cmd_watchlist,
        "strm": cmd_strm,
        "resource": cmd_resource,
        "health": cmd_health,
        "stats": cmd_stats,
        "daemon": cmd_daemon,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args, c)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()