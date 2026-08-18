#!/usr/bin/env python3
"""
|115 — 115 Media Hub CLI 工具

|用法:
  115 status                            系统状态
  115 search <关键词>                    搜索资源
  115 search --cancel                   取消搜索
  115 channels sync|list|classify|more|sync-names|sync-cancel
                                       管理资源频道
  115 subscribe list|add|remove|start|stop|status|logs|logs-clear|rebuild|episodes|start-with-link
                                       管理订阅
  115 jobs list|clear|retry|create|refresh|cancel
                                       管理资源任务
  115 offline list [--page N]          查看 115 官方离线任务（只读诊断）
  115 settings [key=value...]           查看/修改配置
  115 logs [--tail N]                   查看系统日志
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
  115 scrape identify|rename-plan|rename|diff|jobs|providers|entries|folders|rename-warning|jobs-create|move|copy|delete|rollback|jobs-clear|batch-preferences
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
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import httpx

MH_USERNAME = os.environ.get("MH_USERNAME", "")
MH_PASSWORD = os.environ.get("MH_PASSWORD", "")

API_BASE = os.environ.get("MH_API_BASE", "http://127.0.0.1:18080")
COOKIE_FILE = os.environ.get("MH_COOKIE_FILE", "/tmp/.115_cookies.txt")


def _require_docker():
    if shutil.which("docker") is None:
        sys.exit("未检测到 docker 命令：sources/daemon 等命令需要宿主机安装 Docker")


def _require_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        sys.exit(f"{label} 无效：{value or '(空)'}")


def _require_float(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        sys.exit(f"{label} 无效：{value or '(空)'}")


def _parse_json_array(value, label):
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        sys.exit(f"{label} 需要 JSON 数组，例如 [1,3,5]")
    if not isinstance(parsed, list):
        sys.exit(f"{label} 需要 JSON 数组，例如 [1,3,5]")
    return parsed


def _resolve_container_name():
    override = os.environ.get("MH_CONTAINER", "").strip()
    if override:
        return override
    candidates = ("115-media-hub", "115-media-hub-test")
    try:
        proc = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        existing = set(proc.stdout.split())
    except Exception:
        existing = set()
    for name in candidates:
        if name in existing:
            return name
    return candidates[0]


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
                            domain=cookie_data.get("domain", urlparse(self.base_url).hostname or "127.0.0.1"),
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
        os.chmod(COOKIE_FILE, 0o600)

    def _resolve_credentials(self):
        username = MH_USERNAME
        password = MH_PASSWORD
        if username and password:
            return username, password
        if not sys.stdin.isatty():
            sys.exit(
                "未提供登录凭据：请设置 MH_USERNAME/MH_PASSWORD 环境变量"
                "（密码为面板网页登录使用的同一密码），或在交互终端运行本命令"
            )
        import getpass

        username = username or input("用户名: ").strip()
        password = password or getpass.getpass("密码: ")
        return username, password

    def _login_if_needed(self):
        session = self._ensure_session()
        r = session.get("/status-summary")
        if r.status_code == 401:
            username, password = self._resolve_credentials()
            r = session.post("/login", json={"username": username, "password": password})
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
    if args.cancel:
        data = c.json("POST", "/resource/search/cancel", {})
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
        sync_payload = {"force": args.force}
        if args.limit:
            sync_payload["limit"] = args.limit
        data = c.json("POST", "/resource/channels/sync", sync_payload)
        print(f"✅ 频道同步已提交（后台执行）: {json.dumps(data, ensure_ascii=False)}")
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
        classify_payload = {"channel_id": channel_id}
        if args.sample_size:
            classify_payload["sample_size"] = args.sample_size
        data = c.json("POST", "/resource/channels/classify", classify_payload)
        print(f"✅ 频道分类已完成: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "more":
        channel_id = args.channel_id or ""
        if not channel_id:
            sys.exit("请指定频道 ID（--channel 参数）")
        more_payload = {"channel_id": channel_id, "limit": args.limit or 10}
        if args.before:
            more_payload["before"] = args.before
        if args.query:
            more_payload["query"] = args.query
        if args.provider_filter:
            more_payload["provider_filter"] = args.provider_filter
        data = c.json("POST", "/resource/channels/more", more_payload)
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
        # 解析别名
        aliases_list = [a.strip() for a in args.aliases.split(",") if a.strip()] if args.aliases else []
        exclude_list = [k.strip() for k in args.exclude_keywords.split(",") if k.strip()] if args.exclude_keywords else []
        new_task = {
            "name": title.strip(),
            "media_type": args.type,
            "title": (args.title or title).strip(),
            "keyword": title.strip(),
            "quality": args.quality,
            "savepath": _get_default_savepath(c.json("GET", "/get_settings"), args.type or "movie") if not args.savepath else args.savepath.rstrip("/"),
            "provider": args.provider,
            "season": args.season,
            "total_episodes": args.total_episodes,
            "aliases": aliases_list,
            "exclude_keywords": exclude_list,
            "min_score": args.min_score,
            "anime_mode": args.anime_mode,
            "strict_title_match": args.strict_match,
            "cron_minutes": args.cron_minutes,
            "enabled": True,
            # Extended parameters
            "year": args.year or "",
            "quality_priority": args.quality_priority or "balanced",
            "min_file_size_mb": args.min_file_size_mb or 0,
            "exclude_file_extensions": args.exclude_file_extensions or "",
            "tmdb_id": args.tmdb_id or 0,
            "tmdb_media_type": args.tmdb_media_type or "",
            "tmdb_episode_mode": args.tmdb_episode_mode or "seasonal",
            "share_link_url": args.link or "",
            "share_link_receive_code": args.receive_code or "",
            "share_subdir": args.share_subdir or "",
            "share_subdir_cid": args.share_subdir_cid or "",
            "fixed_link_channel_search": args.fixed_link_channel_search,
            "candidate_scan_prefetch_limit": args.candidate_scan_prefetch_limit or 0,
            "candidate_scan_concurrency": args.candidate_scan_concurrency or 0,
            "share_scan_concurrency": args.share_scan_concurrency or 0,
            "share_scan_rate_limit_seconds": args.share_scan_rate_limit_seconds or 0.0,
            "schedule_weekdays": _parse_json_array(args.schedule_weekdays, "--schedule-weekdays"),
            "schedule_start_time": args.schedule_start_time or "",
            "schedule_end_time": args.schedule_end_time or "",
        }
        # 未指定查询星期时，移除字段让后端 fallback 到全周
        if not new_task.get("schedule_weekdays") and new_task.get("cron_minutes", 0) > 0:
            del new_task["schedule_weekdays"]
        c.json("POST", "/subscription/save", {"tasks": tasks + [new_task]})
        print(f"✅ 已创建订阅「{title}」")

    elif args.action == "remove":
        name = " ".join(args.name)
        if not any(str(t.get("name", "") or "").strip() == name.strip() for t in tasks):
            sys.exit(f"未找到订阅「{name}」")
        data = c.json("POST", "/subscription/delete", {"name": name})
        print(f"✅ 已删除订阅「{name}」")

    elif args.action == "start":
        name = " ".join(args.name) if args.name else ""
        if not name:
            sys.exit("请指定订阅名称")
        data = c.json("POST", "/subscription/start", {"name": name})
        print(f"✅ 订阅已触发: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "stop":
        name = " ".join(args.name) if args.name else ""
        if not name:
            sys.exit("请指定订阅名称")
        data = c.json("POST", "/subscription/stop", {"name": name})
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
        name = args.task_name or ""
        if not name:
            sys.exit("请指定订阅名称（--task-name 参数）")
        data = c.json("POST", "/subscription/rebuild", {"name": name})
        print(f"✅ 订阅已重建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "episodes":
        name = args.task_name or ""
        if not name:
            sys.exit("请指定订阅名称（--task-name 参数）")
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
        name = " ".join(args.name) if args.name else ""
        if not name:
            sys.exit("请指定订阅名称")
        data = c.json("POST", "/subscription/start_with_link", {"name": name, "link_url": link, "receive_code": args.receive_code or "", "savepath": args.savepath})
        print(f"✅ 订阅已通过链接触发: {json.dumps(data, ensure_ascii=False)}")


def cmd_jobs(args, c: Client):
    """管理资源任务"""
    if args.action == "list":
        data = c.json("GET", "/resource/jobs/state", {"limit": args.limit, "status": args.status or ""})
        print(fmt_json(data))
    elif args.action == "clear":
        data = c.json("POST", "/resource/jobs/clear", {})
        print(f"✅ 已清理: {json.dumps(data, ensure_ascii=False)}")
    elif args.action in ("clear_completed", "clear-completed"):
        data = c.json("POST", "/resource/jobs/clear_completed")
        print(f"✅ 已完成任务已清理: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "retry":
        if not args.job_id:
            sys.exit("请指定任务 ID（--job-id）")
        job_id = _require_int(args.job_id, "任务 ID")
        data = c.json("POST", "/resource/jobs/retry", {"job_id": job_id})
        print(f"✅ 已重试: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "create":
        resource_id = args.resource_id or ""
        if not resource_id:
            sys.exit("请指定资源 ID（--resource-id，先 search 获取）")
        resource_id_int = _require_int(resource_id, "资源 ID")
        _cfg = c.json("GET", "/get_settings") if not args.savepath else None
        savepath = args.savepath or _get_default_savepath(_cfg or {}, "movie")
        payload = {"resource_id": resource_id_int, "savepath": savepath}
        if args.receive_code:
            payload["receive_code"] = args.receive_code
        if args.magnet_provider:
            payload["magnet_provider"] = args.magnet_provider
        if args.no_auto_refresh:
            payload["auto_refresh"] = False
        if args.allow_duplicate:
            payload["allow_duplicate"] = True
        if args.folder_id:
            payload["folder_id"] = args.folder_id
        data = c.json("POST", "/resource/jobs/create", payload)
        print(f"✅ 转存任务已创建: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "refresh":
        job_id = args.job_id or ""
        if not job_id:
            sys.exit("请指定任务 ID（--job-id）")
        data = c.json("POST", "/resource/jobs/refresh", {"job_id": _require_int(job_id, "任务 ID")})
        print(f"✅ 已触发刷新: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "cancel":
        job_id = args.job_id or ""
        if not job_id:
            sys.exit("请指定任务 ID（--job-id）")
        data = c.json("POST", "/resource/jobs/cancel", {"job_id": _require_int(job_id, "任务 ID")})
        print(f"✅ 已取消任务: {json.dumps(data, ensure_ascii=False)}")


def _get_default_savepath(cfg: dict, media_type: str = "movie") -> str:
    """从 resource_favorite_dirs 按媒体类型匹配默认路径"""
    if not isinstance(cfg, dict):
        return "/电影" if media_type == "movie" else "/剧集"
    fav = cfg.get("resource_favorite_dirs", {})
    all_dirs = []
    for provider_dirs in fav.values() if isinstance(fav, dict) else []:
        if isinstance(provider_dirs, list):
            all_dirs.extend(provider_dirs)
    if media_type == "tv":
        tv_keywords = ["电视剧", "剧集", "tv", "连续剧", "动漫", "动画"]
        for d in all_dirs:
            name = (d.get("name", "") or "").lower()
            for kw in tv_keywords:
                if kw in name:
                    return d.get("path", "")
    movie_keywords = ["电影", "movie", "影片", "影视"]
    for d in all_dirs:
        name = (d.get("name", "") or "").lower()
        for kw in movie_keywords:
            if kw in name:
                return d.get("path", "")
    if all_dirs:
        return all_dirs[0].get("path", "")
    return "/电影" if media_type == "movie" else "/剧集"


def cmd_offline(args, c: Client):
    """115 官方离线任务只读诊断"""
    if args.action == "list":
        page = max(1, int(getattr(args, "page", 1) or 1))
        data = c.json("GET", f"/resource/offline/tasks?page={page}")
        if not isinstance(data, dict) or not data.get("ok"):
            print(f"❌ 读取离线任务失败: {data.get('msg', '未知错误') if isinstance(data, dict) else data}")
            return
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        if not tasks:
            print("无离线任务（或 115 Cookie 未配置）")
            return
        status_labels = {0: "等待", 1: "下载中", 2: "已完成", -1: "失败"}
        for task in tasks:
            status = int(task.get("status", 0) or 0)
            percent = int(float(task.get("percent", 0) or 0))
            name = str(task.get("name", "") or "").strip() or str(task.get("url", "") or "").strip()
            print(
                f"  • [{status_labels.get(status, '未知')}] {percent}%  "
                f"{name[:72]}  hash={task.get('info_hash', '')}  dir={task.get('wp_path_id', '')}"
            )


def cmd_settings(args, c: Client):
    """查看/修改配置"""
    if args.favorite_dirs_115 is not None or args.favorite_dirs_quark is not None:
        cfg = c.json("GET", "/get_settings")
        fav = cfg.setdefault("resource_favorite_dirs", {"115": [], "quark": [], "tianyi": [], "123pan": [], "aliyun": []})
        if args.favorite_dirs_115 is not None:
            items = []
            for token in args.favorite_dirs_115.split(","):
                token = token.strip()
                if not token:
                    continue
                if "=" in token:
                    n, p = token.split("=", 1)
                    items.append({"name": n.strip(), "path": p.strip()})
                else:
                    items.append({"name": token.split("/")[-1], "path": token})
            fav["115"] = items
            print(f"✅ 115 常用目录: {len(items)} 个")
        if args.favorite_dirs_quark is not None:
            items = []
            for token in args.favorite_dirs_quark.split(","):
                token = token.strip()
                if not token:
                    continue
                if "=" in token:
                    n, p = token.split("=", 1)
                    items.append({"name": n.strip(), "path": p.strip()})
                else:
                    items.append({"name": token.split("/")[-1], "path": token})
            fav["quark"] = items
            print(f"✅ Quark 常用目录: {len(items)} 个")
        c.json("POST", "/save_settings", cfg)
        print("✅ 配置已保存")
        return
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
                try:
                    cfg[key] = int(val)
                except ValueError:
                    print(f"⚠️ {key} 需要整数，已跳过")
                    continue
            elif isinstance(existing, float):
                try:
                    cfg[key] = float(val)
                except ValueError:
                    print(f"⚠️ {key} 需要数字，已跳过")
                    continue
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
        data = c.json("POST", "/settings/cookies/check", {})
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
        tmdb_id = args.tmdb_id or ""
        if not tmdb_id:
            sys.exit("请指定 TMDB ID（--tmdb-id）")
        media_type = args.media_type or ""
        if not media_type:
            sys.exit("请指定媒体类型（--media-type movie|tv）")
        data = c.json("GET", "/tmdb/detail", {"tmdb_id": _require_int(tmdb_id, "TMDB ID"), "media_type": media_type})
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
            # Extended params
            "target_path": args.target_path or "",
            "skip_by_dir_mtime": args.skip_dir_mtime,
            "strm_write_mode": args.strm_write_mode or "incremental",
            "sync_clean": not args.incremental,
            "retries": args.retries or 3,
            "list_delay_ms": args.list_delay_ms or 250,
            "min_file_size_mb": args.min_file_size_mb or 0,
            "auto_scrape_on_new": args.auto_scrape_on_new,
            "auto_scrape_options": _parse_auto_scrape_options(args.auto_scrape_options_json),
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
        if not any(str(t.get("name", "") or "").strip() == name for t in tasks):
            sys.exit(f"未找到监控任务「{name}」")
        data = c.json("POST", "/monitor/delete", {"name": name})
        print(f"✅ 已删除监控任务「{name}」")

    elif args.action == "start":
        name = args.name.strip() if args.name else ""
        if not name:
            sys.exit("请指定监控任务名称")
        data = c.json("POST", "/monitor/start", {"name": name})
        print(f"✅ 监控已启动: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "stop":
        name = args.name.strip() if args.name else ""
        if not name:
            sys.exit("请指定监控任务名称")
        data = c.json("POST", "/monitor/stop", {"name": name})
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
        if getattr(args, "id", None):
            data = c.json("POST", f"/tree/tasks/{args.id}/run", {})
            print(f"✅ 目录树任务已触发: {json.dumps(data, ensure_ascii=False)}")
        else:
            data = c.json("POST", "/tree/sync-all", {})
            print(f"✅ 目录树下载并生成已触发: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "full":
        if not getattr(args, "id", None):
            print("❌ 全量重写需要 --id 指定目录树任务")
            return
        data = c.json("POST", f"/tree/tasks/{args.id}/full", {})
        print(f"✅ 目录树全量重写已触发: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "list":
        data = c.json("GET", "/tree/tasks")
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        if not tasks:
            print("无目录树任务")
            return
        for task in tasks:
            print(
                f"  • {task.get('id', '')}  {task.get('folder_path', '')}  →  {task.get('tree_name', '')}  "
                f"[前缀={task.get('prefix', '')} 排除={task.get('exclude', 1)}]"
            )
    elif args.action == "create":
        folder = getattr(args, "folder", None)
        if not folder:
            print("❌ 创建目录树任务需要 --folder 指定 115 文件夹路径")
            return
        payload = {"folder_path": folder}
        if getattr(args, "name", None):
            payload["tree_name"] = args.name
        data = c.json("POST", "/tree/tasks", payload)
        print(f"✅ 目录树任务已创建: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "defaults":
        folder = getattr(args, "folder", None)
        if not folder:
            print("❌ 查看自动填充参数需要 --folder 指定 115 文件夹路径")
            return
        data = c.json("GET", f"/tree/task-defaults?folder_path={quote(folder)}")
        defaults = data.get("defaults", {}) if isinstance(data, dict) else {}
        print(
            f"  树文件名: {defaults.get('tree_name', '')}\n"
            f"  父文件夹路径前缀: {defaults.get('prefix', '') or '（空）'}\n"
            f"  排除层级: {defaults.get('exclude', 1)}"
        )
    elif args.action == "update":
        task_id = getattr(args, "id", None)
        if not task_id:
            print("❌ 更新目录树任务需要 --id")
            return
        payload = {}
        if getattr(args, "folder", None):
            payload["folder_path"] = args.folder
        if getattr(args, "name", None):
            payload["tree_name"] = args.name
        if not payload:
            print("❌ 更新目录树任务需要 --folder 或 --name")
            return
        data = c.json("POST", f"/tree/tasks/{task_id}", payload)
        print(f"✅ 目录树任务已更新: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "delete":
        if not getattr(args, "id", None):
            print("❌ 删除目录树任务需要 --id")
            return
        data = c.json("DELETE", f"/tree/tasks/{args.id}")
        print(f"✅ 目录树任务已删除: {json.dumps(data, ensure_ascii=False)}")
    elif args.action == "jobs":
        data = c.json("GET", "/tree/jobs")
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        if not jobs:
            print("无目录树任务记录")
            return
        for job in jobs:
            print(
                f"  #{job.get('id', '')}  {job.get('folder_path', '')}  "
                f"[{job.get('status', '')}] changed={job.get('changed', 0)}  "
                f"parsed={job.get('parsed_count', 0)}  generated={job.get('generated_count', 0)}  "
                f"export={job.get('export_id', '') or '-'}  {job.get('submitted_at', '')}"
            )
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
        data = c.json("GET", "/tree/logs")
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
        data = c.json("POST", "/tree/logs/clear")
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

    _require_docker()
    container = _resolve_container_name()

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
        safe_kw = json.dumps(keyword)
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
        data = c.json("GET", "/resource/browse", {"provider": provider, "cid": cid})
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
        data = c.json("GET", "/resource/browse", {"provider": provider, "cid": cid, "folders_only": "1"})
        entries = data if isinstance(data, list) else data.get("entries", data.get("items", []))
        if not entries:
            print("(空目录)")
            return
        _print_tree([entry for entry in entries if entry.get("is_dir")], provider, c, prefix="")

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
            sub = c.json("GET", "/resource/browse", {"provider": provider, "cid": file_id, "folders_only": "1"})
            sub_items = sub if isinstance(sub, list) else sub.get("entries", sub.get("items", []))
            if sub_items:
                sub_prefix = prefix + ("    " if is_last else "│   ")
                _print_tree(
                    [entry for entry in sub_items if entry.get("is_dir")],
                    provider,
                    c,
                    sub_prefix,
                    depth + 1,
                )


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
        body = {"link_url": url, "receive_code": code, "cid": cid}
        if args.raw_text:
            body["raw_text"] = args.raw_text
        if args.paged:
            body["paged"] = True
        if args.folders_only:
            body["folders_only"] = True
        if args.force_refresh:
            body["force_refresh"] = True
        if args.offset:
            body["offset"] = args.offset
        if args.limit:
            body["limit"] = args.limit
        try:
            data = c.json("POST", f"/resource/browse/{provider}/share_entries_preview", body)
        except SystemExit:
            # Try direct provider endpoint
            data = c.json("POST", f"/resource/{provider}/share_entries_preview", body)
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
            sys.exit("请指定资源 ID（--resource-id，先 search 获取）")
        resource_id_int = _require_int(resource_id, "资源 ID")
        _cfg = c.json("GET", "/get_settings") if not args.savepath else None
        savepath = args.savepath or _get_default_savepath(_cfg or {}, "movie")
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
        payload = {"resource_id": resource_id_int, "savepath": savepath}
        if args.receive_code:
            payload["receive_code"] = args.receive_code
        if args.magnet_provider:
            payload["magnet_provider"] = args.magnet_provider
        data = c.json("POST", "/resource/jobs/create", payload)
        print(f"✅ 转存任务已创建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "preview-batch":
        url = args.url or ""
        if not url:
            sys.exit("请指定分享链接")
        provider = args.provider or "115"
        data = c.json("POST", f"/resource/browse/{provider}/share_entries_preview", {"link_url": url})
        print(fmt_json(data))


# ── Phase 3: scrape ────────────────────────────────────────────────────────

def _build_scrape_plan_options(args) -> Dict[str, Any]:
    """把 rename-plan 命令行参数组装成 options；未传任何选项时返回空 dict。"""
    options: Dict[str, Any] = {}
    if args.file_name_mode:
        options["file_name_mode"] = args.file_name_mode
    if args.no_rename_folders:
        options["rename_selected_folders"] = False
    if args.no_season_subfolder:
        options["use_season_subfolder"] = False
    if args.include_tmdb_id:
        options["include_tmdb_id"] = True
    if args.delete_ad_files:
        options["delete_ad_files"] = True
    if args.title_language:
        options["title_language"] = args.title_language
    if args.season is not None:
        options["season"] = max(1, min(99, args.season))
    if args.episode_mode:
        options["episode_mode"] = args.episode_mode
    if args.preserve_file_info:
        options["preserve_file_info"] = True
    if args.options_json:
        try:
            extra = json.loads(args.options_json)
        except (ValueError, TypeError):
            sys.exit("--options-json 必须是合法 JSON 对象")
        if not isinstance(extra, dict):
            sys.exit("--options-json 必须是 JSON 对象")
        options.update(extra)
    return options


def _parse_auto_scrape_options(raw: str) -> Dict[str, Any]:
    """解析 monitor add 的 --auto-scrape-options-json，非法 JSON 直接报错退出。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        sys.exit("--auto-scrape-options-json 必须是合法 JSON 对象")
    if not isinstance(parsed, dict):
        sys.exit("--auto-scrape-options-json 必须是 JSON 对象")
    return parsed


def cmd_scrape(args, c: Client):
    """刮削管理"""
    if args.action == "identify":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        payload = {"entries": [{"path": path}]}
        if args.provider:
            payload["provider"] = args.provider
        data = c.json("POST", "/scraper/identify", payload)
        print(fmt_json(data))

    elif args.action == "rename-plan":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        payload = {"entries": [{"path": path}]}
        if args.provider:
            payload["provider"] = args.provider
        options = _build_scrape_plan_options(args)
        if options:
            payload["options"] = options
        data = c.json("POST", "/scraper/rename-plan", payload)
        print(fmt_json(data))

    elif args.action == "batch-preferences":
        sub = " ".join(args.path).strip() if args.path else ""
        if sub not in ("get", "set", "clear"):
            sys.exit("batch-preferences 需要子动作：get | set | clear")
        provider = args.provider or "115"
        if sub == "get":
            data = c.json("GET", f"/scraper/{provider}/batch/preferences")
        else:
            options: Dict[str, Any] = {}
            if sub == "set":
                if not args.options_json:
                    sys.exit("batch-preferences set 需要 --options-json")
                try:
                    options = json.loads(args.options_json)
                except (ValueError, TypeError):
                    sys.exit("--options-json 必须是合法 JSON 对象")
                if not isinstance(options, dict):
                    sys.exit("--options-json 必须是 JSON 对象")
            data = c.json("POST", f"/scraper/{provider}/batch/preferences", {"options": options})
        print(fmt_json(data))

    elif args.action == "diff":
        job_id = args.job_id or ""
        if not job_id:
            sys.exit("请指定 Job ID（--job-id）")
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
        params = {"limit": args.limit or 20}
        if args.job_id:
            params["job_id"] = _require_int(args.job_id, "Job ID")
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
        payload = {"cid": cid}
        if args.name:
            payload["name"] = args.name
        data = c.json("POST", f"/scraper/{provider}/folders", payload)
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
        new_path = args.new_path or ""
        if not new_path:
            sys.exit("请指定新路径（--new-path）")
        provider = args.provider or "115"
        data = c.json("POST", f"/scraper/{provider}/rename-warning", {"old_path": path, "new_path": new_path})
        print(fmt_json(data))

    elif args.action == "rename":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        name = args.name or ""
        if not name:
            sys.exit("请指定新名称（--name）")
        provider = args.provider or "115"
        payload = {"path": path, "name": name}
        if args.parent_id:
            payload["parent_id"] = args.parent_id
        data = c.json("POST", f"/scraper/{provider}/rename", payload)
        print(f"✅ 已重命名: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "jobs-create":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        provider = args.provider or "115"
        identified = c.json("POST", "/scraper/identify", {"entries": [{"path": path}], "provider": provider})
        if not isinstance(identified, dict):
            sys.exit("识别失败，请检查路径是否正确")
        query = str(identified.get("query", "") or "").strip()
        media_type = str(identified.get("media_type", "") or "movie").strip()
        if not query:
            sys.exit("无法从路径识别出查询关键词，请检查路径是否正确")
        tmdb_id_raw = str(args.tmdb_id or "").strip()
        if tmdb_id_raw:
            tmdb_item = {
                "id": _require_int(tmdb_id_raw, "TMDB ID"),
                "media_type": args.media_type or media_type,
            }
        else:
            tmdb_data = c.json("GET", "/tmdb/search", {"q": query, "media_type": media_type, "page": 1})
            items = tmdb_data.get("items", []) if isinstance(tmdb_data, dict) else []
            if not items:
                sys.exit(f"TMDB 未找到与「{query}」匹配的条目；可指定 --tmdb-id 手动选择")
            if len(items) > 1:
                print(f"⚠️ 识别到 {len(items)} 个候选，默认使用第一个；如需指定请用 --tmdb-id：")
                for item in items[:10]:
                    item_title = str(item.get("title", "") or item.get("name", "") or "?").strip()
                    item_year = str(item.get("year", "") or "").strip()
                    print(f"  {int(item.get('id', 0) or 0)}  {item_title}  ({item_year})")
            tmdb_item = items[0]
        tmdb = dict(tmdb_item)
        tmdb.setdefault("tmdb_id", int(tmdb_item.get("id", 0) or 0))
        tmdb.setdefault("tmdb_media_type", str(tmdb_item.get("media_type", "") or media_type).strip())
        plan = c.json(
            "POST",
            "/scraper/rename-plan",
            {"entries": [{"path": path}], "provider": provider, "tmdb": tmdb, "options": {}},
        )
        if not isinstance(plan, dict) or not plan.get("actions"):
            sys.exit("未能生成改名计划，请检查路径与 TMDB 条目")
        if not plan.get("ready"):
            for issue in plan.get("issues", []) if isinstance(plan.get("issues"), list) else []:
                print(f"  ⚠️ {issue}")
            for warning in plan.get("warnings", []) if isinstance(plan.get("warnings"), list) else []:
                print(f"  ⚠️ {warning}")
            sys.exit("改名计划仍存在冲突或未识别项，请先处理后再执行")
        data = c.json("POST", "/scraper/jobs/create", {"plan": plan})
        print(f"✅ 刮削任务已创建: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "move":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        dest = args.dest or ""
        if not dest:
            sys.exit("请指定目标路径（--dest）")
        provider = args.provider or "115"
        payload = {"path": path, "dest": dest}
        if args.source_cid:
            payload["source_cid"] = args.source_cid
        data = c.json("POST", f"/scraper/{provider}/move", payload)
        print(f"✅ 移动完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "copy":
        path = " ".join(args.path) if args.path else ""
        if not path:
            sys.exit("请指定文件路径")
        dest = args.dest or ""
        if not dest:
            sys.exit("请指定目标路径（--dest）")
        provider = args.provider or "115"
        payload = {"path": path, "dest": dest}
        if args.source_cid:
            payload["source_cid"] = args.source_cid
        data = c.json("POST", f"/scraper/{provider}/copy", payload)
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
        payload = {"path": path}
        if args.parent_id:
            payload["parent_id"] = args.parent_id
        data = c.json("POST", f"/scraper/{provider}/delete", payload)
        print(f"✅ 删除完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "rollback":
        job_id = args.job_id or ""
        if not job_id:
            sys.exit("请指定 Job ID（--job-id）")
        data = c.json("POST", f"/scraper/jobs/{job_id}/rollback")
        print(f"✅ 回滚完成: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "jobs-clear":
        data = c.json("POST", "/scraper/jobs/clear", {})
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
            item_id = item.get("id", "?")
            status = item.get("status", "pending")
            status_icon = {"want": "⏳", "subscribed": "📺", "done": "✅"}.get(status, "⏳")
            print(f"  {status_icon} {title}  (id={item_id})  [{status}]")

    elif args.action == "add":
        tmdb_id = args.tmdb_id[0] if args.tmdb_id else ""
        title = args.title or ""
        if not tmdb_id:
            sys.exit("请指定 TMDB ID")
        if not title:
            sys.exit("请指定标题（--title）")
        payload = {"tmdb_id": _require_int(tmdb_id, "TMDB ID"), "title": title, "media_type": args.type or "movie"}
        if args.original_title:
            payload["original_title"] = args.original_title
        if args.year:
            payload["year"] = args.year
        if args.poster_url:
            payload["poster_url"] = args.poster_url
        if args.overview:
            payload["overview"] = args.overview
        if args.vote_average:
            payload["vote_average"] = float(args.vote_average)
        data = c.json("POST", "/recommendation/watchlist/add", payload)
        print(f"✅ 已添加到推荐清单: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "remove":
        item_id = args.id or ""
        if not item_id:
            sys.exit("请指定记录 ID（--id，通过 list 获取）")
        data = c.json("POST", "/recommendation/watchlist/remove", {"id": _require_int(item_id, "记录 ID")})
        print(f"✅ 已从推荐清单移除: {json.dumps(data, ensure_ascii=False)}")

    elif args.action == "update":
        item_id = args.id or ""
        if not item_id:
            sys.exit("请指定记录 ID（--id，通过 list 获取）")
        status = args.status or "done"
        data = c.json("POST", "/recommendation/watchlist/update_status",
                       {"id": _require_int(item_id, "记录 ID"), "status": status})
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
        data = c.json("POST", "/strm/orphan-metadata/delete", {})
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
        payload = {"raw_text": text, "provider": provider}
        if args.source_name:
            payload["source_name"] = args.source_name
        if args.source_type:
            payload["source_type"] = args.source_type
        if args.channel_name:
            payload["channel_name"] = args.channel_name
        if args.published_at:
            payload["published_at"] = args.published_at
        if args.message_url:
            payload["message_url"] = args.message_url
        data = c.json("POST", "/resource/items/import_text", payload)
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
        payload = {"raw_text": text}
        if args.source_name:
            payload["source_name"] = args.source_name
        if args.source_type:
            payload["source_type"] = args.source_type
        if args.channel_name:
            payload["channel_name"] = args.channel_name
        if args.published_at:
            payload["published_at"] = args.published_at
        if args.message_url:
            payload["message_url"] = args.message_url
        data = c.json("POST", "/resource/items/preview_text", payload)
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
        resource_id = args.resource_id or ""
        if not resource_id:
            sys.exit("请指定资源 ID（--id 参数）")
        resource_id_int = _require_int(resource_id, "资源 ID")
        confirm = args.yes or input(f"确定要删除资源 #{resource_id_int}？(y/N): ").lower() == "y"
        if not confirm:
            print("已取消")
            return
        data = c.json("POST", "/resource/items/delete", {"id": resource_id_int})
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
        container = _resolve_container_name()
        r = subprocess.run(
            ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Status}}"],
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
    _require_docker()
    container = _resolve_container_name()

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
    sp_search.add_argument("--cancel", action="store_true", help="取消当前搜索")
    sp_search.add_argument("keyword", nargs="*", help="搜索关键词 (留空=cancel 时忽略)")

    # channels
    sp_ch = sp.add_parser("channels", help="管理资源频道")
    sp_ch.add_argument("action", choices=["sync", "list", "classify", "more", "sync-names", "sync-cancel"], help="sync=同步, list=列出, classify=分类, more=更多内容, sync-names=同步名称, sync-cancel=取消同步")
    sp_ch.add_argument("--force", action="store_true", help="强制重新同步")
    sp_ch.add_argument("--channel", dest="channel_id", default="", help="频道 ID (more/classify/sync-names)")
    sp_ch.add_argument("--limit", type=int, default=10, help="条数 (more/sync 每频道限制)")
    sp_ch.add_argument("--sample-size", type=int, default=0, help="采样条数 (classify, 1-100)")
    sp_ch.add_argument("--before", default="", help="翻页游标 (more)")
    sp_ch.add_argument("--query", default="", help="搜索关键词 (more)")
    sp_ch.add_argument("--provider-filter", default="", help="提供商过滤 (more, all/115/quark)")

    # subscribe
    sp_sub = sp.add_parser("subscribe", help="管理订阅")
    sp_sub.add_argument("action", choices=["list", "add", "remove", "start", "stop", "status", "logs", "logs-clear", "rebuild", "episodes", "start-with-link"])
    sp_sub.add_argument("name", nargs="*", help="订阅名称 (add/remove/start)")
    sp_sub.add_argument("--type", default="movie", choices=["movie", "tv"], help="媒体类型")
    sp_sub.add_argument("--quality", default="balanced", help="质量偏好 (4K/1080p/720p/balanced)")
    sp_sub.add_argument("--savepath", default="", help="115 保存路径（留空自动按媒体类型从常用目录推断）")
    sp_sub.add_argument("--provider", default="115", choices=["115", "quark"], help="网盘提供商")
    sp_sub.add_argument("--link", default="", help="资源链接 (start-with-link)")
    sp_sub.add_argument("--task-name", default="", help="订阅名称 (rebuild/episodes)")
    # 补充参数
    sp_sub.add_argument("--title", default="", help="订阅标题（用于显示，可与名称不同）")
    sp_sub.add_argument("--aliases", default="", help="别名（逗号分隔，增加匹配率）")
    sp_sub.add_argument("--season", type=int, default=1, help="季度号（剧集）")
    sp_sub.add_argument("--total-episodes", type=int, default=0, help="总集数")
    sp_sub.add_argument("--exclude-keywords", default="", help="排除关键词（逗号分隔）")
    sp_sub.add_argument("--min-score", type=int, default=60, help="最低匹配分数 (0-100)")
    sp_sub.add_argument("--anime-mode", action="store_true", help="番剧匹配模式（多季/严格匹配）")
    sp_sub.add_argument("--strict-match", action="store_true", help="严格标题匹配")
    sp_sub.add_argument("--cron-minutes", type=int, default=120, help="定时扫描间隔（分钟）")
    # 扩展参数
    sp_sub.add_argument("--year", default="", help="年份过滤（如 2024）")
    sp_sub.add_argument("--quality-priority", default="balanced", choices=["balanced", "ultra", "fhd", "hd", "sd"], help="画质优先级")
    sp_sub.add_argument("--min-file-size-mb", type=int, default=0, help="最小文件大小（MB）")
    sp_sub.add_argument("--exclude-file-extensions", default="", help="排除文件扩展名（逗号分隔）")
    sp_sub.add_argument("--tmdb-id", type=int, default=0, help="TMDB ID（精确绑定）")
    sp_sub.add_argument("--tmdb-media-type", default="", choices=["movie", "tv"], help="TMDB 媒体类型")
    sp_sub.add_argument("--tmdb-episode-mode", default="seasonal", choices=["seasonal", "separate"], help="剧集模式")
    sp_sub.add_argument("--receive-code", default="", help="分享提取码（start-with-link 或订阅固定链接）")
    sp_sub.add_argument("--share-subdir", default="", help="分享子目录路径")
    sp_sub.add_argument("--share-subdir-cid", default="", help="分享子目录 ID")
    sp_sub.add_argument("--fixed-link-channel-search", action="store_true", help="固定链接辅助频道搜索")
    sp_sub.add_argument("--candidate-scan-prefetch-limit", type=int, default=0, help="候选扫描预取数（0-80）")
    sp_sub.add_argument("--candidate-scan-concurrency", type=int, default=0, help="候选扫描并发（1-6）")
    sp_sub.add_argument("--share-scan-concurrency", type=int, default=0, help="分享扫描并发（1-6）")
    sp_sub.add_argument("--share-scan-rate-limit-seconds", type=float, default=0.0, help="分享扫描速率限制（0.05-5s）")
    sp_sub.add_argument("--schedule-weekdays", default="[]", help="周几执行 JSON 数组（如 [1,3,5]）")
    sp_sub.add_argument("--schedule-start-time", default="", help="开始时间（HH:MM）")
    sp_sub.add_argument("--schedule-end-time", default="", help="结束时间（HH:MM）")

    # jobs
    sp_jobs = sp.add_parser("jobs", help="管理资源任务")
    sp_jobs.add_argument("action", choices=["list", "clear", "clear_completed", "clear-completed", "retry", "create", "refresh", "cancel"])
    sp_jobs.add_argument("--job-id", default="", help="任务 ID (retry/refresh/cancel)")
    sp_jobs.add_argument("--limit", type=int, default=20, help="列表条数")
    sp_jobs.add_argument("--status", default="", help="过滤状态 (pending/submitted/completed/failed)")
    sp_jobs.add_argument("--resource-id", default="", help="资源 ID (create)")
    sp_jobs.add_argument("--savepath", default="/115", help="保存路径 (create)")
    sp_jobs.add_argument("--receive-code", default="", help="分享提取码 (create)")
    sp_jobs.add_argument("--magnet-provider", default="", help="磁力下载网盘 (create, 默认 115)")
    sp_jobs.add_argument("--no-auto-refresh", action="store_true", help="不自动刷新 (create)")
    sp_jobs.add_argument("--allow-duplicate", action="store_true", help="允许重复导入 (create)")
    sp_jobs.add_argument("--folder-id", default="", help="目标文件夹 ID (create)")

    # settings
    sp_set = sp.add_parser("settings", help="查看/修改配置")
    sp_set.add_argument("kv", nargs="*", help='key=value (例如 cookie_115="xxx")')
    sp_set.add_argument("--test-proxy", action="store_true", help="测试 TG 代理连接")
    sp_set.add_argument("--test-pansou", action="store_true", help="测试 PanSou 盘搜")
    sp_set.add_argument("--test-notify", action="store_true", help="测试通知推送")
    sp_set.add_argument("--favorite-dirs-115", default=None, help="115 常用目录（逗号分隔，如 电影=影视/电影,电视剧=影视/电视剧）")
    sp_set.add_argument("--favorite-dirs-quark", default=None, help="Quark 常用目录（逗号分隔）")

    # logs
    sp_logs = sp.add_parser("logs", help="查看系统日志")
    sp_logs.add_argument("action", nargs="?", default="", choices=["", "clear"], help="clear=清除日志, 留空=查看")
    sp_logs.add_argument("--tail", type=int, default=0, help="只显示最后 N 条（与 clear 互斥）")

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
    sp_tmdb.add_argument("--tmdb-id", default="", help="TMDB ID (detail)")
    sp_tmdb.add_argument("--media-type", default="", choices=["movie", "tv"], help="媒体类型 (detail: movie/tv)")
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
    sp_mon.add_argument("--target-path", default="", help="STRM 输出目标路径 (add)")
    sp_mon.add_argument("--skip-dir-mtime", action="store_true", help="跳过目录 mtime 检测 (add)")
    sp_mon.add_argument("--strm-write-mode", default="incremental", choices=["incremental", "full"], help="STRM 写入模式 (add)")
    sp_mon.add_argument("--incremental", action="store_true", help="增量模式（不清理已删除文件）(add)")
    sp_mon.add_argument("--retries", type=int, default=3, help="最大重试次数 (add)")
    sp_mon.add_argument("--list-delay-ms", type=int, default=250, help="列表请求延迟毫秒数 (add)")
    sp_mon.add_argument("--min-file-size-mb", type=float, default=0.0, help="最小文件大小 MB (add)")
    sp_mon.add_argument("--auto-scrape-on-new", action="store_true", help="新增资源自动刮削整理 (add)")
    sp_mon.add_argument("--auto-scrape-options-json", default="", help="自动整理选项 JSON 对象 (add)，如 {\"file_name_mode\":\"keep\"}")

    # tree
    sp_tree = sp.add_parser("tree", help="目录树同步")
    sp_tree.add_argument(
        "action",
        choices=["run", "full", "list", "create", "update", "delete", "defaults", "jobs", "status", "logs", "logs-clear"],
    )
    sp_tree.add_argument("--id", help="目录树任务 id（run/full/update/delete 使用）")
    sp_tree.add_argument("--folder", help="115 文件夹路径（create/update/defaults 使用，如 影视库/电视剧）")
    sp_tree.add_argument("--name", help="树文件名（create/update 可选，默认 目录树-路径段…）")

    # offline
    sp_offline = sp.add_parser("offline", help="115 离线任务诊断")
    sp_offline.add_argument("action", choices=["list"], help="列出 115 官方离线任务")
    sp_offline.add_argument("--page", type=int, default=1, help="任务列表页码")

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
    sp_share.add_argument("--raw-text", default="", help="原始文本（附加在链接后用于解析）(preview)")
    sp_share.add_argument("--paged", action="store_true", help="分页模式 (preview)")
    sp_share.add_argument("--folders-only", action="store_true", help="仅显示文件夹 (preview)")
    sp_share.add_argument("--force-refresh", action="store_true", help="强制刷新缓存 (preview)")
    sp_share.add_argument("--offset", type=int, default=0, help="分页偏移 (preview)")
    sp_share.add_argument("--limit", type=int, default=0, help="分页条数 (preview)")

    # scrape
    sp_scrape = sp.add_parser("scrape", help="刮削管理")
    sp_scrape.add_argument("action", choices=["identify", "rename-plan", "diff", "jobs", "providers", "entries", "folders", "rename", "rename-warning", "jobs-create", "move", "copy", "delete", "rollback", "jobs-clear", "batch-preferences"])
    sp_scrape.add_argument("path", nargs="*", help="文件路径 (identify/rename-plan/move/copy/delete/rename/rename-warning/jobs-create) 或子动作 get|set|clear (batch-preferences)")
    sp_scrape.add_argument("--job-id", default="", help="Job ID (diff/rollback)")
    sp_scrape.add_argument("--provider", default="", help="提供商 (jobs/move/copy/delete/rename)")
    sp_scrape.add_argument("--limit", type=int, default=20, help="列表条数 (jobs)")
    sp_scrape.add_argument("--dest", default="", help="目标路径 (move/copy)")
    sp_scrape.add_argument("--name", default="", help="新名称 (rename)")
    sp_scrape.add_argument("--new-path", default="", help="新路径 (rename-warning)")
    sp_scrape.add_argument("--cid", default="0", help="目录 ID (folders)")
    sp_scrape.add_argument("--yes", action="store_true", help="跳过确认 (delete)")
    sp_scrape.add_argument("--parent-id", default="", help="父目录 ID (rename/delete)")
    sp_scrape.add_argument("--source-cid", default="", help="源目录 ID (move/copy)")
    sp_scrape.add_argument("--tmdb-id", default="", help="TMDB ID (jobs-create, 可选)")
    sp_scrape.add_argument("--media-type", default="", choices=["movie", "tv"], help="TMDB 媒体类型 (jobs-create)")
    sp_scrape.add_argument("--file-name-mode", default="", choices=["keep", "clean", "standard"], help="文件命名方式 (rename-plan/batch-preferences set)")
    sp_scrape.add_argument("--no-rename-folders", action="store_true", help="不重命名文件夹 (rename-plan)")
    sp_scrape.add_argument("--no-season-subfolder", action="store_true", help="不创建 Season 子文件夹 (rename-plan)")
    sp_scrape.add_argument("--include-tmdb-id", action="store_true", help="文件夹名写入 TMDB ID (rename-plan)")
    sp_scrape.add_argument("--delete-ad-files", action="store_true", help="整理时删除广告文件 (rename-plan)")
    sp_scrape.add_argument("--title-language", default="", choices=["auto", "zh", "en"], help="标题语言 (rename-plan)")
    sp_scrape.add_argument("--season", type=int, default=None, help="未识别时默认季号 (rename-plan)")
    sp_scrape.add_argument("--episode-mode", default="", choices=["auto", "seasonal", "absolute"], help="季集识别方式 (rename-plan)")
    sp_scrape.add_argument("--preserve-file-info", action="store_true", help="保留原文件细节标签 (rename-plan)")
    sp_scrape.add_argument("--options-json", default="", help="JSON 选项对象 (rename-plan / batch-preferences set)")

    # watchlist
    sp_wl = sp.add_parser("watchlist", help="推荐清单")
    sp_wl.add_argument("action", choices=["list", "add", "remove", "update"])
    sp_wl.add_argument("tmdb_id", nargs="*", help="TMDB ID (add/remove/update)")
    sp_wl.add_argument("--id", default="", help="DB 记录 ID (remove/update, 通过 list 获取)")
    sp_wl.add_argument("--status", default="done",
                       choices=["want", "subscribed", "done"],
                       help="状态 (update)")
    sp_wl.add_argument("--title", default="", help="标题 (add)")
    sp_wl.add_argument("--type", default="movie", choices=["movie", "tv"], help="媒体类型 (add)")
    sp_wl.add_argument("--original-title", default="", help="原始标题 (add)")
    sp_wl.add_argument("--year", default="", help="年份 (add)")
    sp_wl.add_argument("--poster-url", default="", help="海报 URL (add)")
    sp_wl.add_argument("--overview", default="", help="简介 (add)")
    sp_wl.add_argument("--vote-average", type=float, default=0.0, help="评分 (add)")

    # strm
    sp_strm = sp.add_parser("strm", help="STRM 管理")
    sp_strm.add_argument("action", choices=["orphans", "cleanup", "dirs"])

    # resource
    sp_rsrc = sp.add_parser("resource", help="资源中心管理")
    sp_rsrc.add_argument("action", choices=["import", "preview", "quick-links", "delete"])
    sp_rsrc.add_argument("sub_action", nargs="?", default="list", help="quick-links 子操作 (list/add/remove)")
    sp_rsrc.add_argument("--id", dest="resource_id", default="", help="资源 ID (delete)")
    sp_rsrc.add_argument("--text", default="", help="资源文本 (import/preview)")
    sp_rsrc.add_argument("--provider", default="115", help="网盘提供商 (import)")
    sp_rsrc.add_argument("--name", default="", help="名称 (quick-links add/remove)")
    sp_rsrc.add_argument("--url", default="", help="链接 URL (quick-links add)")
    sp_rsrc.add_argument("--yes", action="store_true", help="跳过确认 (delete)")
    sp_rsrc.add_argument("--source-name", default="", help="来源名称 (import/preview)")
    sp_rsrc.add_argument("--source-type", default="", help="来源类型 (import/preview, 默认 manual)")
    sp_rsrc.add_argument("--channel-name", default="", help="频道名称 (import/preview)")
    sp_rsrc.add_argument("--published-at", default="", help="发布时间 (import/preview)")
    sp_rsrc.add_argument("--message-url", default="", help="消息链接 (import/preview)")

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
        "offline": cmd_offline,
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
