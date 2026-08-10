import io
from http.cookies import SimpleCookie
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..core import *  # noqa: F401,F403
from ..db import retry_sqlite_locked
from ..memory import release_process_memory
from .strm_files import delete_managed_strm_file, managed_strm_file_path

TREE_SYNC_PATH_BATCH_SIZE = max(
    100,
    min(5000, int(os.environ.get("TREE_SYNC_PATH_BATCH_SIZE", 1000) or 1000)),
)
TREE_SYNC_SQLITE_SELECT_CHUNK_SIZE = 800


def _format_tree_elapsed_seconds(seconds: float) -> str:
    return f"{max(0.0, float(seconds or 0.0)):.2f}秒"


def _normalize_tree_source_relative_path(raw_source: Any, cfg: Dict[str, Any]) -> str:
    source = str(raw_source or "").strip()
    if not source:
        return ""
    if "://" in source:
        parsed = urllib.parse.urlsplit(source)
        marker_idx = (parsed.path or "").lower().find("/d")
        if marker_idx >= 0:
            encoded = (parsed.path or "")[marker_idx + 2 :].lstrip("/")
            source = urllib.parse.unquote(encoded) if encoded else ""
        else:
            source = parsed.path or ""
    normalized_remote = normalize_remote_path(source)
    matched = match_mount_point_by_remote_path(cfg, normalized_remote)
    if matched and normalize_mount_provider(matched.get("provider", "")) == "115":
        return normalize_relative_path(matched.get("relative_path", ""))
    return normalize_relative_path(source)


def _resolve_115_file_entry_by_relative_path(cookie: str, relative_path: str) -> Dict[str, Any]:
    normalized = normalize_relative_path(relative_path)
    if not normalized:
        raise RuntimeError("目录树文件路径不能为空")
    parent_rel = normalize_relative_path(os.path.dirname(normalized))
    file_name = str(os.path.basename(normalized) or "").strip()
    if not file_name:
        raise RuntimeError("目录树文件路径不合法")
    parent_cid = resolve_115_folder_id_by_path(cookie, parent_rel) if parent_rel else "0"
    entries = list_115_entries(cookie, parent_cid)
    matched = next(
        (
            item
            for item in entries
            if (not bool(item.get("is_dir"))) and str(item.get("name", "")).strip() == file_name
        ),
        None,
    )
    if not matched:
        raise RuntimeError(f"115 网盘文件不存在：{normalized}")
    return dict(matched)


def _collect_115_download_urls(payload: Any) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()

    def push(url_value: Any) -> None:
        token = str(url_value or "").strip()
        if (not token) or (not token.lower().startswith(("http://", "https://"))) or token in seen:
            return
        seen.add(token)
        urls.append(token)

    def walk(node: Any) -> None:
        if isinstance(node, str):
            push(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("url", "download_url", "file_url", "download_url_web", "download_url_web2"):
            walk(node.get(key))
        for key in ("data", "urls", "result", "info"):
            walk(node.get(key))

    walk(payload)
    return urls


def _resolve_115_download_payload(cookie: str, pick_code: str) -> Tuple[List[str], str]:
    throttle_115_api_requests()
    request_headers = {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://115.com/",
        "Origin": "https://115.com",
        "User-Agent": "Mozilla/5.0 115-media-hub",
    }
    url = "https://webapi.115.com/files/download?pickcode=" + urllib.parse.quote(pick_code)
    request = urllib.request.Request(url, headers=request_headers, method="GET")
    with urllib.request.urlopen(request, timeout=45) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read().decode(charset, errors="ignore")
        result = safe_json_loads(body, {})
        response_set_cookies = resp.headers.get_all("Set-Cookie") or []
    if not isinstance(result, dict):
        raise RuntimeError("115 下载地址解析返回异常")
    if not bool(result.get("state", False)):
        detail = (
            str(result.get("error", "")).strip()
            or str(result.get("msg", "")).strip()
            or str(result.get("message", "")).strip()
            or "115 下载地址解析失败"
        )
        raise RuntimeError(detail)
    download_urls = _collect_115_download_urls(result)
    if not download_urls:
        raise RuntimeError("115 返回成功，但未解析到下载链接")
    extra_cookie_pairs: List[str] = []
    for raw_cookie in response_set_cookies:
        jar = SimpleCookie()
        try:
            jar.load(str(raw_cookie or ""))
        except Exception:
            continue
        for key, morsel in jar.items():
            token = f"{str(key or '').strip()}={str(morsel.value or '').strip()}"
            if token and token not in extra_cookie_pairs:
                extra_cookie_pairs.append(token)
    return download_urls, "; ".join(extra_cookie_pairs)


def _download_tree_file_bytes(download_urls: List[str], cookie: str, download_cookie: str = "") -> bytes:
    def _build_download_url_candidates(raw_url: str) -> List[str]:
        source = str(raw_url or "").strip()
        if not source:
            return []
        candidates: List[str] = []
        seen: Set[str] = set()

        def push(url_value: str) -> None:
            token = str(url_value or "").strip()
            if (not token) or token in seen:
                return
            seen.add(token)
            candidates.append(token)

        push(source)
        try:
            parts = urllib.parse.urlsplit(source)
            if parts.scheme.lower() in ("http", "https") and parts.netloc:
                # 仅规范 path，保留 query 原样，避免破坏签名参数。
                encoded_path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/%:@+")
                path_only = urllib.parse.urlunsplit((parts.scheme, parts.netloc, encoded_path, parts.query, parts.fragment))
                push(path_only)
                normalized = normalize_http_url(source)
                push(normalized)
        except Exception:
            pass
        return candidates

    def _request_binary_raw_url(url: str, headers: Optional[Dict[str, str]]) -> bytes:
        target_url = str(url or "").strip()
        if not target_url.lower().startswith(("http://", "https://")):
            raise RuntimeError("目录树下载链接不合法")
        request = urllib.request.Request(target_url, headers=dict(headers or {}), method="GET")
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.read()

    merged_cookie = "; ".join([part for part in [str(cookie or "").strip(), str(download_cookie or "").strip()] if part])
    header_candidates: List[Optional[Dict[str, str]]] = [
        {
            "Cookie": merged_cookie,
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "Cookie": str(download_cookie or "").strip(),
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "Referer": "https://115.com/",
            "Origin": "https://115.com",
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        {
            "User-Agent": "Mozilla/5.0 115-media-hub",
            "Accept": "*/*",
        },
        None,
    ]
    last_error: Optional[Exception] = None
    expanded_urls: List[str] = []
    for download_url in download_urls:
        expanded_urls.extend(_build_download_url_candidates(download_url))
    for expanded_url in expanded_urls:
        for headers in header_candidates:
            try:
                data = _request_binary_raw_url(expanded_url, headers)
                if data is not None:
                    return data
            except Exception as exc:
                last_error = exc
                continue
    if last_error is not None:
        raise RuntimeError(f"目录树文件下载失败: {last_error}") from last_error
    raise RuntimeError("目录树文件下载失败")


def _fetch_115_tree_file_bytes(cookie: str, source_rel: str) -> bytes:
    entry = _resolve_115_file_entry_by_relative_path(cookie, source_rel)
    pick_code = str(entry.get("pick_code", "")).strip()
    if not pick_code:
        raise RuntimeError(f"目录树文件缺少 pickcode：{source_rel}")
    download_urls, download_cookie = _resolve_115_download_payload(cookie, pick_code)
    return _download_tree_file_bytes(download_urls, cookie, download_cookie)


def _load_tree_raw_cache(cache_path: str) -> Optional[bytes]:
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "rb") as f:
            payload = f.read()
    except Exception:
        return None
    return payload if payload else None


def _save_tree_raw_cache(cache_path: str, raw_bytes: bytes) -> None:
    payload = raw_bytes or b""
    if not payload:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(payload)
    os.replace(tmp_path, cache_path)


def _decode_tree_file_text(raw_bytes: bytes) -> str:
    payload = raw_bytes or b""
    if not payload:
        return ""
    for encoding in ("utf-8-sig", "utf-16", "utf-16le", "gb18030", "utf-8"):
        try:
            text = payload.decode(encoding)
            if text:
                return text
        except Exception:
            continue
    return payload.decode("utf-8", errors="ignore")


def _scan_tree_text(
    content: str,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Optional[Callable[[str], None]] = None,
) -> Tuple[int, int, int]:
    path_stack: Dict[int, str] = {}
    lines_total = 0
    nodes_total = 0
    matched_total = 0
    for raw_line in io.StringIO(str(content or "")):
        line = str(raw_line or "").replace("\ufeff", "")
        if not line.strip():
            continue
        lines_total += 1
        level = line.count("|")
        clean_name = re.sub(r"^[|\s—-]+", "", line).strip()
        if not clean_name:
            continue
        nodes_total += 1
        for stale_level in [key for key in path_stack.keys() if key > level]:
            path_stack.pop(stale_level, None)
        path_stack[level] = clean_name
        if not is_video_file(clean_name, user_exts):
            continue
        # 对齐 0.2.2：不强制要求 0..level 每层都存在，按已有层级拼接即可。
        full_parts = [path_stack[depth] for depth in range(level + 1) if depth in path_stack]
        if not full_parts:
            continue
        rel_parts = full_parts[max(0, int(exclude or 0)) :]
        final_rel_path = join_relative_path(prefix, "/".join(rel_parts))
        if final_rel_path:
            matched_total += 1
            if on_match is not None:
                on_match(final_rel_path)
    return matched_total, lines_total, nodes_total


def _stream_tree_file_matches(
    raw_bytes: bytes,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Callable[[str], None],
) -> Tuple[int, int, int]:
    content = _decode_tree_file_text(raw_bytes)
    if not str(content or "").strip():
        raise RuntimeError("目录树文件为空")
    matched_total, lines_total, nodes_total = _scan_tree_text(content, user_exts, prefix, exclude, on_match=on_match)
    return matched_total, lines_total, nodes_total


def _replay_tree_cache(cache_path: str, on_match: Callable[[str], None]) -> int:
    matched_total = 0
    if not os.path.exists(cache_path):
        return matched_total
    with open(cache_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            rel_path = normalize_relative_path(str(raw_line or "").strip())
            if not rel_path:
                continue
            on_match(rel_path)
            matched_total += 1
    return matched_total


def _stream_tree_matches_to_cache(
    cache_path: str,
    raw_bytes: bytes,
    user_exts: Set[str],
    prefix: str,
    exclude: int,
    on_match: Callable[[str], None],
) -> Tuple[int, int, int]:
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp_path = cache_path + ".tmp"
    matched_total = 0
    lines_total = 0
    nodes_total = 0
    with open(tmp_path, "w", encoding="utf-8") as cache_file:
        def handle_match(rel_path: str) -> None:
            nonlocal matched_total
            normalized = normalize_relative_path(rel_path)
            if not normalized:
                return
            cache_file.write(normalized)
            cache_file.write("\n")
            on_match(normalized)
            matched_total += 1

        try:
            _matched_total, lines_total, nodes_total = _stream_tree_file_matches(
                raw_bytes,
                user_exts,
                prefix,
                exclude,
                handle_match,
            )
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
    os.replace(tmp_path, cache_path)
    return matched_total, lines_total, nodes_total


def _iter_chunks(values: List[Any], chunk_size: int) -> List[List[Any]]:
    size = max(1, int(chunk_size or 1))
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def _build_local_file_path_hash(rel_path: str) -> str:
    return hashlib.md5(rel_path.encode("utf-8")).hexdigest()


def _mark_local_files_seen_batch(
    cursor: sqlite3.Cursor,
    rel_paths: List[str],
    scan_token: str,
) -> Tuple[List[str], int]:
    ordered_rows: List[Tuple[str, str]] = []
    batch_seen_hashes: Set[str] = set()
    duplicate_count = 0

    for raw_path in rel_paths:
        rel_path = normalize_relative_path(raw_path)
        if not rel_path:
            continue
        path_hash = _build_local_file_path_hash(rel_path)
        if path_hash in batch_seen_hashes:
            duplicate_count += 1
            continue
        batch_seen_hashes.add(path_hash)
        ordered_rows.append((path_hash, rel_path))

    if not ordered_rows:
        return [], duplicate_count

    def write_batch() -> Tuple[List[str], int]:
        duplicate_total = duplicate_count
        existing_rows: Dict[str, Tuple[str, str]] = {}
        path_hashes = [path_hash for path_hash, _rel_path in ordered_rows]
        for chunk in _iter_chunks(path_hashes, TREE_SYNC_SQLITE_SELECT_CHUNK_SIZE):
            placeholders = ",".join("?" for _item in chunk)
            cursor.execute(
                f"SELECT path_hash, relative_path, scan_token FROM local_files WHERE path_hash IN ({placeholders})",
                chunk,
            )
            for path_hash, existing_rel_path, existing_scan_token in cursor.fetchall():
                existing_rows[str(path_hash or "")] = (
                    normalize_relative_path(existing_rel_path),
                    str(existing_scan_token or ""),
                )

        upsert_rows: List[Tuple[str, str, str]] = []
        fresh_paths: List[str] = []
        for path_hash, rel_path in ordered_rows:
            existing_rel_path, existing_scan_token = existing_rows.get(path_hash, ("", ""))
            if existing_rel_path == rel_path and existing_scan_token == scan_token:
                duplicate_total += 1
                continue
            upsert_rows.append((path_hash, rel_path, scan_token))
            fresh_paths.append(rel_path)

        if upsert_rows:
            cursor.executemany(
                """
                INSERT INTO local_files (path_hash, relative_path, scan_token)
                VALUES (?, ?, ?)
                ON CONFLICT(path_hash) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    scan_token = excluded.scan_token
                WHERE local_files.relative_path <> excluded.relative_path
                   OR local_files.scan_token <> excluded.scan_token
                """,
                upsert_rows,
            )
        return fresh_paths, duplicate_total

    def transactional_write() -> Tuple[List[str], int]:
        conn = cursor.connection
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                cursor.execute("BEGIN IMMEDIATE")
            result = write_batch()
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction:
                conn.rollback()
            raise

    return retry_sqlite_locked(transactional_write)


async def run_sync(use_local: bool = False, force_full: bool = False) -> None:
    if task_status["running"]:
        return
    task_status["running"] = True
    schedule_ui_state_push(0)
    cfg = get_config()
    os.makedirs(TREE_DIR, exist_ok=True)
    run_started_at = time.perf_counter()
    prefetch_elapsed_seconds = 0.0
    generate_elapsed_seconds = 0.0
    cleanup_elapsed_seconds = 0.0
    generated_file_count = 0
    unchanged_file_count = 0
    duplicate_scan_count = 0
    total_files = 0
    stale_file_candidates = 0
    deleted_file_count = 0
    delete_failed_file_count = 0
    stale_index_count = 0
    conn: Optional[sqlite3.Connection] = None

    try:
        config_error = validate_tree_runtime_config(cfg, use_local)
        if config_error:
            raise RuntimeError(config_error)

        if use_local:
            await write_log("ℹ 目录树本地调试模式已弃用：当前统一使用容器内 115 源")

        trees = [t for t in cfg.get("trees", []) if str((t or {}).get("path", "")).strip()]
        fetched_tree_count = 0
        local_raw_cache_count = 0
        parsed_tree_count = 0
        skipped_tree_count = 0
        user_exts = get_user_extensions(cfg)
        check_hash_enabled = bool(cfg.get("check_hash", False))
        can_skip_by_hash = check_hash_enabled and cfg.get("sync_mode") != "full" and not force_full
        last_hash_state = parse_last_hash_state(cfg.get("last_hash", ""))
        last_tree_hashes = last_hash_state.get("trees", {}) if isinstance(last_hash_state.get("trees", {}), dict) else {}
        last_tree_keys = last_hash_state.get("tree_keys", []) if isinstance(last_hash_state.get("tree_keys", []), list) else []
        current_tree_hashes: Dict[str, Dict[str, str]] = {}
        current_tree_keys: List[str] = []
        if check_hash_enabled:
            if can_skip_by_hash:
                await write_log("ℹ 已开启 MD5 校验：目录树内容无变化时将复用缓存并跳过同步")
            else:
                await write_log("ℹ 已开启 MD5 校验，但当前为全量重写 STRM，跳过策略不生效")

        write_mode_label = "全量重写 STRM" if cfg.get("sync_mode") == "full" or force_full else "增量写入 STRM"
        cleanup_mode_label = "开启" if cfg.get("sync_clean", True) else "关闭"
        await write_log(
            f"━━━━━━━━━━【任务开始 | 目录树文件 | 源 {len(trees)} 个 | 写入 {write_mode_label} | 清理过期 STRM {cleanup_mode_label}】━━━━━━━━━━",
            "task-divider",
        )

        mount_prefix_115 = get_mount_prefix(cfg, "115")
        if not mount_prefix_115:
            raise RuntimeError("请先在参数配置中填写 115 网盘路径前缀")

        source_contexts: List[Dict[str, Any]] = []
        for idx, tree in enumerate(trees):
            raw_source = tree.get("path", "")
            source_rel = _normalize_tree_source_relative_path(raw_source, cfg)
            prefix = normalize_relative_path(tree.get("prefix", ""))
            exclude = max(0, int(tree.get("exclude", 1) or 1))
            source_label = "/" + source_rel if source_rel else "/"
            tree_key = build_tree_cache_key(
                {
                    "source_type": "tree_file",
                    "path": str(raw_source or "").strip(),
                    "prefix": prefix,
                    "exclude": exclude,
                }
            )
            current_tree_keys.append(tree_key)
            tree_cache_path = os.path.join(TREE_DIR, f"cache_{tree_key}.txt")
            tree_raw_cache_path = os.path.join(TREE_DIR, f"raw_{tree_key}.txt")

            await update_progress(
                "读取目录树文件",
                (idx / max(len(trees), 1) * 35),
                f"源 {idx + 1}/{len(trees)}：{source_label}",
            )
            await write_log(f"读取目录树文件源: {source_label}")

            cookie = str(cfg.get("cookie_115", "")).strip()
            source_fetch_started_at = time.perf_counter()
            try:
                raw_bytes = await asyncio.to_thread(_fetch_115_tree_file_bytes, cookie, source_rel)
                fetched_tree_count += 1
                await asyncio.to_thread(_save_tree_raw_cache, tree_raw_cache_path, raw_bytes)
            except Exception as exc:
                cached_raw_bytes = await asyncio.to_thread(_load_tree_raw_cache, tree_raw_cache_path)
                if cached_raw_bytes is None:
                    raise
                raw_bytes = cached_raw_bytes
                local_raw_cache_count += 1
                await write_log(
                    f"⚠ 源 {idx + 1} 联网读取失败，已使用上次成功保存的本地目录树副本：{exc}",
                    "warn",
                )
            prefetch_elapsed_seconds += max(0.0, time.perf_counter() - source_fetch_started_at)
            file_hash = hashlib.md5(raw_bytes).hexdigest()
            parse_signature = build_tree_parse_signature(file_hash, user_exts)
            current_tree_hashes[tree_key] = {"parse_signature": parse_signature}
            old_state = last_tree_hashes.get(tree_key, {})
            old_signature = old_state.get("parse_signature", "") if isinstance(old_state, dict) else ""
            unchanged = bool(
                can_skip_by_hash
                and old_signature
                and old_signature == parse_signature
                and os.path.exists(tree_cache_path)
            )
            source_contexts.append(
                {
                    "idx": idx,
                    "source_rel": source_rel,
                    "source_label": source_label,
                    "prefix": prefix,
                    "exclude": exclude,
                    "tree_cache_path": tree_cache_path,
                    "tree_raw_cache_path": tree_raw_cache_path,
                    "unchanged": unchanged,
                }
            )
            del raw_bytes

        tree_layout_changed = sorted(last_tree_keys) != sorted(current_tree_keys)
        all_trees_unchanged = bool(source_contexts) and all(context["unchanged"] for context in source_contexts)
        if can_skip_by_hash and all_trees_unchanged and tree_layout_changed:
            await write_log("ℹ 目录树源配置有变更，继续执行同步以校正结果")
        if can_skip_by_hash and all_trees_unchanged and not tree_layout_changed:
            prefetch_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
            await write_log(
                f"本轮概况：联网读取 {fetched_tree_count} 个，本地副本 {local_raw_cache_count} 个，缓存复用 0 个，解析 0 个"
            )
            await write_log("✅ MD5 校验命中：全部目录树无变动，跳过解析与同步")
            await write_log(
                f"任务耗时：前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | 总 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)}"
            )
            await write_log("━━━━━━━━━━【任务结束 | 目录树文件 | MD5 校验命中】━━━━━━━━━━", "task-divider")
            await update_progress("任务完成", 100, "MD5 校验命中：无变动")
            return

        ensure_db()
        conn = open_db()
        conn.isolation_level = None
        cursor = conn.cursor()
        scan_token = f"tree-{int(time.time())}-{secrets.token_hex(8)}"
        generate_started_at = time.perf_counter()
        current_source_state: Dict[str, str] = {"label": ""}
        pending_rel_paths: List[str] = []

        def generate_strm_for_rel_path(rel_path: str) -> None:
            nonlocal total_files, duplicate_scan_count, generated_file_count, unchanged_file_count
            normalized = normalize_relative_path(rel_path)
            if not normalized:
                return
            total_files += 1
            target = managed_strm_file_path(normalized)
            needs_regenerate = (not os.path.exists(target)) or cfg["sync_mode"] == "full" or force_full
            if needs_regenerate:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                remote_path = build_provider_remote_path(cfg, "115", normalized)
                strm_url = build_strm_play_url(cfg, remote_path)
                with open(target, "w", encoding="utf-8") as sf:
                    sf.write(strm_url)
                generated_file_count += 1
            else:
                unchanged_file_count += 1

            if total_files % 1000 == 0:
                task_status["progress"].update(
                    {
                        "step": "生成STRM",
                        "percent": 40,
                        "detail": f"{current_source_state['label']} | 已处理 {total_files} 条",
                    }
                )
                schedule_ui_state_push(0)

        def flush_path_batch() -> None:
            nonlocal duplicate_scan_count
            if not pending_rel_paths:
                return
            batch_paths = list(pending_rel_paths)
            pending_rel_paths.clear()
            fresh_paths, batch_duplicates = _mark_local_files_seen_batch(cursor, batch_paths, scan_token)
            duplicate_scan_count += batch_duplicates
            for fresh_path in fresh_paths:
                generate_strm_for_rel_path(fresh_path)

        def process_rel_path(rel_path: str) -> None:
            normalized = normalize_relative_path(rel_path)
            if not normalized:
                return
            pending_rel_paths.append(normalized)
            if len(pending_rel_paths) >= TREE_SYNC_PATH_BATCH_SIZE:
                flush_path_batch()

        scanned_tree_line_total = 0
        scanned_tree_node_total = 0
        for source_context in source_contexts:
            idx = int(source_context["idx"])
            source_rel = str(source_context["source_rel"])
            current_source_state["label"] = f"源 {idx + 1}/{len(trees)}：{source_context['source_label']}"
            if source_context["unchanged"]:
                reused_count = _replay_tree_cache(source_context["tree_cache_path"], process_rel_path)
                skipped_tree_count += 1
                await write_log(f"源 {idx + 1} MD5 无变化，复用缓存 {reused_count} 条")
                continue

            try:
                raw_bytes = _load_tree_raw_cache(source_context["tree_raw_cache_path"])
                if raw_bytes is None:
                    raise RuntimeError(f"目录树本地副本不存在：{source_rel}")
                matched_count, scanned_lines, scanned_nodes = _stream_tree_matches_to_cache(
                    source_context["tree_cache_path"],
                    raw_bytes,
                    user_exts,
                    source_context["prefix"],
                    source_context["exclude"],
                    process_rel_path,
                )
            except RuntimeError as exc:
                if str(exc) == "目录树文件为空":
                    raise RuntimeError(f"目录树文件为空：{source_rel}") from exc
                raise

            parsed_tree_count += 1
            scanned_tree_line_total += scanned_lines
            scanned_tree_node_total += scanned_nodes
            await write_log(f"源 {idx + 1} 解析完成: 行 {scanned_lines} | 节点 {scanned_nodes} | 命中 {matched_count}")
            del raw_bytes
            flush_path_batch()

        flush_path_batch()

        if check_hash_enabled:
            cfg["last_hash"] = json.dumps(
                {"version": 2, "tree_keys": current_tree_keys, "trees": current_tree_hashes},
                ensure_ascii=False,
                sort_keys=True,
            )
            save_config(cfg)

        if duplicate_scan_count > 0:
            await write_log(f"检测到重复路径 {duplicate_scan_count} 条，已去重后继续同步")
        generate_elapsed_seconds = max(0.0, time.perf_counter() - generate_started_at)
        await write_log(
            (
                f"本轮概况：联网读取 {fetched_tree_count} 个 | 本地副本 {local_raw_cache_count} 个 | 缓存复用 {skipped_tree_count} 个 | 解析 {parsed_tree_count} 个 | "
                f"目录树行 {scanned_tree_line_total} | 目录树节点 {scanned_tree_node_total} | 命中 {total_files}"
            )
        )
        await write_log(f"解析完成，共发现 {total_files} 个有效文件")
        if total_files == 0:
            if fetched_tree_count > 0 or local_raw_cache_count > 0 or use_local:
                await write_log("⚠ 目录树读取成功，但未匹配到可生成文件；本次按成功结束并跳过过期 STRM 清理")
                total_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
                await write_log(
                    f"任务耗时：前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | 总 {_format_tree_elapsed_seconds(total_elapsed_seconds)}"
                )
                await write_log("━━━━━━━━━━【任务结束 | 目录树文件 | 执行成功】━━━━━━━━━━", "task-divider")
                await update_progress("任务完成", 100, "目录树读取成功，但未匹配可生成文件")
                return
            raise RuntimeError("扫描结果为空，且未成功读取目录树文件")

        cleanup_started_at = time.perf_counter()
        await update_progress("清理过期STRM", 90, f"准备校验 {total_files} 条扫描结果")

        cursor.execute("SELECT COUNT(*) FROM local_files WHERE scan_token <> ?", (scan_token,))
        stale_file_candidates = int((cursor.fetchone() or (0,))[0] or 0)
        if stale_file_candidates > 0 and cfg.get("sync_clean", True):
            cursor.execute("SELECT relative_path FROM local_files WHERE scan_token <> ?", (scan_token,))
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                for (dead_path,) in rows:
                    try:
                        if delete_managed_strm_file(str(dead_path or "")):
                            deleted_file_count += 1
                    except Exception:
                        delete_failed_file_count += 1

        def delete_stale_local_files() -> int:
            cursor.execute("BEGIN IMMEDIATE")
            try:
                cursor.execute("DELETE FROM local_files WHERE scan_token <> ?", (scan_token,))
                deleted_count = max(0, int(cursor.rowcount or 0))
                conn.commit()
                return deleted_count
            except Exception:
                conn.rollback()
                raise

        stale_index_count = retry_sqlite_locked(delete_stale_local_files)
        cleanup_elapsed_seconds = max(0.0, time.perf_counter() - cleanup_started_at)

        cleanup_mode_label = "开启" if cfg.get("sync_clean", True) else "关闭"
        await update_progress("任务完成", 100, f"同步成功: {total_files} 文件")
        await write_log(
            f"生成汇总: 新增/更新 {generated_file_count} | 保持不变 {unchanged_file_count} | 总扫描 {total_files}"
        )
        await write_log(
            (
                f"清理汇总: 清理过期 STRM {cleanup_mode_label} | 过期记录 {stale_file_candidates} | 删除 STRM {deleted_file_count} | "
                f"删除失败 {delete_failed_file_count} | 索引清理 {stale_index_count}"
            )
        )
        total_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
        await write_log(
            (
                f"任务耗时: 前置处理 {_format_tree_elapsed_seconds(prefetch_elapsed_seconds)} | "
                f"生成写入 {_format_tree_elapsed_seconds(generate_elapsed_seconds)} | "
                f"清理落库 {_format_tree_elapsed_seconds(cleanup_elapsed_seconds)} | "
                f"总 {_format_tree_elapsed_seconds(total_elapsed_seconds)}"
            )
        )
        await write_log("━━━━━━━━━━【任务结束 | 目录树文件 | 执行成功】━━━━━━━━━━", "task-divider")
    except Exception as exc:
        await write_log(f"❌ 运行故障: {exc}")
        failed_elapsed_seconds = max(0.0, time.perf_counter() - run_started_at)
        await write_log(f"任务耗时: 总 {_format_tree_elapsed_seconds(failed_elapsed_seconds)}", "warn")
        await write_log("━━━━━━━━━━【任务结束 | 目录树文件 | 执行失败】━━━━━━━━━━", "task-divider")
        await update_progress("任务中止", 0, str(exc))
    finally:
        try:
            if conn is not None:
                conn.close()
                conn = None
        except Exception:
            pass
        await asyncio.to_thread(release_process_memory, "tree-sync", True)
        task_status["running"] = False
        schedule_ui_state_push(0)
